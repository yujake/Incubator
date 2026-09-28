"""共享存储：跨进程锁、原子写、事务、事件日志、ID 分配、重建。

这是 A/B 两个智能体唯一的交汇点，因此把三件事集中在这里做对：

1. 不存在"部分写入" —— 一律"写临时文件 → os.replace"，且先校验后落盘。
   校验失败就整笔放弃，快照不会被污染成半成品。
2. 不存在"丢失更新" —— 任何读-改-写都在同一把排他锁内完成。A 追加文献、
   B 改 `processed`，两者并发时若各自"读全表→改一行→写全表"，后写的一方会
   把先写的一方覆盖掉。锁是这里唯一正确的解法。
3. 不存在"说不清谁改了什么" —— 每次落盘同时追加事件到 `events.jsonl`。
   事件里带的是整行 upsert（而不是 diff），于是 `rebuild()` 只需按主键折叠
   就能重建快照；这让"快照损坏/手工改坏"永远可恢复。

多表事务按固定顺序加锁（见 `LOCK_ORDER`），这是避免死锁的标准做法。

## "看着对、其实不成立"的地方（`F-1` / `F-3` / `G-12` / `R6-AN-1`，已修）

上面三句话曾经各自有一个反例，都在全面体检里被实测复现过，修法与代价逐条写在
对应函数的 docstring 里（`_atomic_write` / `tx` 的提交块 / `init` / `rebuild` /
`_merge_counters_for_commit`）：

- `_atomic_write` 的临时名是固定的 `<file>.tmp`，os.replace 不重试 ⇒
  Windows 上两个并发写者互相抢同一个临时名，抛 `PermissionError [WinError 32]`（`F-3`）；
- `init(force=True)` 与 `rebuild()` 完全不加锁，且用 `_atomic_write` 逐个写表 ⇒
  并发写者会看到"表被清空到一半"的中间态（`G-12`）；
- 提交顺序是"先落盘全部快照、再追加事件" ⇒ 两者之间崩一次，磁盘上出现
  "快照里有、事件里没有"的行，而 `rebuild()` 会不报错地丢掉最后一次提交，
  并把 counters 退回到落后于表的状态（`F-1`）；
- 提交块用事务自己那份 counters 缓存整份覆盖 `counters.json` ⇒ 在"事务已读、
  尚未提交"的窗口里 `set_counters` 落盘的写入被静默吞掉（`R6-AN-1`，实测
  999 → 4）。修法就是让 counters 的读-改-写也进写者锁、并对"两个方向"各留一条
  痕迹事件（`R7-AN-1` 补上"盘上被拨低"那一半）⇒ 上面第 2 条承诺对这条路径成立。
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from filelock import FileLock, Timeout

from . import schema as S

#: `_atomic_write` 的 `os.replace` 重试次数与退避基数（`F-3`）。
#: 总等待 = 0.02 + 0.04 + 0.08 + 0.16 + 0.32 = 0.62 秒 —— 足够跨过"另一个进程正
#: 持有目标文件"的瞬间，而短到不会让一次真实的权限错误变成一次长挂起。
#:
#: `R3-10`（重审实测）：这句注释此前漏掉了"第 6 次失败之后还 sleep 了 0.64s"
#: 那一笔，于是注释说 0.62s、实测是 1.27s（`os.replace` 恒定失败时）。而这段代码
#: 正处在写者锁内：多出来的那 0.64 秒会原样叠加到持锁时长上。
#: 修法选的是"让代码与注释一致"而不是"改数字"：最后一次尝试失败之后不再 sleep
#: （反正下一句就是抛 `StoreError`，那一觉是纯等待），总等待于是真的 ≈0.62 秒。
_REPLACE_ATTEMPTS = 6
_REPLACE_BACKOFF_S = 0.02

#: 加锁的固定顺序。任何多表事务都必须按这个顺序取锁，否则两个事务可能互相等待。
#: 新增表一律追加在 counters 之前（counters 永远是最后一把，因为任何 alloc 都要它）。
LOCK_ORDER: tuple[str, ...] = (
    "search_requests",
    "literature",
    "concepts",
    "relations",
    "analysis_reports",
    "research_questions",
    # 猜想：在研究层产生、在实验层被检验 ⇒ 紧跟 research_questions（`draft/30` §T1 第 5 处）。
    "conjectures",
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
        #: 本事务取过号的计数器类别（`R6-AN-1`）。提交块只允许改这些类别 ——
        #: `counters` 是整份写回的，没取过号的类别照盘上的值，否则一个没碰过
        #: 它的在飞事务会把窗口里 `set_counters` 写下的值覆盖回去。
        self._alloc_kinds: set[str] = set()
        #: 每类计数器"本事务读到的那个值"（`R7-AN-1`）。它是"窗口里有没有别的写者"
        #: 的判据：提交时盘上值与本事务自己那次推进之间的差（`cache - base`）是
        #: 本事务自己造成的，不能算别人写过。方向痕迹（`disk_higher` / `disk_lower`）
        #: 也以它为基准 —— 以缓存值为基准会让每一次普通取号都变成"盘上更低"。
        self._alloc_base: dict[str, int] = {}

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

        返回 `True` = 真的插进去了；`False` = 这个键已经有一行，本次什么都没写。

        ⚠️ 它不自己加锁，唯一性只在"读与写同一个临界区"内成立。
        由 `store.tx` 持有该表排他锁来保证：`tx.rows()` 在锁内读的是
        前一个进程刚提交的那一版，所以后到者一定看得见先到者。
        在 `store.tx` 之外调用它 = 把"先读后写"的窗口原样搬回来，
        而代码看起来像加了约束 —— 这是本方法唯一危险的误用方式。

        为什么空键要抛而不是"当作不冲突"：空键要么让每一行都冲突
        （唯一性变成"全表只能有一行"），要么让唯一性完全失效 ——
        两种都不是调用方想要的，所以不给它一个静默的解释。

        `id_kind` 是本实现对提案的一处最小附加（见本提案 §2.3 的
        "冲突时不调 alloc_id ⇒ 重放不消耗号"）：给了它，主键就在判重之后
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

        为什么需要这个公开方法：`tx.rows(t)` 返回的是可变列表，调用方可以直接
        改里面的 dict 或 `del` 掉一项（删行就是这么做的）。那种情况下 `upsert` 不会被调用，
        于是没有任何东西把这张表标成脏 —— 提交时它会被静默跳过，改动凭空消失。
        （此前 docstring 提到过 `mark_dirty` 但它并不存在，调用方只能去摸 `tx._dirty`
        这个私有属性，这是文档与实现对不上。）
        """
        if table not in self.tables:
            raise StoreError(f"事务未声明表 {table}（声明了 {self.tables}）")
        self._dirty.add(table)

    # ---- ID 分配（锁内进行，与建行同事务）
    def alloc_id(self, kind: str) -> str:
        """分配一个 4 位 ID。

        ## 为什么必须在这里跳过已被占用的号（一次真实缺陷的修复）

        `counters.json` 是 ID 分配器的缓存，它的真源是各张表里已经用掉的号。
        两者一旦漂移（手工建行、从台账恢复、外部脚本写入、旧版 `rebuild`），
        分配器就会发出一个已经被占用的号 —— 而 `upsert` 是按主键替换，
        于是新行会静默覆盖掉旧行：不报重复 ID、不报错、旧数据凭空消失。

        实测教训：D 的 `adjudicate` 建矛盾问题时，新建的 (0002,0004) 问题被
        已存在的 0000 顶掉，`new_question_ids` 还返回 `["0000"]` ——
        调用方看到"新建成功"，而知识库里少了一条问题。

        所以这里做三件事（任何一条单独都不够）：

        1. 在已声明的事务表里查一遍该号是否已被占用，占用就往后跳；
        2. 跳完之后把 `counters` 推到最终号 + 1，于是这个缓存会
           自愈（下次 `verify` 不会再报 `counter_behind`）；
        3. 越界（超过 :data:`MAX_ID`）时抛 :class:`IdExhausted`，不静默升位宽。

        为什么用"跳过"而不是"抛异常"：漂移是既成事实（数据已经在表里），
        此时让整个智能体崩掉并不能修好它；往后跳一位既能继续工作，
        又保证了"不会覆盖"。真正的失序仍然由 `verify` 的 `counter_behind`
        与 `id_gap` 报出来 —— 这里负责不破坏数据，`verify` 负责报告失序。

        ## `F-2`：查占用这件事不许被静默跳过

        上面第 1 条曾经写成 `if table is not None and table in self.tables:` ——
        也就是说：没声明目标表时，占用检查被整段跳过，而函数照样发号。
        实测（`temp/auditF-probe1.txt` [D1]）：把 `counters.lit` 拨回 0 之后，
        声明了 `literature` 的事务给出 `0001`（正确地跳过 `0000`），
        而只声明 `counters` 的事务给出 `0000`（已被占用）；随后把这个号写回
        `literature` ⇒ `['first','second']` 变成 `['OVERWRITER','second']`，
        行数不变，旧行静默消失。

        这正是本函数 docstring 第 194-203 行那段教训（D 的 `adjudicate` 被顶号）
        的同一个形态，而它自己的守卫留了一个不报错的缺口。
        现在的判据：`alloc_id(kind)` 要求事务声明了那张表，否则抛
        :class:`StoreError` 并说清"要分配 X 的号就得同时声明表 Y"。
        如果将来真的需要"只取号、不建行"，那必须是一个显式可审计的形状
        （例如另开一个 `reserve_id()` 并说明为什么不需要查占用），而不是
        默默把检查跳过。

        ## `R6-AN-1`：本事务取过哪些类别，提交时要用

        `counters.json` 是整份写回的。提交时若直接拿本事务的缓存覆盖它，
        就会把"事务已读、尚未提交"这个窗口里别的写者（`set_counters`）写下的值
        无声地吞掉（实测：C 写 999、盘上确认 999，B 提交后那份 999 不见了，
        无日志无异常）。
        所以这里记下取过号的类别（`self._alloc_kinds`）；提交块只改这些类别，
        其余类别照盘上的值，并对"盘上比我更靠前"的类别留一条痕迹事件 ——
        见 `Store._merge_counters_for_commit`。
        """
        if kind not in S.ID_COUNTERS:
            raise StoreError(f"未知 ID 类别：{kind}")
        if "counters" not in self.tables:
            raise StoreError("分配 ID 的事务必须声明 counters 表")
        # ⚠️ 必须优先用本事务内已改过的 counters，而不是重新从磁盘读。
        # 否则同一事务里连续 alloc 会反复读到同一个初值，把同一个 ID 发出去多次
        # —— 表现为"多行拿到同一个 lit_id"，而按主键 upsert 会静默互相覆盖。
        c = self._store._dirty_counters
        if c is None:
            c = self._store._load("counters")
            self._store._dirty_counters = c
        counters = c.setdefault("counters", {})
        nxt = int(counters.get(kind, 0))
        # `R7-AN-1`：记下"本事务读到的那一版"。提交时用它（而不是缓存值 c+1）去判断
        # "窗口里有没有别的写者"：`cache - base` 正是本事务自己的那次推进，
        # 拿缓存值当基准会把每一次普通取号都读成"盘上被别的写者拨低了"。
        if kind not in self._alloc_base:
            self._alloc_base[kind] = nxt

        # ---- [1] 跳过已被占用的号（`F-2`：目标表必须已声明，否则拒绝发号）
        field = S.ID_COUNTERS[kind]
        table = next((t for t, spec in S.TABLES.items() if spec["id_field"] == field), None)
        jumped = 0
        if table is not None and table not in self.tables:
            raise StoreError(
                f"分配 {kind} 的号必须同时声明表 {table}（当前事务声明的是 "
                f"{sorted(self.tables)}）。"
                "占用检查只能在目标表被读到的前提下做；跳过它会让发号器发出一个"
                "已被占用的号，而 `upsert` 按主键替换 ⇒ **静默覆盖旧行**（`F-2`）。"
                "若确实只需要取号、不建行，请用一个显式命名的接口并说明理由。"
            )
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
        self._alloc_kinds.add(kind)
        self._record("counters", {"kind": kind, "allocated": f"{nxt:04d}"}, note="alloc_id")
        if jumped:
            # 跳过号这件事必须可见：它是"计数器和表已经漂移"的直接证据。
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
        #: 进程内的批次序号（`F-1` 的提交标记用）—— 让同一毫秒内的两批也不撞号。
        self._batch_seq = itertools.count(1)
        #: 事件序号的水位线（`c-6`）。每次追加前都会与日志尾巴取 max，
        #: 所以它只是"这一进程已经发到哪"，**不是**判断起点 —— 起点永远是
        #: `read_events()` 的尾巴，见 `_next_seq`。声明在这里是为了让
        #: "这个属性一定存在"成为类的事实，而不是某一次调用的副作用。
        self._seq = 0

    # ---------------------------------------------------------------- 初始化
    def _writer_lock(self, *, timeout: float = 60.0) -> FileLock:
        """全体表之外的一把写者锁（`G-12`）。

        为什么在 `LOCK_ORDER` 之外还要一把：`init()` / `rebuild()` / 直接调
        `_atomic_write` 的写者不持有任何表锁，而它们会批量重写多张表。
        实测（`G-12`）的形态是：一个进程在 `init(force=True)` 或 `rebuild()`，
        另一个进程在 `tx()` 里读同一张表 ⇒ 读的人会看到"表被清空到一半 / 只有一半表
        是新版"的中间态 —— 那不是数据竞争，是可观测的中间态泄漏。

        ## 加锁顺序（防死锁的唯一规则）

        规则是：先拿全部表锁，再拿这把写者锁（`tx` 的提交块就是这么做的）。
        `init` / `rebuild` 不拿表锁，所以它们只拿写者锁。任何地方都不许反过来
        （先写者锁、再表锁），否则两个写者会互相等待。

        锁文件放在 `.locks/` 下、名字以 `_` 开头 ⇒ 不会被 `LOCK_ORDER` 的表锁
        认为是某张表（`tx` 只按 `LOCK_ORDER` 拼名字）。
        """
        self.locks.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self.locks / "_writer.lock"), timeout=timeout)

    def init(self, force: bool = False) -> None:
        """建立目录与空表。

        `force=True` 会覆盖已有的表 ⇒ 它是"清空这个工作区"的动作，
        所以在写者锁内完成（`G-12`）：这把锁保证**写者之间**互斥（两个清空/事务不会互相踩），
        它不排除并发读者在清空过程中读到中间态 —— 读侧今天不拿这把锁（`R3-1` 已裁定接受现状）。
        """
        self.data.mkdir(parents=True, exist_ok=True)
        self.library.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        try:
            with self._writer_lock(timeout=60.0):
                for table, spec in S.TABLES.items():
                    p = self.data / spec["file"]
                    if force or not p.exists():
                        self._atomic_write(p, S.empty_table())
                cp = self.data / "counters.json"
                if force or not cp.exists():
                    self._atomic_write(cp, {"schema_version": S.SCHEMA_VERSION, "counters": {}})
                self.events_path.touch(exist_ok=True)
        except Timeout as e:
            raise StoreError(
                "获取写者锁超时（init）。可能有另一个进程正在重建/初始化这个工作区；"
                "若进程已死，锁文件是可安全删除的（filelock 用 OS 锁，不含内容）。"
            ) from e

    def exists(self) -> bool:
        return all((self.data / s["file"]).exists() for s in S.TABLES.values())

    # ---------------------------------------------------------------- 低级 IO
    @staticmethod
    def _dump(doc: dict) -> str:
        return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False) + "\n"

    def set_counters(self, values: Mapping[str, int], *, actor: str, note: str = "") -> dict:
        """公开地写 `counters.json`（`c-7`；`R7-AN-1` 把"窗口里会怎样"写准）。

        ## 这个方法保证什么、不保证什么（逐字事实）

        - 在调用返回时，本方法写的那个文件里就是给定值（拿写者锁、原子落盘）；
          没有在飞事务时，拨低就是拨低，`verify` 会照实报 `counter_behind`。
        - 但如果此刻有另一个事务已经读过 counters、尚未提交，那个事务的提交会把该类别的
          终值取 `max(盘上的值, 它读到的值)`（`R6-AN-1` / `R7-AN-1` 的合并规则）⇒
          在窗口里显式拨低不会降低盘上值，但会留下一条带方向的痕迹
          （`counters_commit_merged`，`direction=disk_lower`，带盘上/缓存/基线/合并四个读数）
          ⇒ 那次写入是可判定的，不是无声消失。
        - 窗口结束后再调用一次，拨低按正常语义生效（重审实测：提交后重试 ⇒ 盘上就是给定值）
          ⇒ 被吞掉的是窗口，不是这个方法本身坏了。
        - 在窗口里写入更大的值同样不会被吞：终值取 max，那次写入直接留在盘上
          （痕迹方向是 `disk_higher`）。

        ## 为什么需要这个公开入口

        `counters.json` 是 ID 分配器的缓存，真源是各张表里用掉的号。少数场景需要把它
        故意拨到某个位置（复现"计数器落后/超前"的缺陷、造探针夹具）。以前只能绕过
        事务直接调私有的 `_atomic_write` —— 实测 `tools/probe_gap_ledger.py` 就是这么干的
        （`c-7`），而那条路既不拿写者锁、也不进事务：

        - 与并发 `tx` 的 `alloc_id` 争同一份 counters ⇒ 计数器漂移 ⇒ 跳号，
          严重时真撞号并被 `upsert` 静默覆盖旧行；
        - 它同时说明"`_atomic_write` 必须在锁内"这条约束只有下划线前缀作提示、没有结构性防线
          （探针能这么写，别人也能）。

        所以这里给它一个公开路径：拿写者锁（与 `init`/`rebuild`/`tx` 的提交块同一把），
        再原子落盘。调用方从此不需要、也不应该去碰私有 API。

        ## `R6-AN-1`：这把写者锁不保证"与在飞事务不漂移"，别把它读成那句承诺

        重审实测（两个真进程）：C 调用本方法写下 `concept=999`（当时盘上确认 999），
        另一个进程里的事务 B 在 C 之前就读过 counters、在 C 之后才提交 ⇒
        提交后盘上是 4，999 消失，且没有任何日志或异常。
        原因是提交侧当时用事务自己那份旧缓存整份覆盖 `counters.json`，
        而事务体全程不持写者锁（写者锁只在提交块里拿）。
        撤掉本方法里的写者锁后同一形态读数完全相同 ⇒ 分辨力不在这一把锁上，
        而在提交侧的合并：`_merge_counters_for_commit` 把 counters 的读-改-写
        搬进了同一把写者锁，并对两个方向各留一条痕迹事件。
        所以这一段不许再写成"拿了写者锁 ⇒ 与并发 tx 不漂移"。

        返回值是写进去的文档（便于日志与断言）。不做"计数器不得小于表里最大号"这类
        校验：本方法的用途之一正是故意造出落后状态去复现缺陷（窗口内的那一次按上面
        的规则处置，窗口外的那一次照常生效），替调用方做策略会把这个用途堵掉；
        该判据属于 `verify_all`（`counter_behind`）。
        """
        kind_map = S.ID_COUNTERS
        unknown = sorted(set(values) - set(kind_map))
        if unknown:
            raise StoreError(
                f"set_counters 收到未知的计数器类别 {unknown}（合法：{sorted(kind_map)}）—— "
                "写进去的键必须能被 alloc_id 读懂，否则它只是盘上一个没人读的数字"
            )
        for k, v in values.items():
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise StoreError(f"set_counters 的 {k!r} 必须是非负整数，收到 {v!r}")
        doc = {"schema_version": S.SCHEMA_VERSION,
               "counters": {k: int(v) for k, v in values.items()}}
        with self._writer_lock(timeout=60.0):
            self._atomic_write(self.data / "counters.json", doc)
            # 进程内缓存也要跟着更新，否则同一进程里紧接着的 alloc_id 会从旧值起算。
            self._dirty_counters = doc
        _ = (actor, note)   # 预留：写者锁已经在锁文件里留下痕迹，这里只保留签名一致性
        return doc

    def _merge_counters_for_commit(self, t: "Tx") -> dict:
        """`R6-AN-1`：提交 counters 之前先读盘、再按"不丢"合并。

        调用点只有一个：`tx` 的提交块，而且必须在写者锁内（读盘 → 合并 → 落盘
        这三步要与 `set_counters` 互斥，否则窗口只是变窄，没有关上）。

        ## 判据先行：这是缺陷，不是"刻意的 last-write-wins"

        四条理由（逐条可核）：

        1. 提交侧改的是它自己没碰过的内容：`counters.json` 是整份写回的，
           事务只对取过号的那几个类别有所有权，却把整份文件按旧缓存覆盖；
        2. 这与 `set_counters` 自己的 docstring 相反（那把写者锁声明的目标是
           "与并发 tx 的 alloc_id 不漂移"），而实测撤锁后读数完全相同 ⇒
           两处声明与实现互相矛盾；
        3. 与模块 docstring 第 2 条（"不存在丢失更新：任何读-改-写都在同一把
           排他锁内完成"）相反 —— 旧形态正是一次跨临界区的读-改-写；
        4. `tools/probe_gap_ledger.py` 用 `set_counters` 造 `c-7` 的读数 ⇒
           它造出的读数会被在飞事务吞掉，也就是"用来验证不漂移的工具本身不可复现"。
        刻意的 LWW 会是"逐键 + 有时间戳/版本 + 有痕迹"的，而这里三样都没有。

        ## 合并规则（两条，都是"不丢"而不是"谁赢"）

        1. 本事务取过号的类别：取 `max(盘上值, 缓存值)`。取号只会单调前进，
           所以 max 既保住本事务发出去的号的推进，也保住窗口里写下的更大值；
        2. 本事务没碰过的类别：用盘上的值。`set_counters` 是显式覆盖，
           一个没碰过该类别的在飞事务把它回退掉才是越权。盘上没有而缓存里有（例如
           `set_counters` 这次没写它）时不从缓存补回来 —— 缓存里那份是
           本事务读过的旧状态，补回来就是把它当成"我的写入"。

        ## `R7-AN-1`：窗口里的拨低也必须可判定（`R6-AN-1` 只覆盖了抬高方向）

        `max` 只会把计数器往前推，所以显式拨低在窗口里不会降低盘上值 ——
        这一点是刻意的（改成"缓存赢"会重开 `R6-AN-1` 的 raising 方向，实测过）。
        但反方向如果一条痕迹都不留，那次写入就是无声消失、判据上也看不见
        （`R7-AN-1` 实测：C 写 `concept=0`、盘上确认 0，B 提交后盘上是 4、痕迹 0 条）。
        所以痕迹改成双向：

        - 触发条件：取过号的类别里，盘上值 ≠ 本事务读到的基线（`Tx._alloc_base`）；
        - 方向：`direction` 逐类别给 `disk_higher`（盘上更高，被别的写者抬高了）
          或 `disk_lower`（盘上更低，被别的写者拨低了，本次提交用 max 抬回）；
        - 读数：`disk` / `cache` / `baseline` / `merged` 四个字典都按类别给，
          两个方向各自有完整读数；`disk_higher` / `disk_lower` 两个列表点名归属。

        为什么触发条件写"≠ 基线"而不是字面上的"盘上 ≠ 缓存"：本事务自己的那次推进
        就是 `盘上(读时的值) → 缓存(推进后的值)`，拿缓存当基准会让每一次普通取号
        都满足"盘上 ≠ 缓存"，于是每次 alloc 提交都写一条痕迹，而那条痕迹的方向会把
        本事务自己的推进说成"别的写者拨低了盘上值"（假归因）。
        基线与缓存的差（`cache - baseline`）是本事务自己的账，不算别人的写入；
        把 `baseline` 一并写进事件，读的人可以自己把这个差算出来。
        `tests/test_store_counters_commit.py::test_quiet_commit_advances_the_counter_without_a_trace`
        钉住这条：常态下盘上值是 3、缓存是 4（确实不等），但一条痕迹都不许写。

        它在 `_append_events` 之前追加，所以和这一批事务事件一起落进 `events.jsonl`
        （`rebuild` 只重放 upsert，不会被它影响）。

        ## 边界（如实写下来，免得被读成无条件）

        `rebuild` 的 counters 仍然只由事件里那些 alloc 推出（`set_counters`
        不写事件）⇒ 重建后计数器会回到"日志里发过的号 + 1"。这是 `rebuild`
        的既有边界（"重建的唯一输入是事件日志"），不是本次合并引入的。
        """
        disk = self._load("counters")
        cache = self._dirty_counters or disk
        disk_c = {k: int(v) for k, v in (disk.get("counters") or {}).items()}
        cache_c = {k: int(v) for k, v in (cache.get("counters") or {}).items()}
        out = dict(disk_c)
        changed: dict[str, dict[str, Any]] = {}
        for kind in sorted(t._alloc_kinds):
            d = disk_c.get(kind, 0)
            c = cache_c.get(kind, 0)
            out[kind] = max(d, c)
            base = t._alloc_base.get(kind)
            if base is None or d == base:
                # `base is None` 只可能出现在"没有经过 alloc_id 就进了 _alloc_kinds"时
                # （今天不可能）：没有基线就没有"窗口里有人写过"的证据，不写痕迹。
                continue
            changed[kind] = {
                "disk": d,
                "cache": c,
                "baseline": int(base),
                "merged": out[kind],
                "direction": "disk_higher" if d > base else "disk_lower",
            }
        if changed:
            higher = sorted(k for k, v in changed.items() if v["direction"] == "disk_higher")
            lower = sorted(k for k, v in changed.items() if v["direction"] == "disk_lower")
            t.info(
                "counters_commit_merged",
                differing=sorted(changed),
                direction={k: v["direction"] for k, v in changed.items()},
                # 兼容旧键名：它一直只表示"盘上的值更大、被并进来了"那一半。
                merged_from_disk=higher,
                disk_higher=higher,
                disk_lower=lower,
                disk={k: v["disk"] for k, v in changed.items()},
                cache={k: v["cache"] for k, v in changed.items()},
                baseline={k: v["baseline"] for k, v in changed.items()},
                merged={k: v["merged"] for k, v in changed.items()},
                note=("提交时盘上的计数器与本事务读到的基线不同 ⇒ 这个窗口里有别的"
                      "写者（例如 set_counters）。终值仍取 max(盘上, 缓存)：盘上更高"
                      "时保住它；盘上更低（显式拨低被 max 抬回）时不会让计数器倒退"
                      "（那会重开撞号方向）。两个方向都记在这里，于是被吞掉的那次"
                      "写入至少是可判定的（R6-AN-1 / R7-AN-1）。"),
            )
        merged = dict(disk)
        merged["schema_version"] = S.SCHEMA_VERSION
        merged["counters"] = out
        return merged

    def _atomic_write(self, path: Path, doc: dict) -> None:
        """写临时文件 → fsync → os.replace。同目录替换在 Windows 上也是原子的。

        ## `F-3`：临时名必须唯一，替换必须重试

        旧版临时名是固定的 `path.with_suffix(path.suffix + '.tmp')`，`os.replace`
        不重试。实测（`temp/auditF-probe2.txt` 的 [F] 段，两个真进程并发各写同一个
        `literature.json` 12 次）：两进程都拿到退出码 0、各自以为写进了 24 行，
        而磁盘上只剩 8 行；`_atomic_write` 抛出 10 次 `OSError`，逐字包括

            PermissionError [WinError 32] 另一个程序正在使用此文件:
            '...literature.json.tmp' -> '...literature.json'

        也就是说：模块 docstring 那句无条件的"不存在部分写入 —— 一律写临时文件→
        os.replace"在并发写者下不成立（Windows 上 `os.replace` 会因为目标或
        源被另一个进程打开而抛）。

        现在的修法两条，都是"把冲突面缩到最小"而不是"假装没有冲突"：

        1. 临时名带 `pid` 与线程 id ⇒ 两个写者不再抢同一个临时文件
           （抢文件是 `WinError 32` 的直接来源）；
        2. `os.replace` 包一个短重试（指数退避，`R3-10` 之后总等待 ≈0.62 秒：
           5 次退避，最后一次失败后不再 sleep）⇒ 目标文件被
           另一个进程短暂持有（防病毒、索引器、另一个 replace 的瞬间）时不再硬崩；
        3. 重试耗尽才抛，且抛的是 :class:`StoreError`（**带路径与最后一次的
           OS 错误**），不再是裸 `OSError` —— 调用方拿到的是一个本框架的错误类型，
           而 `tx()` 也会把它翻译成"这笔事务没做成"。

        ⚠️ 它不保证"并发写同一个表不丢更新"：那件事只有一把锁能保证，见
        `_writer_lock` 与 `tx` 的提交块。这里只保证单次落盘是原子的、且不会
        因为临时名相撞而硬崩。
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
        payload = self._dump(doc)
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            last: OSError | None = None
            for attempt in range(_REPLACE_ATTEMPTS):
                try:
                    os.replace(tmp, path)
                    return
                except OSError as exc:  # WinError 32 / Errno 13 都在这一支
                    last = exc
                    if attempt + 1 < _REPLACE_ATTEMPTS:
                        # `R3-10`：最后一次失败之后不 sleep（下面紧接着就抛）。
                        # 旧版无条件 sleep，于是注释里的 0.62 秒在实测里是 1.27 秒，
                        # 而这段在写者锁内 —— 那 0.64 秒是纯粹的持锁等待。
                        time.sleep(_REPLACE_BACKOFF_S * (2 ** attempt))
            raise StoreError(
                f"原子替换失败（重试 {_REPLACE_ATTEMPTS} 次后仍失败）：{tmp} -> {path}；"
                f"最后一次错误：{type(last).__name__}: {last}"
            ) from None
        finally:
            # 失败路径上把临时文件清掉：留着它只会让下一次诊断多一个可疑文件
            # （旧版正是这样攒下一堆 `<表>.json.tmp` —— 实测 [F] 段里能看到它们）。
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    # 清不掉（例如另一个进程正拿着它）不该掩盖真正的失败原因：
                    # 这个 `finally` 里抛出去会把"为什么这笔写失败"换成一个
                    # "临时文件删不掉"。留一个 `<表>.json.<pid>-<tid>.tmp` 的危害
                    # 远小于那个（而且它带 pid，一眼能看出是谁留下的）。
                    pass

    @staticmethod
    def _check_version(doc: dict, where: str) -> None:
        """`F-7`（**人裁 = fail-closed**，观测时刻 2026-09-26 19:5x）：读期拒绝版本不符。

        背景（`draft/28` 的 `F-7`，实测 `temp/auditF-probe2.txt` / `temp/f7-before.txt`）：
        版本判据此前只有 `validate_table` 一处，而它只在**提交时**被调用 ——
        那时校验的是本进程刚合成、`schema_version` 必为当前值的 doc。
        `_load` / `read` / `rows` / `rebuild` **从不校验版本**，
        于是把一个旧版本号的 JSON 放进 `data/` 就能被照读不误：
        「旧字段被按新语义解释」这件事没有任何地方会响。

        现在的口径（所有者裁定）：**读期拒绝**。不符就抛 `StoreError`，
        消息里给出**两个版本号**与这一条的处置（先 `rebuild` 或做迁移）。

        - 缺 `schema_version` 字段 = 与"旧版本"同档（拒读），但不许崩成 `KeyError`；
        - 版本相同才放行（**不是** `>=`，也不是"读不出来就放过"）。
        """
        got = doc.get("schema_version")
        if got == S.SCHEMA_VERSION:
            return
        raise StoreError(
            f"{where} 的 schema_version 与当前不符：盘上是 {got!r}，本进程期望 "
            f"{S.SCHEMA_VERSION!r} ⇒ **拒读**（`F-7` 的口径：读期 fail-closed，"
            "不许按当前语义解释旧数据）。处置：确认要以哪一版为准 ⇒ 必要时跑 "
            "`agentflow rebuild`（从 events.jsonl 重建）或做一次显式迁移；"
            "任何情况下都不许把这一条读成'没有版本问题'。"
        )

    def _load(self, table: str) -> dict:
        if table == "counters":
            p = self.data / "counters.json"
            if not p.exists():
                return {"schema_version": S.SCHEMA_VERSION, "counters": {}}
            doc = json.loads(p.read_text(encoding="utf-8"))
            self._check_version(doc, "counters.json")
            return doc
        spec = S.TABLES.get(table)
        if spec is None:
            raise StoreError(f"未知表：{table}")
        p = self.data / spec["file"]
        if not p.exists():
            return S.empty_table()
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise StoreError(
                f"{spec['file']} 不是合法 JSON（{e}）。可用 `agentflow rebuild` 从 events.jsonl 重建。"
            ) from e
        self._check_version(doc, spec["file"])
        return doc

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

            # ---- 提交：先全部校验，再在写者锁内落盘与追加事件。任一失败 => 什么都不写。
            #
            # `F-1`：这一段曾经是"先落盘全部快照、再追加事件"，两者之间崩一次就留下
            # "快照里有、事件里没有"的行，而 `rebuild()` 会不报错地丢掉最后一次
            # 提交（实测：快照 2 行 / counters=2，rebuild 后 1 行 / counters=1）。
            # 现在的顺序与形状：
            #
            #   ① 校验（全在内存里，失败 ⇒ 一行都不写）；
            #   ② 追加事件 + 提交标记（先落事件：崩在这里 ⇒ 快照还是旧的，
            #      而那一批事件没有提交标记 ⇒ 重建时不会重放它）；
            #   ③ 逐张落盘快照（崩在这里 ⇒ 事件有、快照可能只写了一半 ——
            #      但重建会把那一批完整地重放一遍，于是结果是一致的）。
            #
            # 为什么"先落事件"是安全的方向：`rebuild()` 按主键 last-write-wins 折叠
            # 整行 upsert，重放一批完整的事件得到的就是提交时的那个状态；
            # 反过来（先快照后事件）丢掉的是事件，而重建的唯一输入就是事件 ⇒
            # 那一次提交在重建后消失，且没有任何东西会报告这件事。
            to_write: list[tuple[Path, dict]] = []
            counters_pending = False
            for table in sorted(t._dirty, key=LOCK_ORDER.index):
                if table == "counters":
                    # `R6-AN-1`：counters 的内容不能在锁外定。
                    # `Tx.alloc_id` 只在第一次取号时读一次 `counters.json`，而事务体
                    # 全程不持写者锁（写者锁只在下面这一段里拿）；`set_counters`
                    # 拿的是同一把写者锁，所以它能在这个窗口里落盘，随后被这里
                    # 用那份旧缓存整份覆盖 —— 实测：C 写 999 且盘上确认 999，
                    # B 提交后盘上是 4，无日志无异常。现在改成：拿到写者锁之后再
                    # 读盘、再按"不丢"合并（`_merge_counters_for_commit`）。
                    # 落盘顺序里 counters 因此排在最后：事件先于快照这条顺序不变，
                    # 而若干张快照之间的先后没有语义（重建的唯一输入是事件）。
                    counters_pending = True
                    continue
                spec = S.TABLES[table]
                doc = {"schema_version": S.SCHEMA_VERSION, "rows": t.rows(table)}
                S.validate_table(table, doc)
                to_write.append((self.data / spec["file"], doc))

            wlock = self._writer_lock(timeout=timeout)
            try:
                wlock.acquire()
            except Timeout as e:
                raise StoreError(
                    f"获取写者锁超时（{timeout}s，提交阶段）。可能有另一个进程正在"
                    "rebuild/init 这个工作区；若进程已死，锁文件是可安全删除的。"
                ) from e
            try:
                # `R6-AN-1`：counters 的最终内容在写者锁内定 —— 读盘、合并、
                # 必要时往这一批事件里追加一条痕迹，都必须在 `_append_events`
                # 之前完成（事件只追加一次，追加之后改 `t._events` 不会进日志）。
                if counters_pending:
                    to_write.append(
                        (self.data / "counters.json", self._merge_counters_for_commit(t))
                    )
                if t._events:
                    self._append_events(t._events)
                for path, doc in to_write:
                    # `G4-R2`（第 50 轮，判据四第 4 组带出来的新洞）：**把写盘的 `OSError` 翻成
                    # `StoreError`**。旧版让 `_atomic_write` 的裸 `OSError`（磁盘满 errno 28 /
                    # 权限 errno 13 / WinError 32）直接穿透 `tx()` —— 而本模块的落盘层
                    # （`init` / `_atomic_write` 的重试耗尽那一支）都抛 `StoreError`。
                    # 调用方按"`StoreError` 就是 store 报的失败"写恢复路径，会**漏掉最该恢复的那一类**
                    # （磁盘满 / 只读盘），拿到的是一次裸 `OSError`。
                    # 实测（`temp/g4-nospace.txt`，用 monkeypatch 模拟 ENOSPC，不改盘）：
                    # 原快照字节未变、无残留 `.tmp`、事务不生效 —— **数据是安全的**，
                    # 唯独异常类型不对。把原始 errno 与路径带进消息，别丢诊断信息。
                    try:
                        self._atomic_write(path, doc)
                    except OSError as exc:
                        raise StoreError(
                            f"落盘失败（{type(exc).__name__}，errno="
                            f"{getattr(exc, 'errno', None)}）：{exc}。"
                            f"目标文件 {Path(path).name}。"
                            "事务**没有**生效（原快照未被改动、临时文件已清理）；"
                            "常见原因是磁盘满 / 只读盘 / 文件被别的进程占用 —— "
                            "处置是腾出空间或改权限后重试，而不是重跑整个流程。"
                        ) from exc
            finally:
                try:
                    wlock.release()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            # ⚠️ 无论成功还是失败都必须清空事务内的计数器缓存。
            # 只在提交成功时清，会让失败事务把改过的计数留在内存里：下一次
            # alloc_id 会基于一个磁盘上并不存在的值发号，轻则产生 ID 空洞，
            # 重则与另一个进程发出的号真撞号，而按主键 upsert 会静默覆盖。
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
        """把一个事务的事件整批追加，并在末尾写一条提交标记（`F-1`）。

        一批事件 = 一个 `batch` 号（时间戳 + pid + 序号，进程内单调）。
        `rebuild()` 只重放带提交标记的批次：标记就是"这一批的每一行都已经
        完整落到这个文件里了"的证据。没有标记的批次一律不重放 —— 那是崩在
        追加中途留下的半批（`read_events` 早就会把半个 JSON 行读成 `corrupt`），
        重放它会让重建结果取决于崩在第几行。

        ⚠️ 兼容口径：仓库里已有的历史事件没有 `batch` 字段。它们被当作
        "完整批次"处理（见 `rebuild` 的注释）—— 历史日志是旧版一行一 fsync 写出来的，
        没有"半批"这个概念；把老事件一律当不完整会丢掉整个历史，那比它要防的风险
        大得多。`rebuild` 会把这条口径连同"重放了多少批、跳过多少批"一起返回。

        ⚠️ 调用点约束（`c-6`）：序号由 `_next_seq` 从**日志尾巴**取，而"读尾巴 +
        追加"必须是一个原子段 ⇒ 本方法**只能在写者锁内调用**。`tx` 的提交块
        与 `init` / `rebuild` 都满足这一点（它们拿的是同一把 `_writer_lock`），
        于是两个进程不可能同时读到同一个尾巴。反过来，在锁外直接调用它
        （探针脚本曾经这么干过，见 `c-7`）会让两边的序号互相重叠。
        """
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        batch = f"{_now()}-{os.getpid()}-{next(self._batch_seq)}"
        with open(self.events_path, "a", encoding="utf-8", newline="\n") as f:
            for e in events:
                e = {"seq": self._next_seq(), "ts": _now(), "batch": batch, **e}
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            f.write(json.dumps(
                {"seq": self._next_seq(), "ts": _now(), "op": "commit",
                 "batch": batch, "rows": len(events)},
                ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _next_seq(self) -> int:
        """取下一个事件序号 —— 来源是**日志里已有的最大 seq**，不是"数行数"（`c-6`）。

        ## `c-6`：序号必须由"日志的尾巴"决定，且首次加载要落在写者锁内

        `draft/28` 的 `c-6`（实测形态）说两件事，两个都在这里处置：

        1. 旧版把 `len(events.jsonl 的行数)` 当序号来源（每进程只读一次）。
           行数与 `seq` 字段**不是一回事**：`read_events` 会把任何解析不了的行
           替换成 `{"seq": i, "op": "corrupt"}`，于是日志里出现过坏行之后，
           "第 n 行的 seq" 与 "第 n 行" 就分家了，接着发出的号会与日志里**已有的**
           `seq` 撞上。现在改成"日志里出现过的最大 `seq` + 1"（见 `_seq_high_water`）：
           坏行占位的 `seq=i` 也照算，序号只会往后走，不会回退到别人用过的值上。
        2. 旧版的惰性加载（第一次调用时数一遍行数）发生在**任意**位置；真正
           需要原子性的是"读日志尾巴 → 写入新行"这一段。这一段由
           `_append_events` 在 `store.tx` 的**写者锁**内调用（提交块先 `wlock.acquire()`
           再 `_append_events`），所以读尾巴与追加是同一个临界区里的两步。

        ⚠️ 由此带来一条对调用方的约束：**`_append_events` / `_next_seq` 只能在
        写者锁内调用**。`init` / `rebuild` 走 `_writer_lock`，`tx` 在提交块里拿同一把
        锁 ⇒ 三者互斥，没有"两个写者同时读尾巴"。这一条不是靠自觉：
        `tests/test_store_r3_commit_order.py` 钉住提交顺序，而这里每次调用都
        重新读一遍日志尾巴（不再缓存一个可能与盘上分家的行数），
        代价是每次追加多读一遍 `events.jsonl` —— 相对"重复 seq 的时间线"，
        这个代价是划算的。
        """
        self._seq = max(self._seq, self._seq_high_water()) + 1
        return self._seq

    def _seq_high_water(self) -> int:
        """日志里出现过的最大 `seq`（没有日志 / 全是空行时是 0）。

        为什么单独一个函数而不是内联在 `_next_seq` 里：`rebuild` 与 `verify`
        都可能面对"手改过 / 旧格式"的日志，任何非整数的 `seq` 只该被当作
        "这一行没有可用序号"（记 0），而不该让一次追加或一次重建崩在 `int()` 上。
        `read_events` 早就承诺"坏行不中断重建"，序号提取必须守同一条承诺。
        """
        high = 0
        for e in self.read_events():
            try:
                n = int(e.get("seq", 0) or 0)
            except (TypeError, ValueError):
                continue
            high = max(high, n)
        return high

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

        因为事件里存的是整行 upsert，折叠逻辑就是"按主键 last-write-wins"。

        ## `F-1`：只重放完整批次，并在写者锁内整个做完

        旧版逐条重放，于是"崩在快照与事件之间"的那一次提交会不报错地消失
        （实测：快照 2 行 / counters=2 ⇒ rebuild 后 1 行 / counters=1）。
        现在两条判据：

        - 完整批次才算数：一批事件后面必须跟一条 `op="commit"` 的标记
          （`_append_events` 写）；没有标记的那一批整批跳过，并把跳过数报出来
          （`batches_incomplete`）。历史事件没有 `batch` 字段 ⇒ 当作完整批次
          （理由见 `_append_events` 的兼容口径）。
        - 整个重建在一把写者锁内（`G-12`）：这把锁只保证**写者之间**互斥
          （两个重建/事务不会互相踩），它**不**排除并发读者在重建过程中读到中间态 ——
          读侧今天不拿这把锁（`R3-1` 的口径裁决：接受现状，只把措辞改成事实）。

        返回值新增三个计数，全是"读的人必须能看见"的东西：
        `batches_applied` / `batches_incomplete` / `events_replayed`。
        旧调用方只看 `applied` / `skipped` / `counters`，那三个键原样保留。
        另有四个后来补上的、同样是"必须能看见"的键：

        - `legacy_events_without_version`（`F-7`）：没有版本号的老事件条数；
        - `corrupt_events`（`I-5` / `R3-4`）：日志里坏掉的行的条数。
          旧版把这件事吞在 `read_events` 的 `corrupt` 占位里，返回值看不见
          ⇒ "没抛异常"被读成"日志是好的"；
        - `snapshot_rows_not_in_log` 与 `snapshot_ahead`（`R3-3`）：
          快照里有、日志里从来没有过的行数与逐表明细。

        ## `R3-3`：为什么必须比对快照与日志（而不只是看提交标记）

        上面那两条判据（`batches_incomplete` / `corrupt_events`）都只问"日志里
        有没有问题"。而重建的输入是日志、输出会整表覆盖快照 ⇒ 另一类偏离是
        "快照超前于日志"：正常提交后手工往 `<表>.json` 加一行（日志无痕），
        旧版返回 `applied=1 / batches_incomplete=0`，那一行被静默丢掉而计数为 0。
        于是"`batches_incomplete == 0`"被读成"库里没有丢过提交"，而那是错的。

        现在返回 `snapshot_rows_not_in_log`（差集行数）与 `snapshot_ahead`
        （`{表名: [主键, …]}`）。它不会让重建失败（重建是灾难恢复手段，
        不能因为它要修的东西而拒绝工作），但那份"这次会丢多少已有数据"从此
        在报告里看得见。口径：只算"快照有、日志没有"这一个方向；
        反方向（日志有、快照没有，例如删行）是正常形态，不在这里报 ——
        删行不进事件日志是重建的已知边界，见 `F-9`。

        ## `F-9`（第 3 条）：这条"不丢信息"的承诺**有边界**，边界写在这里

        折叠时是"合并而非替换"：事件行里带了的非 schema 键（`_keys`、
        `_quote_check` 这类诊断字段）会被保留下来，这一半是成立的。
        但**重建的唯一输入是事件日志**：一个键若只存在于快照、从未进过任何事件
        （例如有人手工往 `<表>.json` 里加了一个诊断字段），重建后它**不在了**。
        这不是缺陷，而是"从日志重建"的定义 —— 但它必须被写下来，
        否则"rebuild 什么都不丢"会被读成无条件的事实，而 `F-7` 那类
        "只改快照"的偏离会因此显得无害。
        """
        try:
            with self._writer_lock(timeout=120.0):
                return self._rebuild_locked(backup=backup)
        except Timeout as e:
            raise StoreError(
                "获取写者锁超时（rebuild）。可能有另一个进程正在写这个工作区；"
                "若进程已死，锁文件是可安全删除的（filelock 用 OS 锁，不含内容）。"
            ) from e

    def _snapshot_keys(self) -> dict[str, set[str]]:
        """各表当前快照里的主键集合（`R3-3` 的输入）。

        为什么读不出来就跳过这张表、而不是抛：`rebuild` 的典型调用场景恰恰是
        "快照坏了"（半截 JSON、版本不符、手工改坏）。在这里抛等于让
        "重建"这个灾难恢复手段在最需要它的时候失败。跳过的那张表不会进
        `snapshot_rows_not_in_log` 的分母 —— 于是这个计数只会少报、不会误报，
        方向与 `R3-3` 的"宁可如实说看不见"一致。
        """
        out: dict[str, set[str]] = {}
        for table, spec in S.TABLES.items():
            p = self.data / spec["file"]
            if not p.exists():
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rows = doc.get("rows")
            if not isinstance(rows, list):
                continue
            idf = spec["id_field"]
            out[table] = {str(r.get(idf)) for r in rows
                          if isinstance(r, dict) and r.get(idf) is not None}
        return out

    def _rebuild_locked(self, *, backup: bool = True) -> dict:
        # `R3-3`（重审实测）：快照必须与日志比对，不能只看 `op=commit` 标记。
        #
        # 缺陷形态：正常提交之后手工往 `<表>.json` 多塞一行（日志无痕）⇒ 旧版
        # `rebuild` 返回 `{'applied': 1, 'batches_applied': 1, 'batches_incomplete': 0, …}`，
        # 那一行被静默丢掉而计数为 0 —— 也就是"快照超前于日志"（旧顺序
        # 先快照后事件留下的真实缺陷形态）在改后既不报错也不报数。
        # 于是"`batches_incomplete == 0`"被读成"库里没有丢过提交"，而那是错的。
        #
        # 快照必须在被覆盖之前读：下面这一段会把每张表整个重写。
        snapshot_before = self._snapshot_keys()
        if backup:
            bdir = self.data / f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            bdir.mkdir(parents=True, exist_ok=True)
            for spec in S.TABLES.values():
                src = self.data / spec["file"]
                if src.exists():
                    shutil.copy2(src, bdir / spec["file"])
            if (self.data / "counters.json").exists():
                shutil.copy2(self.data / "counters.json", bdir / "counters.json")

        events = self.read_events()
        # `F-7`（人裁 = fail-closed）落在**事件流**上的口径，与读快照**故意不同**，
        # 理由必须写清（否则这条判据会变成"把历史数据一律拒掉"）：
        #   - 事件里**写了**版本号且与当前不符 ⇒ **拒**（拿旧语义重放会静默改写快照）；
        #   - 事件里**没有**版本号 ⇒ 视作"加版本号之前写下的历史事件"，**照常重放**，
        #     并把条数报进返回值（`legacy_events_without_version`）——
        #     这是 `_append_events` 对 `batch` 字段的同一条兼容口径，
        #     也是全部既有夹具（以及真实历史库）的形态；把它也拒掉等于
        #     让 `rebuild` 对历史库完全不可用，而 `rebuild` 正是灾难恢复的唯一手段。
        bad_versions = sorted({repr(e.get("schema_version")) for e in events
                               if "schema_version" in e
                               and e.get("schema_version") != S.SCHEMA_VERSION
                               and e.get("op") != "corrupt"})
        if bad_versions:
            raise StoreError(
                "events.jsonl 的 schema_version 与当前不符（盘上出现 "
                f"{bad_versions}，期望 {S.SCHEMA_VERSION!r}）⇒ **拒绝重建**（`F-7`）："
                "拿旧语义的事件重放会静默改写快照。处置：确认以哪一版为准 ⇒ "
                "必要时先做一次显式迁移，再 rebuild。"
            )
        legacy_no_version = sum(1 for e in events
                                if "schema_version" not in e and e.get("op") != "corrupt")
        # `I-5`（登记在 `draft/28`）：坏行**必须被计数**，不能只是"没抛异常"。
        # 旧返回值里有 `skipped`，但它的语义是"没进 state 的行"，而坏行根本
        # 进不了 `replay` ⇒ 一条恒真的断言（`skipped >= 0`）就能蒙混过关，
        # 而"日志里有几行坏了"这个事实在报告里**看不见**。
        corrupt_events = sum(1 for e in events if e.get("op") == "corrupt")
        # ---- 先算出"哪些批次是完整的"
        committed: set[str] = set()
        for e in events:
            if e.get("op") == "commit" and e.get("batch"):
                committed.add(str(e["batch"]))
        replay: list[dict] = []
        batches_seen: set[str] = set()
        batches_incomplete: set[str] = set()
        for e in events:
            b = e.get("batch")
            if b is None:
                replay.append(e)  # 历史事件：没有批次概念 ⇒ 一律算完整
                continue
            b = str(b)
            batches_seen.add(b)
            if b in committed:
                replay.append(e)
            else:
                batches_incomplete.add(b)

        state: dict[str, dict[str, dict]] = {t: {} for t in S.TABLES}
        order: dict[str, list[str]] = {t: [] for t in S.TABLES}
        counters: dict[str, int] = {}
        applied = skipped = 0

        # `R3-3`：这次重放真的写下了哪些主键（逐表）。用它去减快照里已有的键，
        # 差集就是"快照里有、日志里没有"的行 —— 那是这次重建会静默丢掉的数据。
        logged_keys: dict[str, set[str]] = {}
        for e in replay:
            if e.get("op") != "upsert":
                continue
            table = e.get("table")
            if table not in S.TABLES:
                continue
            row = e.get("row") or {}
            idf = S.TABLES[table]["id_field"]
            key = row.get(idf)
            if key is not None:
                logged_keys.setdefault(table, set()).add(str(key))
        snapshot_ahead: dict[str, list[str]] = {
            t: sorted(keys - logged_keys.get(t, set()))
            for t, keys in snapshot_before.items()
            if keys - logged_keys.get(t, set())
        }
        snapshot_rows_not_in_log = sum(len(v) for v in snapshot_ahead.values())

        for e in replay:
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
            # 合并而非替换：schema 字段用校验后的规范值，其它键（`_keys`、
            # `_quote_check` 这类诊断/扩展字段）原样保留。
            # 早先这里只存 obj，导致 rebuild 后诊断字段全部丢失 —— 虽然判重靠
            # `doi`/`dedup_key` 兜底仍然可用，但"能重建"就不该"重建出更少的信息"。
            #
            # `F-9`（第 3 条）把这条承诺的**边界**写清，因为它原先写成了无条件的
            # "诊断字段不丢"：保留的是**事件行里带了的**非 schema 键。
            # 一个键若只存在于快照、而从未进过任何事件（例如有人手工往
            # `<表>.json` 里加了一个诊断字段），重建后它**不在了** ——
            # 重建的唯一输入是事件日志，快照里没进过日志的东西无从恢复。
            # 这不是缺陷而是"重建"的定义，但读 docstring 的人有资格知道它。
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
        return {
            "applied": applied,
            "skipped": skipped,
            "counters": counters,
            # 下面三个是 `F-1` 新增的"读的人必须能看见"的计数：
            # 一个不完整的批次意味着丢掉了一次提交，那件事绝不能只体现在行数上。
            "batches_applied": len(batches_seen - batches_incomplete),
            "batches_incomplete": len(batches_incomplete),
            "events_replayed": len(replay),
            # `F-7`：这一批事件里有多少条**没有版本号**（加版本号之前写下的）。
            # 它们照常重放，但读报告的人必须知道"这次重放里有 N 条是老格式"。
            "legacy_events_without_version": legacy_no_version,
            # `I-5`：`events.jsonl` 里有几行**坏了**（半行 JSON / 不是 JSON）。
            # 旧版把这件事吞在 `read_events` 的 `corrupt` 占位里，
            # 返回值里看不见 ⇒ "没抛异常"被误读成"日志是好的"。
            "corrupt_events": corrupt_events,
            # `R3-3`：快照里有、而日志里从来没有过的行数（逐表明细在下一个键里）。
            # 为什么会发生：旧顺序（先快照后事件）崩在两者之间、或有人手工往
            # `<表>.json` 里加行。这些行本次重建不会出现在结果里（重建的唯一
            # 输入是日志），而旧版对这件事一个字都不说 —— 于是
            # "`batches_incomplete == 0`"被读成"库里没丢过提交"。
            # 方向：它只多不少地报"这次会丢多少已有数据"，读报告的人据此判断
            # 该不该先修日志再重建。
            "snapshot_rows_not_in_log": snapshot_rows_not_in_log,
            # 逐表明细（只有差集非空的表才在里面）：人排查时需要知道是哪张表，
            # 而不只是一个总数。
            "snapshot_ahead": {t: v for t, v in sorted(snapshot_ahead.items())},
        }

    # ---------------------------------------------------------------- 路径工具
    def library_path(self, rel: str | None) -> Path | None:
        """把表里的相对路径解析为绝对路径，并强制它仍在 library/ 内。

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

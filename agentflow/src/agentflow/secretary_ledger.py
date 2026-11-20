# -*- coding: utf-8 -*-
"""秘书的台账底座：落点、追加口、发号、名册写临界区（从 secretary.py 的 U01+U02+U03 逐字搬出）。

我保证哪条不变式：同一份台账里 `seq` 只发一次；一次追加要么整行落盘、要么一个字节不落；
名册的 per-owner 临界区串行化"读三份 -> 判 -> 写两笔"，且锁序只许 `tasks -> roster`。

## 为什么这三块必须在同一个文件里（不许再拆）

`_APPEND_LOCKS` 与 `_ROSTER_LOCKS` 是同一件事的两层：进程内 `threading.Lock` + 跨进程
`filelock`，两者的键同形（`str(path)` / `root.resolve()+owner`）。代码里已经写明为什么不
复用同一把锁（追加锁罩不住"读三份 -> 判 -> 写两笔"）。分开成两个文件之后，"这两把锁不会
互相嵌套"这句话要靠两个文件的读者自己拼 —— 拼错的形态是死锁或竞态，而所有判据是绿的。
`_ROSTER_PENDING` 与第二层同键同址（在飞集合），也必须在这里。

## 对外名字

`append_jsonl` / `append_jsonl_stamped` / `decisions_path` / `_roster_section` /
`_roster_guarded` / `note_roster_pending` / `forget_roster_pending` / `roster_pending`，
以及各台账的路径函数。它们都还在 secretary.py 里再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Mapping
from pathlib import Path
import functools
import json
import threading
from . import schema as S

#: 台账落点：`<工作区>/out/secretary/<role>.jsonl`（追加式、脚本发号，`draft/53` §11.2）。
SECRETARY_DIR = ("out", "secretary")


#: 命题同一性判定的旁支台账（append-only）：一行一次判定，键是命题正文的 sha256。
#:
#: 为什么按正文 sha 缓存而不是按本次登记：同一段正文被交上来第二遍（改个标签、换个人重交、
#: 重试）时，判定不会有别的结论 —— 而每一次都要真发一次模型调用。没有这一层，
#: "同一条定理交了三遍"就是三笔钱买同一句话。
PROPOSITION_VERDICT_LEDGER = "proposition_verdicts.jsonl"


def decisions_path(root: str | Path, role: str, task_id: str = "") -> Path:
    """这一名秘书的决定台账路径。

    - `task_id` 空 ⇒ 老文件 `out/secretary/<role>.jsonl`（每角色一份，绝不混写）：
      历史行仍然在这里，读侧必须继续读得到；
    - `task_id` 给了 ⇒ 分片 `out/secretary/<role>-<task_id>.jsonl`：一实例一片、一个写者一片，于是
      同角色的并发实例（`summon_many` 的多 `instance`）不再往同一个文件里挤。
    注意：名字刻意不叫 `ledger_path` —— 那个名字在 `artifacts.py`（产物归属台账）与 `signatures.py`（签名
    台账）里各有一份独立实现，而秘书的决定台账与它们不是同一件事 —— 合并它们会把三件不同的事折成一个
    （lint R003 的口径是"同一判据的两份实现必须合并"，这里恰恰不是同一判据，所以正确的做法是改名字而不是合并）。
    """
    name = f"{role}-{task_id}.jsonl" if str(task_id or "") else f"{role}.jsonl"
    return Path(root).joinpath(*SECRETARY_DIR, name)


#: 同一进程里按路径复用的追加锁（与 `sessions.append` 同一做法）。
_APPEND_LOCKS: dict[str, Any] = {}

_APPEND_LOCKS_GUARD = threading.Lock()


def _append_lock(path: Path) -> Any:
    """同一路径的进程内锁（`filelock` 在同进程里不是线程安全的，两层都要）。"""
    key = str(path)
    with _APPEND_LOCKS_GUARD:
        lock = _APPEND_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _APPEND_LOCKS[key] = lock
        return lock


#: 名册写的 per-owner 临界区（业主 2026-11-02 口径②）：进程内一把 `threading.Lock` +
#: 跨进程一把 `FileLock`，按 `(root.resolve(), owner)` 分片。
#:
#: 为什么不复用 `_APPEND_LOCKS`：那把锁按文件名罩"一次追加（取号 + 写一行）"，
#: 罩不住"读三份文件 → 判（名字 / 槽位 / 重号）→ 写两笔"这一整段（`draft/149` §3.2）。
#: 为什么落在 `Secretary` 而不是 `Conductor`：`open_solo_entry`（用户指定单条执行）
#: 不经过 conductor（`agent_loop.py` 直接调秘书），加在 conductor 上会漏掉它。
_ROSTER_LOCKS: dict[str, Any] = {}

_ROSTER_LOCKS_GUARD = threading.Lock()

#: 同线程重入计数（roster_add → surface_alloc 会再要一次同一把锁）。
_ROSTER_DEPTH = threading.local()


@contextmanager
def _roster_section(root: str | Path, owner: str) -> Any:
    """同 `(root, owner)` 的名册写临界区（同线程可重入；跨进程用 `<owner>.jsonl.section.lock`）。

    锁序（必须写死，否则会死锁）：进这里之前先把 `tasks` 那一侧的事做完。`retire` 就是
    这样排的（`settle` 在写名册三笔之前），所以临界区里不再取任何 store 锁 ——
    只可能是 `tasks → roster`，不可能是反向。

    重入为什么必须有：`roster_add` 在临界区里调 `surface_alloc`（名字与槽位必须同一段），
    而 `surface_alloc` 自己也要这把锁；`filelock` 不可重入（`draft/149` A2 实测嵌套会
    超时），所以内层按线程计数直接放行。
    """
    from filelock import FileLock

    key = f"{Path(root).resolve()}::{str(owner or '')}"
    held = getattr(_ROSTER_DEPTH, "held", None)
    if held is None:
        held = {}
        _ROSTER_DEPTH.held = held
    if held.get(key):
        held[key] = int(held[key]) + 1
        try:
            yield
        finally:
            held[key] = int(held[key]) - 1
        return
    with _ROSTER_LOCKS_GUARD:
        lock = _ROSTER_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _ROSTER_LOCKS[key] = lock
    target = roster_path(root, owner)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:  # 目录建不出来时下面 FileLock 会自己报错，不在这里折成"没锁"
        pass
    with lock:
        with FileLock(str(target) + ".section.lock", timeout=30.0):
            held[key] = 1
            try:
                yield
            finally:
                held[key] = 0


def _roster_guarded(func: Any) -> Any:
    """把一次写方法的整段包进 per-owner 临界区（`owner` 从关键字参数取）。

    只给"判据 + 写盘"全在本方法里的那几支用（`roster_add` / `roster_repair` /
    `surface_alloc` / `surface_release`）。`retire` 刻意不用它：它中间有 `store.tx("tasks")`，
    整段包进来会把锁序变成 `roster → tasks`（`draft/149` §3.6 要求反过来）。
    """

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        owner = str(kwargs.get("owner") or "")
        with _roster_section(self.root, owner):
            return func(self, *args, **kwargs)

    return wrapper


#: 名册登记的「在飞」集合（`draft/159` §三-甲）：按 `(root.resolve(), owner)` 分片，
#: 与 `_ROSTER_LOCKS` 同键同址 —— 两者罩的是同一件事（这个父的名册写）。
#:
#: 语义：一个 `task_id` 从「它那一行要在这一笔 `tasks` 事务里提交」到「它自己的
#: `roster_add` 已经落盘」之间，在这个集合里。`roster_repair` 的 `known` 并上它，
#: 于是「还没登记」不会被读成「没登记」（81 趟 6 条 `repaired=true` 的根因：
#: A 线程写完了台账行、还没登记，B 线程的补登记把 A 当孤儿补了）。
#:
#: 为什么是模块级而不是挂 `Conductor`：`_ROSTER_LOCKS` 是模块级，理由是
#: 「`open_solo_entry` 不经过 conductor」；这一份罩的是同一个面，分片键必须同一份，
#: 否则同一进程里两条 `Conductor` 各拿各的集合，窗口又回来了。
#:
#: 为什么读的时候不需要再加一层锁：写入顺序是 `set.add(tid)` 先于 `tasks` 事务提交，
#: 而 `roster_repair` 先读 `_tasks()`、后读本集合 —— GIL 下「看得见那一行」的读者
#: 之后一定看得见标记。这个读序是判据（`tests/test_sibling_registration_race_is_not_backfilled.py`
#: 的读序负控），不是注释。
_ROSTER_PENDING: dict[str, set[str]] = {}


def _roster_pending_key(root: str | Path, owner: str) -> str:
    """与 `_roster_section` 同一个分片键（`(root.resolve(), owner)`）。"""
    return f"{Path(root).resolve()}::{str(owner or '')}"


def note_roster_pending(root: str | Path, owner: str, task_id: str) -> None:
    """把「这一号的台账行即将提交、名册还没登记」标进在飞集合（幂等）。"""
    tid = str(task_id or "")
    if not tid:
        return
    key = _roster_pending_key(root, owner)
    with _ROSTER_LOCKS_GUARD:
        _ROSTER_PENDING.setdefault(key, set()).add(tid)


def forget_roster_pending(root: str | Path, owner: str, task_id: str) -> None:
    """清掉在飞标记（登记结束/建行失败都走这里；清不掉 = 该号被 repair 永久跳过）。"""
    tid = str(task_id or "")
    if not tid:
        return
    key = _roster_pending_key(root, owner)
    with _ROSTER_LOCKS_GUARD:
        got = _ROSTER_PENDING.get(key)
        if got is None:
            return
        got.discard(tid)
        if not got:
            _ROSTER_PENDING.pop(key, None)


def roster_pending(root: str | Path, owner: str) -> frozenset[str]:
    """这一父名下「正在登记、名册还没落盘」的号（只读；空集时顺手删键）。"""
    key = _roster_pending_key(root, owner)
    with _ROSTER_LOCKS_GUARD:
        return frozenset(_ROSTER_PENDING.get(key) or ())


def _append_locked(path: str | Path, rec: Mapping[str, Any], *,
                   stamp_field: str = "", stamp_prefix: str = ""
                   ) -> tuple[bool, str, dict[str, Any]]:
    """追加一行的真身：锁内取号（可选：顺手把 `stamp_field` 也发成号）。

    返回 `(写成了吗, 问题, 落盘那一行)`。三件事只在这一处做：进程内锁、跨进程锁、
    `seq = max+1`。`stamp_field` 非空时，那一格的值 = `stamp_prefix + 锁内 seq`
    —— 这是"编号由秘书发"的唯一落点（`draft/90` §1.2 的请示编号，
    见 :meth:`Secretary.note_decision` 的 `proposal`）：同一个 seq 既是行号也是号源，
    于是"这个编号指向哪一行"在结构上不可能漂。

    `seq` 的宽度从 `schema.format_id` 取（与 `store.alloc_id` / 手稿号 / 留言号同一个
    发号形态）：本文件此前自己按"四位 + 冒号补零"的写死宽度拼号，于是业主 2026-10-14 把宽度
    定成六位之后，请示编号是唯一还在发四位的那一处（判据
    `tests/test_id_width.py::test_no_four_digit_mint_remains_in_the_source` 咬的就是它）。
    宽度只有一处可改这件事，靠的就是每个发号点都走 `format_id`。

    为什么要发号而不是让调用方拼一个：拼号的两种写法（时间戳、载荷哈希）都在
    锁外取值 —— 并发下会重号，而重号的请示意味着"接受 A 的编号却执行了 B 的洗"。
    """
    from filelock import FileLock

    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}", {}
    # 2026-10-17（真机 T2r/T5e 两趟同一个崩溃）：这里原本 `json.dumps(dict(rec))` 没有
    # `default=`、且在 try 之外 ⇒ 交接行里一旦带 `TopicalityReport` 这类冻结 dataclass，
    # 就直接冒泡成「A 执行中异常 TypeError: … is not JSON serializable」。
    # 序列化边界上把未知对象折成字符串（读数照旧、语义不变），绝不让"写一行台账"炸掉整步执行。
    try:
        line = json.dumps(dict(rec), ensure_ascii=False, sort_keys=True, default=str) + "\n"
    except Exception as exc:  # noqa: BLE001 —— 与本函数契约一致：写不成要如实报
        return False, f"{type(exc).__name__}: {exc}", {}
    with _append_lock(target):
        try:
            with FileLock(str(target) + ".lock", timeout=30.0):
                seq = 1
                if target.is_file():
                    text = target.read_text(encoding="utf-8", errors="replace")
                    for raw in text.splitlines():
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            row = json.loads(raw)
                        except Exception:  # noqa: BLE001 —— 坏行不参与取号
                            continue
                        if isinstance(row, dict):
                            seq = max(seq, int(row.get("seq") or 0) + 1)
                out = dict(rec)
                out["seq"] = seq
                if stamp_field:
                    out[str(stamp_field)] = f"{stamp_prefix}{S.format_id(seq)}"
                line = json.dumps(out, ensure_ascii=False, sort_keys=True, default=str) + "\n"
                with target.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(line)
        except Exception as exc:  # noqa: BLE001 —— 写不成要如实报（调用方留痕）
            return False, f"{type(exc).__name__}: {exc}", {}
    return True, "", out


def append_jsonl(path: str | Path, rec: Mapping[str, Any]) -> tuple[bool, str]:
    """唯一的秘书台账追加口（S1m）：进程内锁 + 跨进程 `filelock`，`seq` 在锁内算。

    返回 `(写成了吗, 问题)`。为什么必须集中到一处（`draft/91` §7 的 D107）：旧写法是
    "先读全表算 `seq = max+1`、再 `path.open("a")` 追加" —— 读与写之间没有锁，
    同角色的两个实例并发时会拿到同一个 `seq`（与 `_write_new_row` 修过的那个缺陷同族）。

    `seq` 的口径是每片自增（片就是"一个实例的账"），所以两片之间 `seq` 可以重复 ——
    合并视图（`Secretary.merged_decisions`）按 `at` 排序，不靠 `seq` 全局唯一。
    """
    ok, problem, _row = _append_locked(path, rec)
    return ok, problem


def append_jsonl_stamped(path: str | Path, rec: Mapping[str, Any], *,
                         field: str, prefix: str = "") -> tuple[bool, str, str]:
    """同一条追加口，另把 `field` 一格发成 `prefix + 锁内 seq`（编号由秘书发）。"""
    ok, problem, row = _append_locked(path, rec, stamp_field=field, stamp_prefix=prefix)
    return ok, problem, str(row.get(str(field)) or "")


ROSTER_DIR: tuple[str, ...] = ("out", "roster")


def roster_path(root: str | Path, owner: str) -> Path:
    """名册（`owner` = 父的绝对编码）。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}.jsonl")


def roster_index_path(root: str | Path, owner: str) -> Path:
    """对照表（电话簿）：本地名 → 当前调用行。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}-index.jsonl")


def retired_path(root: str | Path, owner: str) -> Path:
    """销号名单（名字一经退役永久不复用；后续版本的新功能读它）。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}-retired.jsonl")


def refusals_path(root: str | Path, owner: str) -> Path:
    """派活登记被拒的流水（被拒是一次有记录的决定）。

    为什么必须落一条盘上记录：拒绝当时名册三份一个字节都没写（`roster_add` 直接返回），
    跨进程唯一靠得住的证据就是这一刻落下的这条流水。收口兜底（`roster_repair`）读它，
    于是"派活时被拒的号"不会在销号那一刻被补成新名字 —— 而那等于悄悄改写那次拒绝。

    落点：`out/roster/refusals/<父>.jsonl`。放进子目录、而不是像 `-retired.jsonl` 那样
    同目录同后缀，是因为读侧按 `out/roster/*.jsonl` 的目录 glob 认"谁有一份名册"
    （`roster_owners` 与 `webui.readers._roster_files`），同目录新增一种后缀要在两处
    各登记一次；子目录两处都天然看不见（`out/surfaces/archive/` 是同一个做法）。
    """
    return Path(root).joinpath(*ROSTER_DIR, "refusals", f"{owner}.jsonl")


#: 名册目录里"不是名册正文"的那几种后缀（`<父>-index.jsonl` / `<父>-surfaces.jsonl` /
#: `<父>-retired.jsonl`）。全工作区口径的读数按它排除，而不是按"文件名里有没有横线"猜 ——
#: 父的编号本身不含横线，但靠猜迟早会把一种新后缀算成一份名册。
#: 2026-11-02 的拒绝流水（`refusals/<父>.jsonl`）不在这张表里：它在子目录里，两处
#: `*.jsonl` 的目录 glob（`roster_owners` / `webui.readers._roster_files`）都看不见它。
_ROSTER_SIDECAR_SUFFIXES: tuple[str, ...] = ("-index.jsonl", "-surfaces.jsonl",
                                             "-retired.jsonl")


SURFACES_DIR: tuple[str, ...] = ("out", "surfaces")


def surfaces_path(root: str | Path, owner: str) -> Path:
    """池事件流（`alloc` / `release` / `archive_failed`），append-only。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}-surfaces.jsonl")


def surface_dir(root: str | Path, owner: str, slot: str) -> Path:
    """一个槽位的面（目录）。"""
    return Path(root).joinpath(*SURFACES_DIR, owner, str(slot))


def archive_dir(root: str | Path, owner: str, name: str) -> Path:
    """归还前把面里的东西归档到这里（业主口径的反面：新子代理不该看到前任的文件）。"""
    return Path(root).joinpath(*SURFACES_DIR, "archive", f"{owner}-{name}")


#: 转发台账（append-only，一行 = 一次秘书转发或一次链尾交付）。
#:
#: 为什么不写进各自的 `decisions` 台账：链式转发是"一条消息走过几个秘书"这一件事，
#: 摊进 N 份按角色/实例分片的决定台账之后，读的人要 glob 整个目录再按时间拼起来
#: —— 而"每一位秘书都真的收到过一次转发"必须能一次读出来（业主的判据 a 就是它）。
#: 落点与决定台账同一个目录：`out/secretary/relay.jsonl`（`webui` 的目录 glob 认
#: `*.jsonl`，同目录会让它进"秘书台账"那一面 —— 转发记录本来就是秘书留痕）。
RELAY_LEDGER = "relay.jsonl"

#: 转发编号前缀（由 `append_jsonl_stamped` 在锁内发号；同一条消息的每一跳共用一个号，
#: 回执沿链回传时靠它把 N 跳认成同一次转发）。
RELAY_ID_PREFIX = "R-"


def relay_path(root: str | Path) -> Path:
    """转发台账的落点：`out/secretary/relay.jsonl`。"""
    return Path(root).joinpath(*SECRETARY_DIR, RELAY_LEDGER)


#: 非平凡性档位的旁支台账（不新增表、不改 schema）：一行 = 一次判断。
#: 为什么用旁支而不是 `statements` 的列：档位会随研究进展变（T4 造出梯子后要降到 T2/T3），
#: 它是时间序列不是记录属性；append-only 的旁支天然保留"降档发生过"的完整历史。
#: 一行靠 `stmt_id` 与命题行对上（2026-10-26，D16）：判档发生在登记之后，号已经在手上。
#: 旧行没有这一格、只有 `statement_sha256`；读侧只为读旧行留一条按 sha 的回退，
#: 新行一律按号（见 :func:`nontriviality_of`）。
NONTRIVIALITY_LEDGER = "nontriviality.jsonl"


def nontriviality_path(root: str | Path) -> Path:
    """档位旁支台账的路径：`out/secretary/nontriviality.jsonl`。"""
    return Path(root) / "out" / "secretary" / NONTRIVIALITY_LEDGER


def proposition_verdicts_path(root: str | Path) -> Path:
    """命题同一性判定台账的路径：`out/secretary/proposition_verdicts.jsonl`。"""
    return Path(root).joinpath(*SECRETARY_DIR, PROPOSITION_VERDICT_LEDGER)


#: 命题形态判定（"这条描述有没有明确「从什么条件导出什么结论」"）的旁支台账。
#:
#: 为什么要有这一本账：这一问的结论必须能被收工读数数出来
#: （「命题登记时需过 F 秘书闸」+ 读数要显形"被拒的条数 + 逐条码"）。而它不落
#: `statements` 行 —— F 自己不写 `statements`（登记是 B 的活），所以判定结果落在
#: 秘书自己的台账上，读侧一个口：:func:`proposition_form_of`。
PROPOSITION_FORM_LEDGER = "proposition_form.jsonl"

#: 同一命题检索的旁支台账（挑词 / 判定 / 检索各一行）。
#:
#: 为什么要有这一本账：验收口径是"B 秘书查过一圈没有"必须可审计
#: （关键词、命中数、查到哪一条、为什么没查成）。这些读数不落 `statements` 行
#: （那一行只记证据位），所以落在秘书自己的台账上，读侧一个口：
#: :func:`statement_same_rows`。
STATEMENT_SAME_LEDGER = "statement_same.jsonl"


#: 派活审阅（"这一条派给 F 的活是不是一个研究方向"）的旁支台账（业主 2026-11-13 裁定 Q5）。
#:
#: 为什么是一本轴台账而不是再往角色台账抄一行：这一问的结论要能被"这一趟派了几个 F、
#: 各自方向"那条读数复用，也要能在派活之后逐条复核"秘书当时为什么说不合适"。Q5 的裁定是
#: 只落这一本 —— 双写会让"同一件事两个落点"，读的人分不清哪一本算数。
DISPATCH_FIT_LEDGER = "dispatch_fit.jsonl"


def dispatch_fit_path(root: str | Path) -> Path:
    """派活审阅台账的路径：`out/secretary/dispatch_fit.jsonl`。"""
    return Path(root).joinpath(*SECRETARY_DIR, DISPATCH_FIT_LEDGER)


def proposition_form_path(root: str | Path) -> Path:
    """命题形态判定台账的路径：`out/secretary/proposition_form.jsonl`。"""
    return Path(root).joinpath(*SECRETARY_DIR, PROPOSITION_FORM_LEDGER)


def statement_same_path(root: str | Path) -> Path:
    """同一命题检索台账的路径：`out/secretary/statement_same.jsonl`。"""
    return Path(root).joinpath(*SECRETARY_DIR, STATEMENT_SAME_LEDGER)

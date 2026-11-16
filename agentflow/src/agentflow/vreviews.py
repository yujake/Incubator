# -*- coding: utf-8 -*-
"""V 稿：V 的秘书判出「有毛病」时，给被审者（F / E / B）的审阅报告。

业主 2026-11-16 的裁定（原文见 SG1 施工单）：

- ⑤ 有毛病 ⇒ 落 V 稿：审的是哪份稿（族 + 号 + sha）/ 有毛病 / findings 与理由
  （含 warning 与程序性 fault）；
- ⑥ 落盘 `verifications/reviews/v-review-NNNNNN.md` + `index.jsonl`；
  号源 = 索引 max 与盘上已用号两边取大 + 1，到上界受控抛错
  （不用 `store.alloc_id` / counters）；
  幂等键 = 台账锚点（台账路径, verification_id）—— 因为未在册 pending 行没有
  `review_call`；
- ⑦ 交付 = `conductor.open_item` 的 notice；`expects="ack"` 是信息型板项的那一档
  （`conductor.INFORMATIONAL_ITEM_KINDS`）：渲染进收件人某一步的提示词那一拍就
  `seen → done`（`close="acked"`），不要求模型再显式 ack —— 它不在
  `conductor.ACK_REQUIRED_ITEM_PREFIXES` 里。`expects=""` 只有撤销后的
  `done/expired` 行才合法（`schema.Task.validate`），live 的 notice 用它会被拒。

## 为什么号源读索引而不是 `store.alloc_id`

V 稿不是 `tasks` / `statements` 那种 store 表里的行：它住在 `verifications/reviews/`
这一层文件里，索引就是它的台账。拿 `store.alloc_id` 会造出一个与索引无关的号源，
两份号一旦漂开，"v-review-000007" 就可能对应两份不同的报告。索引是唯一真身，
号源也只能从它现读。

## 号源为什么要"两边取大"（索引 max 与盘上文件名）

索引是追加式的，而正文先落、索引行后追加（`record_review` 的顺序就是这样）。
两次写之间失败 —— 或者进程正好在那一拍被杀 —— 就会留下"盘上有
`v-review-000007.md`、索引里没有它"的一份稿子。这时若只按索引 max + 1 发号，
下一个号正好是 000007：新稿覆盖旧稿，而索引里会出现两条同号记录
（`_read_index` 照样读得进来，没有任何地方会报错）。所以号源把盘上的
`v-review-NNNNNN.md` 也算进去（`_on_disk_ids`），两边取大再 + 1；号到上界
（`MAX_ID`）时受控抛 `ReviewIdExhausted`，不折回 `000001`。

## 为什么是两层锁（进程内 + 跨进程）

`record_review` 会被两个进程同时调用（并行路各记一份、`agent_loop` 的补落、
真机上两个 V 实例）。进程内那把 `threading.Lock` 只在同一个解释器里有意义 ——
两个进程各自有一份 `_LOCKS`，跨进程等于没有锁，会各发一个号、各写一份索引
（同一个号两份正文）。所以照 `manuscripts.py` 的「取号在 `FileLock` 内」与
`secretary._append_locked` 的"两层都要"形态：进程内一把 + `<索引>.lock` 一把，
罩住"读索引 → 发号 → 落正文 → 追加索引"一整段。`filelock` 的对象在同进程里
不保证线程安全（`secretary._append_lock` 的注释），所以外层必须还有线程锁。

## 幂等键为什么是（台账路径, verification_id）

在册那一签的锚点是 `verifications/<命题号>.jsonl#v-…`；未在册那一签的锚点是
`verifications/pending/<正文 sha>.jsonl#u-…`（没有 `review_call`）。两条路的共同
可定位事实只有这两格，所以幂等键取它们。同一行判定被重复投递时只回旧那一份，
不追加第二个编号、也不覆盖盘上那一份。

## 三态

`record_review` 的 `checked` 是"这一格查成了没有"：索引读不出来 / 写盘失败 ⇒
`checked=False`，`written=False`，理由点名。`idempotent=True` 是"查成了、盘上已有
同一锚点的那一份"——它不是失败，也不是"又写了一份"。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping

from filelock import FileLock, Timeout

from .schema import format_id
from .store import MAX_ID as _STORE_MAX_ID

#: V 稿目录（工作区根相对；索引也在这里）。
REVIEWS_DIR = "verifications/reviews"
#: 索引名（一份报告一行；号源从它现读）。
INDEX_NAME = "index.jsonl"
#: 报告文件名前缀（`v-review-NNNNNN.md`）。
PREFIX = "v-review-"
#: 板项 `input_key` 前缀：V 稿（不是 ack 项，见 `conductor.ACK_REQUIRED_ITEM_PREFIXES`）。
REVIEW_PREFIX = "v-review@"
#: 板项 `input_key` 前缀：签好的稿（同一份稿的一次送审一条）。
SIGNED_PREFIX = "v-signed@"
#: 跨进程锁的文件名后缀（与索引同目录，`filelock` 的 `<目标>.lock` 形态）。
LOCK_SUFFIX = ".lock"
#: 跨进程锁的等待上限（秒）。超时是受控失败（`checked=False` + 理由），
#: 不折成"没锁"—— 拿不到锁还去发号，正是会撞号的那条路。
LOCK_TIMEOUT = 30.0
#: 号的上界：真身是 `store.MAX_ID`（= `schema.ID_DIGITS` 位十进制的最大值）。
#: 这里只引用、不另抄一个 999999 —— 上限一旦有两个字面量就会漂移，而漂移的表现
#: 是"一处 fail-closed、另一处照样发越界号"。
MAX_ID = _STORE_MAX_ID

_ID_RE = re.compile(r"^v-review-(\d{6,})$")
_LOCKS: dict[str, Any] = {}
_LOCKS_GUARD = threading.Lock()


class ReviewIdExhausted(ValueError):
    """V 稿号空间用尽（`v-review-999999` 已经是最后一个号）。

    ## 为什么是一个具名异常，而不是回绕到 `000001`

    回绕（或顺手发一个 7 位号）会让两件事同时发生：覆盖盘上已有的那一份正文，
    且索引里出现同号两行 —— 而索引既是 `_read_index` 的输入、也是 `find_review`
    的返回值，它不会报错，它只会返回"000001 指向两份报告"。这正是本模块要挡的
    那种静默损坏，所以到顶时受控抛错，让人来处理 `verifications/reviews/`。

    它继承 `ValueError`：非工具层的调用方（把 `ValueError` 当受控失败的那些）
    行为不变。`record_review` 会把它折进自己的三态（`checked=False` + 理由）——
    判定与 V 稿是两件事，号用尽不该带走判定本身（`agent_v/core.py` 的
    `_publish_v_review` 已按这条兜住）。
    """


def reviews_dir(root: str | Path) -> Path:
    """V 稿目录（只算路径，不建目录）。"""
    return Path(str(root)).joinpath(*REVIEWS_DIR.split("/"))


def reviews_index_path(root: str | Path) -> Path:
    """V 稿索引 `verifications/reviews/index.jsonl`。"""
    return reviews_dir(root) / INDEX_NAME


def review_path(root: str | Path, review_id: str) -> Path:
    """一份 V 稿的路径（只算路径）。"""
    return reviews_dir(root) / f"{str(review_id)}.md"


def _lock_for(path: Path):
    """同一路径的进程内锁（`filelock` 在同进程里不保证线程安全，两层都要）。"""
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _cross_process_lock(path: Path):
    """同一路径的跨进程锁（`<目标>.lock`；等锁超时会抛 `Timeout`）。"""
    return FileLock(str(path) + LOCK_SUFFIX, timeout=LOCK_TIMEOUT)


@contextlib.contextmanager
def _review_write_lock(root: str | Path):
    """`record_review` 的写临界区：进程内一把 + 跨进程一把（两层都要）。

    罩的是"读索引 → 发号 → 落正文 → 追加索引"这一整段，不是单独某一次写。
    只罩写文件不够：两个进程都能读到同一份旧索引，于是各自发号、各自写一份正文
    （取号点必须在锁内 —— `manuscripts.py:489-490` 的同一形态）。

    目录先建出来：索引、正文与 `<索引>.lock` 都落在这一层（`filelock` 不会替我们建
    父目录 —— 真机上第一次落 V 稿时 `verifications/reviews/` 还不存在）。
    """
    gate = reviews_dir(root)
    gate.mkdir(parents=True, exist_ok=True)
    with _lock_for(gate):
        with _cross_process_lock(reviews_index_path(root)):
            yield


def _read_index(root: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """读索引：返回 `(行, 坏行说明)`；文件不存在 = 还没有报告（不是坏）。"""
    path = reviews_index_path(root)
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    if not path.is_file():
        return rows, problems
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [f"索引读不出来（{type(exc).__name__}: {exc}）"]
    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            got = json.loads(line)
        except ValueError as exc:
            problems.append(f"索引第 {i} 行不是合法 JSON（{exc}）")
            continue
        if not isinstance(got, dict):
            problems.append(f"索引第 {i} 行不是对象")
            continue
        rows.append(got)
    return rows, problems


def _on_disk_ids(root: str | Path) -> frozenset[int]:
    """盘上已经用掉的号（`verifications/reviews/v-review-NNNNNN.md` 的文件名）。

    为什么要单独读盘、而不只看索引：正文先落、索引行后追加，两次写之间失败就会留下
    "盘上有正文、索引里没有"的一份稿。索引不是唯一真身 —— 盘上的文件也是事实，
    而且覆盖它的代价不可逆。临时文件（`.<名>.md.tmp-…`）不算号：它的 stem 带前导点，
    过不了 `_ID_RE`。
    """
    gate = reviews_dir(root)
    try:
        names = [p for p in gate.iterdir()]
    except FileNotFoundError:  # 目录还不存在 ⇒ 盘上还没有号（"列不出来"只在这一档等于"没有"）
        return frozenset()
    used: set[int] = set()
    for path in names:
        got = _ID_RE.match(path.stem) if path.suffix == ".md" else None
        if got:
            used.add(int(got.group(1)))
    return frozenset(used)


def next_review_id(rows: list[Mapping[str, Any]], taken: Iterable[int]) -> str:
    """索引 max 与盘上已用号两边取大 + 1；到上界受控抛 `ReviewIdExhausted`。

    `taken` 是盘上已用号（`_on_disk_ids`）—— 它是必填的，不给默认值：只看索引的
    发号正是"复用号、覆盖正文"那条路，而默认参数会把那条路留给下一个调用方。
    解析不出的索引行不参与发号，但不许把它们当 0（旧行为保留）。
    """
    top = 0
    for row in rows:
        got = _ID_RE.match(str(row.get("review_id") or ""))
        if got:
            top = max(top, int(got.group(1)))
    for n in taken:
        top = max(top, int(n))
    if top >= MAX_ID:
        raise ReviewIdExhausted(
            f"V 稿号已到上界 {PREFIX}{format_id(MAX_ID)}（索引 max 与盘上已用号取大 "
            f"= {top}）⇒ 不发新号：不折回 {PREFIX}{format_id(1)}（那会覆盖盘上已有的"
            f"一份正文），也不越界写更宽的号；`{REVIEWS_DIR}/` 需要人工处理")
    return f"{PREFIX}{format_id(top + 1)}"


def _anchor(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("ledger") or ""), str(row.get("verification_id") or ""))


def find_review(root: str | Path, *, ledger: str,
                verification_id: str) -> dict[str, Any] | None:
    """按台账锚点找已经落过的那一份（找不到 ⇒ `None`）。"""
    rows, _problems = _read_index(root)
    want = (str(ledger or ""), str(verification_id or ""))
    if not want[1]:
        return None
    return next((dict(r) for r in rows if _anchor(r) == want), None)


def _rel(root: str | Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(str(root)).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _atomic_write(path: Path, text: str) -> None:
    """LF 落盘 + 原子替换（临时文件与目标同目录）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _append_index(path: Path, row: Mapping[str, Any]) -> None:
    """追加一行（一次 write；追加式文件不改历史行）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str) + "\n"
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(line)


def _finding_lines(findings: list[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for item in findings:
        level = str(item.get("level") or "info")
        step = item.get("step")
        where = f"第 {step} 步" if isinstance(step, int) and not isinstance(step, bool) else "未指步"
        kind = str(item.get("kind") or "").strip()
        detail = str(item.get("detail") or "").strip()
        head = f"- [{level}] {where}"
        if kind:
            head += f" · {kind}"
        out.append(head + (f"：{detail}" if detail else ""))
    return out


def _render(*, review_id: str, at: str, statement_id: str, manuscript: str,
            manuscript_family: str, manuscript_id: str, proof_sha256: str,
            verdict: str, defect_step: Any, findings: list[Mapping[str, Any]],
            reason: str, fault_kind: str, fault_cause: str, ledger: str,
            verification_id: str) -> str:
    """把一份判定摊成给人读的 V 稿（内容只有事实与理由，不写价值判断）。"""
    lines: list[str] = [
        f"# V 审阅报告 {review_id}",
        "",
        f"- 生成时间：{at}",
        f"- 被审稿：`{manuscript or '（没有手稿路径）'}`",
        f"- 稿族 / 稿号：`{manuscript_family or '（读不出）'}` / `{manuscript_id or '（读不出）'}`",
        f"- 被审正文 sha256：`{proof_sha256 or '（读不出）'}`",
        f"- 结论：有毛病（V 的秘书语义判定：fault）",
        f"- 判词原文：{verdict or '（没有原文）'}",
        f"- 缺陷步：{('第 %s 步' % defect_step) if isinstance(defect_step, int) else '未指步'}",
        f"- 缺陷类别：{fault_kind or '（没给）'}"
        + (f"（{fault_cause}）" if fault_cause else ""),
        f"- 台账锚点：`{ledger}#{verification_id}`",
    ]
    if statement_id:
        lines.append(f"- 命题号（若在册）：`{statement_id}`")
    lines.extend(["", "## findings（含 warning）", ""])
    body = _finding_lines(findings)
    lines.extend(body or ["- （这一转没有逐条 finding；理由见下一节）"])
    lines.extend(["", "## 理由", "", reason.strip() or "（没有给理由）", ""])
    lines.extend([
        "## 判据（写报告的人与读报告的人都按这一条读）",
        "",
        "- 只要不是完全没毛病就叫有毛病；`warning` 也算有毛病。",
        "- 程序性 / 文风 fault 同样落这份报告（它不是对数学缺陷的认定，但它是"
        "「这一份没有通过」的读数）。",
        "",
    ])
    return "\n".join(lines)


def record_review(root: str | Path, *, statement_id: str, manuscript: str,
                  manuscript_family: str, manuscript_id: str,
                  proof_sha256: str, verdict: str, defect_step: Any,
                  findings: list[Mapping[str, Any]] | None, reason: str,
                  ledger: str, verification_id: str, fault_kind: str = "",
                  fault_cause: str = "", review_call: str = "", at: str = "",
                  actor: str = "agent-V") -> dict[str, Any]:
    """落一份 V 稿（幂等；号源 = 索引 max 与盘上已用号两边取大 + 1）。

    返回 `checked` / `written` / `idempotent` / `review_id` / `path` / `rel` /
    `index_path` / `sha256` / `at` / `reason` / `entry`。

    三态见模块 docstring。两种已知的受控失败也走同一形态（`checked=False` +
    理由，不抛出去）：号用尽（`ReviewIdExhausted`）与等号锁超时（`filelock.Timeout`）。
    它们是"这一份没落成"，不是"又写了一份"，也不许带走调用方的判定。
    """
    at = str(at or "").strip()
    out: dict[str, Any] = {
        "checked": False, "written": False, "idempotent": False,
        "review_id": "", "path": "", "rel": "", "index_path": str(reviews_index_path(root)),
        "sha256": "", "at": at, "reason": "", "entry": {},
        "statement_id": str(statement_id or ""), "ledger": str(ledger or ""),
        "verification_id": str(verification_id or ""),
    }
    if not str(verification_id or "").strip() or not str(ledger or "").strip():
        out["reason"] = ("没有台账锚点（台账路径 / verification_id）⇒ 这一份 V 稿"
                         "没有幂等键，不落盘（不许靠猜一个编号写第二份）")
        return out
    try:
        with _review_write_lock(root):
            rows, problems = _read_index(root)
            if problems:
                out["reason"] = ("V 稿索引读不出来 ⇒ 不发新号、不落盘："
                                 + "；".join(problems[:3]))
                return out
            existing = next((dict(r) for r in rows
                             if _anchor(r) == (str(ledger), str(verification_id))), None)
            if existing is not None:
                out.update(checked=True, idempotent=True, written=False,
                           review_id=str(existing.get("review_id") or ""),
                           path=str(review_path(root, str(existing.get("review_id") or ""))),
                           rel=str(existing.get("path") or ""),
                           sha256=str(existing.get("sha256") or ""),
                           at=str(existing.get("at") or at),
                           reason="同一台账锚点已经落过一份 V 稿 ⇒ 回旧的，不写第二份",
                           entry=existing)
                return out
            try:
                review_id = next_review_id(rows, _on_disk_ids(root))
            except ReviewIdExhausted as exc:
                out["reason"] = str(exc)
                return out
            path = review_path(root, review_id)
            rel = _rel(root, path)
            items = [dict(f) for f in (findings or []) if isinstance(f, Mapping)]
            text = _render(
                review_id=review_id, at=at, statement_id=str(statement_id or ""),
                manuscript=str(manuscript or ""),
                manuscript_family=str(manuscript_family or ""),
                manuscript_id=str(manuscript_id or ""),
                proof_sha256=str(proof_sha256 or ""), verdict=str(verdict or ""),
                defect_step=defect_step, findings=items, reason=str(reason or ""),
                fault_kind=str(fault_kind or ""), fault_cause=str(fault_cause or ""),
                ledger=str(ledger), verification_id=str(verification_id))
            try:
                _atomic_write(path, text)
            except OSError as exc:
                out["reason"] = f"V 稿写不进去（{type(exc).__name__}: {exc}）"
                return out
            entry = {
                "review_id": review_id, "at": at, "path": rel,
                "statement_id": str(statement_id or ""),
                "manuscript": str(manuscript or ""),
                "manuscript_family": str(manuscript_family or ""),
                "manuscript_id": str(manuscript_id or ""),
                "proof_sha256": str(proof_sha256 or ""),
                "verdict": str(verdict or ""), "axis": "fault",
                "defect_step": defect_step, "fault_kind": str(fault_kind or ""),
                "fault_cause": str(fault_cause or ""),
                "findings": len(items), "ledger": str(ledger),
                "verification_id": str(verification_id),
                "review_call": str(review_call or ""),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "actor": str(actor or ""),
            }
            try:
                _append_index(reviews_index_path(root), entry)
            except OSError as exc:
                out["reason"] = (f"V 稿索引写不进去（{type(exc).__name__}: {exc}）"
                                 f"；正文已落 `{rel}`，但索引缺这一行，必须重落")
                return out
            out.update(checked=True, written=True, review_id=review_id,
                       path=str(path), rel=rel, entry=entry,
                       sha256=entry["sha256"],
                       reason=f"V 稿已落盘：{rel}")
            return out
    except Timeout as exc:
        out["reason"] = (f"取 V 稿号锁超时（{LOCK_TIMEOUT:g}s；另一个写者卡住了）⇒ "
                         f"不发新号、不落盘，稍后重试（{exc}）")
        return out
    except OSError as exc:  # 目录 / 锁文件建不出来：受控失败，不带走判定
        out["reason"] = f"V 稿落盘失败（{type(exc).__name__}: {exc}）"
        return out


def _conductor_for(store: Any) -> Any:
    """取这个工作区已经存在的主控；没有 ⇒ `None`（不顺手建一个）。"""
    from .tools.conductor_tools import cached_conductor

    return cached_conductor(store)


def _deliver(store: Any, root: str | Path, *, key: str, summary: str,
             detail: str, role_hint: str = "", actor: str = "agent-V",
             depth: int = 1) -> dict[str, Any]:
    """开一条不要求 ack 的 notice 板项 + 写 detail（V 稿 / 签好的稿共用）。"""
    out: dict[str, Any] = {
        "checked": False, "state": "", "item_id": "", "key": key,
        "role": "", "parent_task_id": "", "reason": "",
        "detail_path": "", "existing": False,
    }
    conductor = _conductor_for(store)
    if conductor is None:
        out.update(state="pending", reason="这一趟没有已装配的主控 ⇒ 板项开不了"
                                            "（不是「已经送到」）")
        return out
    from . import conductor as _CND

    parent_id, parent_role = _CND.current_parent()
    if not str(parent_id or ""):
        out.update(state="undelivered",
                   reason="这一趟调用不在任何召唤里（`current_parent` 是空）⇒ "
                          "读不到被审者；不拿「谁醒着」当收件人")
        return out
    role = str(parent_role or role_hint or "")
    out.update(role=role, parent_task_id=str(parent_id))
    if not role:
        out.update(state="undelivered",
                   reason="读不到被审者的角色（`current_parent` 只给了编号）⇒ "
                          "不拿一个默认角色去猜收件人")
        return out
    try:
        board = [dict(r) for r in conductor._board_rows()]
    except Exception:  # noqa: BLE001 —— 读不成就不去重（宁多一条，不静默丢）
        board = []
    have = next((r for r in board if str(r.get("input_key") or "") == key), None)
    if have is not None:
        out.update(checked=True, state="dispatched", existing=True,
                   item_id=str(have.get("task_id") or ""),
                   reason=f"这一条已经在板上（{have.get('task_id') or '没读到编号'}）⇒ 不重开")
        return out
    try:
        item_id = conductor.open_item(
            kind="notice", role=role, expects="ack", action="notice",
            summary=summary, called_by=actor, parent_task_id=str(parent_id),
            depth=max(1, int(depth or 1)), input_key=key)
        got, problem = conductor.set_item_detail(item_id, detail)
    except Exception as exc:  # noqa: BLE001 —— 投递失败是框架失败，不许带走判定
        out.update(state="error",
                   reason=f"板项没开成（{type(exc).__name__}: {exc}）")
        return out
    out.update(checked=bool(got), state=("dispatched" if got else "pending"),
               item_id=str(item_id), detail_path=str(detail or ""),
               reason=(str(problem) if problem else
                       f"已投给 {parent_id} 的板项 {item_id}"))
    return out


def deliver_review(store: Any, *, root: str | Path, review: Mapping[str, Any],
                   statement_id: str = "", actor: str = "agent-V",
                   depth: int = 1) -> dict[str, Any]:
    """把一份 V 稿作为 notice 交给被审者（不要求 ack）。"""
    got = dict(review or {})
    review_id = str(got.get("review_id") or "")
    if not review_id:
        return {"checked": False, "state": "not_written", "item_id": "", "key": "",
                "role": "", "parent_task_id": "", "reason": "没有 V 稿编号 ⇒ 不投",
                "detail_path": "", "existing": False}
    rel = str(got.get("rel") or got.get("path") or "")
    entry = dict(got.get("entry") or {})
    # 程序性 / 文风那一档：正文没有被指出数学缺陷 ⇒ 同一份正文可以原样再送。
    # 这句话原先只活在已退场的回执层（`vreceipts._publish` 的 "report" 措辞）；
    # 退场之后由这份 notice 承担 —— 它是判定那一刻唯一投到送审者名下的文本。
    report_only = str(entry.get("fault_kind") or "") in ("procedural", "style")
    next_step = ("这一条是程序性 / 文风问题：正文没有被指出数学缺陷 ⇒ 同一份正文可以原样再送"
                 "（不必改稿换 sha）。\n" if report_only else
                 "V 的原文不转达；这份报告就是给你的审阅意见。改完把同一份稿重新送 V。\n")
    detail = (
        f"V 的审阅报告：`{rel}`\n"
        f"- 被审稿：`{entry.get('manuscript') or ''}`\n"
        f"- 结论：有毛病（V 的秘书语义判定：fault）\n"
        f"- 台账锚点：`{entry.get('ledger') or ''}"
        f"#{entry.get('verification_id') or ''}`\n"
        + next_step
    )
    return _deliver(store, root, key=f"{REVIEW_PREFIX}{review_id}",
                    summary=f"V 的审阅报告（有毛病）：{review_id}",
                    detail=detail, role_hint="", actor=actor, depth=depth)


def deliver_signed(store: Any, *, root: str | Path, manuscript: str,
                   proof_sha256: str, sign_rel: str, ledger: str,
                   verification_id: str, streak: int, need: int,
                   by: str = "", review_call: str = "",
                   actor: str = "agent-V", depth: int = 1) -> dict[str, Any]:
    """把签好的稿作为 notice 交给送审者（不要求 ack）。"""
    key = f"{SIGNED_PREFIX}{review_call or str(proof_sha256)[:16] or 'unknown'}"
    detail = (
        f"V 已经把签签进稿里：`{manuscript}`\n"
        f"- 正文 sha256：`{proof_sha256}`\n"
        f"- 签文件：`{sign_rel or '（没读到）'}`\n"
        f"- 门槛：由框架按这一趟送审自己数（这一签已到位）\n"
        f"- 落签者：{by or '（没读到）'}\n"
        f"- 台账：`{ledger}#{verification_id}`\n"
        "这一份稿已经签好，可以直接交给 B 收录（按正文 sha 认领）。\n"
    )
    return _deliver(store, root, key=key, summary="V 签好的稿",
                    detail=detail, role_hint="", actor=actor, depth=depth)

# -*- coding: utf-8 -*-
"""交接手稿（`draft/37` §134）：每个智能体交接工作前写一份手稿，留言只传编号。

## 用户口径（逐字，2026-10-04）

> 我觉得各智能体在互相传递信息时可以借助手稿的方式，即建一个收集手稿的文件夹，
> 每个智能体要交接工作前写一份手稿放在里面，且有标号（这个标号靠脚本拿最新的，从 0000 开始顺次标），
> 传信息时就传手稿编号。这样的话派活也有依据，溯源也很清晰。
> 至于手稿的命名就是标号+谁to谁，特别地如果是给所有人就是谁toALL。手稿格式就用 LLM 最擅长的 markdown。

## 这一层解决什么（与既有的三层分开，别混）

| 层 | 落点 | 是什么 |
|---|---|---|
| 草稿本 | `<工作区>/notes/<角色>.md` | 角色自己的思考（「不交接」） |
| 领域对象 | `<工作区>/documents/<doc_id>.md`（`documents` 表） | 论文/手稿本体（进台账、要审校） |
| 「交接手稿」 | `<工作区>/manuscripts/<编号>-<From>to<To>.md` | 「写给某个同伴（或所有人）的工作交接」：我做了什么、依据是什么、你要做什么、我还卡在哪 |

编号由「脚本」分配（不靠模型记）：扫盘上已有的最大编号 +1，第一份是 `0000`；
命名 `<编号>-<From>to<To>.md`（给所有人写 `toALL`）。留言里只传编号，
收件人用 `manuscripts.read` 读全文 —— 于是"派活依据"与"溯源"都落在盘上，
而不是散在对话里。

## 为什么编号必须走脚本 + 锁

`conductor.summon_many` 是「并发」的（同波多个角色真的同时跑）：两份手稿同时写时，
"读最大号 +1"这种写法会撞号，而撞号的表现是「后者覆盖前者」（文件名相同）
—— 一份交接记录静默消失。所以分配号与写文件在同一把文件锁里做（`filelock`，
与 `store` 的写者锁同一族工具）。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from filelock import FileLock, Timeout

from . import schema as S

#: 手稿目录（工作区根下）。
MANUSCRIPTS_DIR = "manuscripts"
#: 索引文件（每写一份追加一行；它是"这一趟交接了什么"的可读账）。
INDEX_NAME = "index.jsonl"
#: 编号锁（分配号与写盘在同一把锁里）。
LOCK_NAME = ".lock"
#: 给所有人的收件人写法（用户口径：`toALL`）。
ALL = "ALL"
#: 文件名形态：`0007-DtoF.md` / `0011-AtoALL.md`。
NAME_RE = re.compile(r"^(\d{4})-([A-Za-z]+)to([A-Za-z]+)\.md$")


def dir_of(root: str | Path) -> Path:
    return Path(root) / MANUSCRIPTS_DIR


def ensure_dir(root: str | Path) -> Path:
    d = dir_of(root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def valid_recipient(token: str) -> bool:
    return str(token) in set(S.ROLES) | {ALL}


def valid_sender(token: str) -> bool:
    return str(token) in set(S.ROLES) | {S.CONDUCTOR_ROLE}


def name_for(mid: str, sender: str, recipient: str) -> str:
    """`<编号>-<From>to<To>.md`（收件人是所有人时写 `toALL`）。"""
    return f"{mid}-{sender}to{recipient}.md"


def parse_name(path: str | Path) -> dict[str, str] | None:
    m = NAME_RE.match(Path(path).name)
    if not m:
        return None
    return {"id": m.group(1), "sender": m.group(2), "recipient": m.group(3)}


def index_path(root: str | Path) -> Path:
    return dir_of(root) / INDEX_NAME


def read_index(root: str | Path) -> list[dict[str, Any]]:
    """读索引（坏行跳过并计数，不抛：一份坏行不该让整层不可用）。"""
    p = index_path(root)
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            got = json.loads(line)
        except ValueError:
            continue
        if isinstance(got, dict):
            out.append(got)
    return out


def _scan_ids(root: str | Path) -> list[str]:
    """盘上出现过的全部编号（文件名 + 索引，两处取并集 —— 任何一处漏读都不该导致撞号）。"""
    ids: set[str] = set()
    d = dir_of(root)
    if d.is_dir():
        for p in d.glob("*.md"):
            got = parse_name(p)
            if got:
                ids.add(got["id"])
    for rec in read_index(root):
        mid = str(rec.get("id") or "")
        if len(mid) == 4 and mid.isdigit():
            ids.add(mid)
    return sorted(ids)


def next_id(root: str | Path) -> str:
    """下一个编号：盘上最大号 +1（第一份是 `0000`）。不持锁时只用于「读」，写请走 `write`。"""
    ids = _scan_ids(root)
    nxt = (int(ids[-1]) + 1) if ids else 0
    return f"{nxt:04d}"


def path_of(root: str | Path, mid: str) -> Path | None:
    """按编号找文件（编号唯一 ⇒ 至多一份；找不到返回 `None`）。"""
    mid = str(mid).strip()
    if not mid.isdigit():
        return None
    d = dir_of(root)
    if not d.is_dir():
        return None
    for p in sorted(d.glob(f"{int(mid):04d}-*.md")):
        return p
    return None


def _render(mid: str, sender: str, recipient: str, title: str, body: str, *,
           refs: Iterable[str] = (), task_id: str = "", sid: str = "",
           created_at: str = "") -> str:
    """手稿正文（markdown）：头部是「机器可读的事实」，正文是给人/模型读的话。"""
    stamp = created_at or _now_iso()
    head = [
        f"# {mid}｜{sender} → {recipient}",
        "",
        f"- 编号：{mid}",
        f"- 从：{sender}",
        f"- 到：{recipient}",
        f"- 标题：{title}",
        f"- 时间：{stamp}",
        f"- 引用（前序手稿）：{'、'.join(str(x) for x in refs) or '（无）'}",
        f"- 台账：{task_id or '（未记）'}"
        + (f" / sid {sid}" if sid else ""),
        "",
        "## 正文",
        "",
        str(body or "").rstrip(),
        "",
    ]
    return "\n".join(head)


def write(root: str | Path, *, sender: str, recipient: str, title: str, body: str,
          refs: Iterable[str] = (), summary: str = "", task_id: str = "",
          sid: str = "", timeout: float = 30.0) -> dict[str, Any]:
    """写一份交接手稿，返回它的记录（含 `id` / `path`）。

    拒绝（抛 `ValueError`，「零写入」）：发件人/收件人不是合法角色、标题为空、正文为空。
    "空手稿"必须被拒：它是"我交接了"的假证据，而这一层存在的全部意义就是可溯源。
    """
    sender = str(sender or "").strip()
    recipient = str(recipient or "").strip().upper()
    title = str(title or "").strip()
    body = str(body or "").strip()
    if not valid_sender(sender):
        raise ValueError(f"发件人必须是 {sorted(set(S.ROLES) | {S.CONDUCTOR_ROLE})} 之一，收到 {sender!r}")
    if not valid_recipient(recipient):
        raise ValueError(f"收件人必须是 {sorted(set(S.ROLES) | {ALL})} 之一（给所有人写 {ALL}），"
                         f"收到 {recipient!r}")
    if not title:
        raise ValueError("标题不能为空（没有标题的手稿在索引里认不出来）")
    if not body:
        raise ValueError("正文不能为空（空手稿是『我交接了』的假证据）")
    refs_list = [str(x).strip() for x in refs if str(x).strip()]
    for ref in refs_list:
        if path_of(root, ref) is None:
            raise ValueError(f"引用的前序手稿 {ref!r} 不在盘上 ⇒ 不许凭空引用（溯源链断了）")

    d = ensure_dir(root)
    lock = FileLock(str(d / LOCK_NAME), timeout=timeout)
    try:
        with lock:
            mid = next_id(root)
            p = d / name_for(mid, sender, recipient)
            if p.exists():                      # 兜底：并发下真撞了就往后挪
                mid = f"{int(mid) + 1:04d}"
                p = d / name_for(mid, sender, recipient)
            created_at = _now_iso()
            text = _render(mid, sender, recipient, title, body, refs=refs_list,
                          task_id=task_id, sid=sid, created_at=created_at)
            p.write_text(text, encoding="utf-8", newline="\n")
            blob = text.encode("utf-8")
            rec = {"id": mid, "path": str(p.relative_to(Path(root))).replace("\\", "/"),
                   "sender": sender, "recipient": recipient, "title": title,
                   "summary": str(summary or "").strip()[:400],
                   "refs": refs_list, "sha256": hashlib.sha256(blob).hexdigest(),
                   "bytes": len(blob), "created_at": created_at,
                   "task_id": task_id, "sid": sid}
            with index_path(root).open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            return rec
    except Timeout as exc:  # pragma: no cover - 只有并发极端场景才会撞上
        raise ValueError(f"取手稿编号锁超时（{timeout}s）：有另一个写者卡住了，稍后重试") from exc


def read(root: str | Path, mid: str) -> dict[str, Any] | None:
    """按编号读一份手稿（返回 `{record, text, path}`；编号不存在 ⇒ `None`）。"""
    p = path_of(root, mid)
    if p is None:
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    rec = next((r for r in read_index(root) if str(r.get("id")) == f"{int(str(mid)):04d}"), None)
    if rec is None:
        got = parse_name(p) or {}
        rec = {"id": got.get("id", ""), "path": str(p.relative_to(Path(root))).replace("\\", "/"),
               "sender": got.get("sender", ""), "recipient": got.get("recipient", ""),
               "title": "", "summary": "", "refs": [], "sha256": "", "bytes": len(text.encode("utf-8")),
               "created_at": "", "task_id": "", "sid": ""}
    return {"record": rec, "text": text, "path": str(p)}


def list_all(root: str | Path, *, to: str = "", sender: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """列手稿（可按收件人/发件人过滤；`to=ALL` 也把广播给所有人的那批算进来）。

    以「盘上的文件」为准（索引只是账）：文件在而索引缺行时，记录照样列出来
    （那时字段少一些）—— "盘上有、账上没有"不该让手稿消失。
    """
    out: list[dict[str, Any]] = []
    by_id = {str(r.get("id")): r for r in read_index(root)}
    d = dir_of(root)
    if d.is_dir():
        for p in sorted(d.glob("*.md")):
            got = parse_name(p)
            if not got:
                continue
            rec = dict(by_id.get(got["id"]) or {})
            rec.setdefault("id", got["id"])
            rec.setdefault("sender", got["sender"])
            rec.setdefault("recipient", got["recipient"])
            rec.setdefault("path", str(p.relative_to(Path(root))).replace("\\", "/"))
            out.append(rec)
    if to:
        want = str(to).upper()
        out = [r for r in out
               if str(r.get("recipient")) == want
               or (want != ALL and str(r.get("recipient")) == ALL)]
    if sender:
        out = [r for r in out if str(r.get("sender")) == str(sender)]
    return out[-limit:]


def digest(root: str | Path, *, limit: int = 5) -> str:
    """给提示词用的一小段读数：最近几份交接手稿（编号 + 谁给谁 + 标题）。"""
    rows = list_all(root, limit=limit)
    if not rows:
        return "（还没有交接手稿）"
    return "\n".join(
        f"- {r.get('id')} {r.get('sender')}→{r.get('recipient')}：{r.get('title') or '(无标题)'}"
        for r in rows)


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def selftest() -> int:
    """最小自检：编号从 0000 顺次、命名含 to/发件人、索引与读回一致、拒绝空手稿。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="manuscripts_selftest_"))
    checks: list[tuple[str, bool]] = []
    a = write(root, sender="D", recipient="F", title="把猜想交给你", body="## 任务\n证明它。")
    b = write(root, sender="F", recipient="ALL", title="进展汇报", body="卡在第 3 步。")
    checks.append(("第一份是 0000", a["id"] == "0000"))
    checks.append(("命名是 编号-FromtoTo", Path(a["path"]).name == "0000-DtoF.md"))
    checks.append(("给全体写 toALL", Path(b["path"]).name == "0001-FtoALL.md"))
    checks.append(("读得回来", (read(root, "0001") or {}).get("record", {}).get("sender") == "F"))
    checks.append(("按收件人过滤（G 也能收到广播的那份）",
                   [r["id"] for r in list_all(root, to="G")] == ["0001"]))
    empty_ok = False
    try:
        write(root, sender="D", recipient="F", title="空的", body="  ")
    except ValueError:
        empty_ok = True
    checks.append(("空正文被拒（零写入）", empty_ok))
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())

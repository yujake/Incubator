# -*- coding: utf-8 -*-
"""交接手稿（`draft/37` §134；存储改为追加式 JSONL：`draft/39` §C1–C4，用户 2026-10-05 裁）。

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
| 「交接手稿」 | `<工作区>/manuscripts/handoffs.jsonl`（一行一份） | 「写给某个同伴（或所有人）的工作交接」：我做了什么、依据是什么、你要做什么、我还卡在哪 |

## 为什么从「一份一个 .md 文件」改成「追加式 JSONL」（用户 2026-10-05 裁）

1. 一行一份，追加写入：并发写者不需要"抢一个文件名"，id 由持锁的读-算-写序列分配，
   撞号与覆盖这两件事在结构上不可能发生（旧格式靠"文件已存在就往后挪"兜底，
   而那是"事后发现"，不是"结构上没有"）；
2. 收工门读数不打折：`closing.manuscript_rows` 改成数行（不是数文件）——
   "盘上有几份交接"这个数不再依赖文件名能不能被解析（旧口径下改个名就少一份）；
3. 查询由脚本做（`scripts/manuscripts_query.py`）：按编号/收发/时间/引用检索，
   并顺手把被引用命题的五元位快照（`draft/39` §3.14）打出来 —— 这件事不进模型上下文，
   需要时脚本现算。

每行的字段：`id` / `sender` / `to` / `summary` / `body` / `refs` / `created_at` /
`task_id` / `sid` / `sha256` / `bytes`。其中 `to` / `summary` / `body` 三者必填
（`summary` 是进留言的那一句话：`[手稿 NNNN] <summary>`；`body` 是 markdown 正文）。

旧格式（`<编号>-<From>to<To>.md`）仍然读得回来（`read` / `list_all` 有旧文件回退），
但不计入 `manuscript_rows`：新口径数的是"行"，旧文件在读数明细里另列一栏
（既不假装没有，也不冒充新格式）。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from filelock import FileLock, Timeout

from . import jsonlfile as JF
from . import schema as S

#: 手稿目录（工作区根下）。
MANUSCRIPTS_DIR = "manuscripts"
#: 追加式账本：一行一份交接（新格式的唯一真相）。
HANDOFFS_NAME = "handoffs.jsonl"
#: 编号锁（分配号与追加行在同一把锁里）。
LOCK_NAME = ".lock"
#: 给所有人的收件人写法（用户口径：`toALL`）。
ALL = "ALL"
#: 旧格式文件名（`0007-DtoF.md` / `0011-AtoALL.md`）：只读回退用，不再写。
NAME_RE = re.compile(r"^(\d{4})-([A-Za-z]+)to([A-Za-z]+)\.md$")
#: 一行的必填字段（缺一 ⇒ 这一行不是一份可溯源的交接）。
REQUIRED_FIELDS: tuple[str, ...] = ("to", "summary", "body")


def dir_of(root: str | Path) -> Path:
    return Path(root) / MANUSCRIPTS_DIR


def handoffs_path(root: str | Path) -> Path:
    return dir_of(root) / HANDOFFS_NAME


def ensure_dir(root: str | Path) -> Path:
    d = dir_of(root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def valid_recipient(token: str) -> bool:
    return str(token) in set(S.ROLES) | {ALL}


def valid_sender(token: str) -> bool:
    return str(token) in set(S.ROLES) | {S.CONDUCTOR_ROLE}


def name_for(mid: str, sender: str, recipient: str) -> str:
    """旧格式的文件名 `<编号>-<From>to<To>.md`（`toALL` 表示所有人）。

    新格式不再产生文件名；这个函数留着是因为旧工作区的手稿要按同一个规则读回来
    （`read` 的旧文件回退），命名规则只有这一份实现。
    """
    return f"{mid}-{sender}to{recipient}.md"


def parse_name(path: str | Path) -> dict[str, str] | None:
    m = NAME_RE.match(Path(path).name)
    if not m:
        return None
    return {"id": m.group(1), "sender": m.group(2), "recipient": m.group(3)}


def read_rows(root: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """读账本的所有行；返回 `(行, 坏行说明)`（坏行逐条报出，不静默跳过）。"""
    return JF.read_jsonl(handoffs_path(root))


def rows(root: str | Path) -> list[dict[str, Any]]:
    """账本里的行（坏行由 `read_rows` 报；这里只要行）。"""
    return read_rows(root)[0]


#: `read_index` 是旧名字（旧格式里它是"索引"；新格式里账本就是唯一真相）。
def read_index(root: str | Path) -> list[dict[str, Any]]:
    return rows(root)


def _legacy_files(root: str | Path) -> list[tuple[str, Path, dict[str, str]]]:
    """旧格式文件（`<编号>-<From>to<To>.md`）⇒ `(id, 路径, 解析出的字段)`，按编号排序。"""
    d = dir_of(root)
    out: list[tuple[str, Path, dict[str, str]]] = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.md")):
        got = parse_name(p)
        if got:
            out.append((got["id"], p, got))
    return out


def _legacy_row(root: str | Path, mid: str, path: Path, got: Mapping[str, str]) -> dict[str, Any]:
    """把一个旧格式文件读成一行（`format=md_legacy` 显式标出来，免得冒充新格式）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    title = ""
    for line in text.splitlines():
        if line.startswith("- 标题："):
            title = line.split("：", 1)[1].strip()
            break
    blob = text.encode("utf-8")
    return {"id": mid, "sender": got.get("sender", ""), "to": got.get("recipient", ""),
            "summary": title, "body": text, "refs": [], "created_at": "",
            "task_id": "", "sid": "", "sha256": hashlib.sha256(blob).hexdigest(),
            "bytes": len(blob), "format": "md_legacy",
            "path": str(path.relative_to(Path(root))).replace("\\", "/")}


def _scan_ids(root: str | Path) -> list[str]:
    """盘上出现过的全部编号（账本行 + 旧文件，两处取并集 —— 任何一处漏读都不该导致撞号）。"""
    ids: set[str] = set()
    for rec in rows(root):
        mid = str(rec.get("id") or "")
        if len(mid) == 4 and mid.isdigit():
            ids.add(mid)
    for mid, _p, _got in _legacy_files(root):
        ids.add(mid)
    return sorted(ids)


def next_id(root: str | Path) -> str:
    """下一个编号：盘上最大号 +1（第一份是 `0000`）。不持锁时只用于「读」，写请走 `write`。"""
    ids = _scan_ids(root)
    nxt = (int(ids[-1]) + 1) if ids else 0
    return f"{nxt:04d}"


def row_of(root: str | Path, mid: str) -> dict[str, Any] | None:
    """按编号取一行（新格式优先；找不到再回退到旧文件；都没有 ⇒ `None`）。"""
    want = f"{int(str(mid)):04d}" if str(mid).strip().isdigit() else ""
    if not want:
        return None
    for rec in rows(root):
        if str(rec.get("id") or "") == want:
            return rec
    d = dir_of(root)
    if d.is_dir():
        for p in sorted(d.glob(f"{want}-*.md")):
            got = parse_name(p)
            if got:
                return _legacy_row(root, want, p, got)
    return None


def path_of(root: str | Path, mid: str) -> Path | None:
    """按编号找旧格式文件（新格式没有一文件一手稿这回事 ⇒ 找不到返回 `None`）。"""
    want = f"{int(str(mid)):04d}" if str(mid).strip().isdigit() else ""
    if not want:
        return None
    d = dir_of(root)
    if not d.is_dir():
        return None
    for p in sorted(d.glob(f"{want}-*.md")):
        return p
    return None


def _render_body(sender: str, recipient: str, summary: str, body: str, *,
                 refs: Iterable[str] = (), task_id: str = "", sid: str = "",
                 created_at: str = "") -> str:
    """给 handoff 记录的 `body` 前面留一段机器可读的头部（人读 markdown、机读字段）。

    行里已经有一份结构化字段了，为什么正文还要带头部：`manuscripts.read` 交回给模型的
    是 `body` 原文，而"这份是谁给谁的、引了哪几份"必须在它读到的那段文字里 ——
    否则收件人得再调一次工具才知道自己在读谁的手稿。
    """
    head = [
        f"# {sender} → {recipient}｜{summary}",
        "",
        f"- 从：{sender}",
        f"- 到：{recipient}",
        f"- 一句话：{summary}",
        f"- 时间：{created_at or _now_iso()}",
        f"- 引用（前序手稿 / 台账对象）：{'、'.join(str(x) for x in refs) or '（无）'}",
        f"- 台账：{task_id or '（未记）'}" + (f" / sid {sid}" if sid else ""),
        "",
    ]
    return "\n".join(head) + "\n" + str(body or "").rstrip() + "\n"


#: 引用里 `前缀:编号` 的写法能指向的台账（`draft/39` §C4：手稿的引用面不止前序手稿）。
OBJECT_REFS: dict[str, str] = {
    "stmt": "statements", "exp": "experiments", "lit": "literature", "rel": "relations",
}


def ref_problem(root: str | Path, ref: str) -> str:
    """这一条引用能不能立住（空串 = 可以）。

    两条合法写法（`draft/39` §C2）：

    - 四位手稿编号（`"0007"`）⇒ 必须在盘上存在（行或旧文件）；
    - `前缀:编号`（`stmt:0007` / `exp:0002` / `lit:0004` / `rel:0011`）⇒ 必须在对应台账里存在。

    为什么写入期要核（而不是留给读者）：引用是"溯源链"的边，悬空的边会让
    "这份手稿的依据是什么"在半年后变成一句无法复核的话 —— 而写入期是唯一能指出
    "你引错了"的时刻（那时作者还在）。
    """
    text = str(ref).strip()
    if not text:
        return ""
    if ":" in text:
        ns, _, obj = text.partition(":")
        table = OBJECT_REFS.get(ns)
        if table is None:
            return (f"引用 {text!r} 的前缀不认识：认 {'/'.join(sorted(OBJECT_REFS))}: 这几种，"
                    "或者四位手稿编号")
        p = Path(root) / "data" / f"{table}.json"
        if not p.is_file():
            return f"引用 {text!r}，而工作区里没有 `data/{table}.json` ⇒ 这条引用悬空"
        try:
            rows = list(json.loads(p.read_text(encoding="utf-8")).get("rows") or [])
        except ValueError as exc:
            return f"引用 {text!r} 核不了：`data/{table}.json` 读不出来（{type(exc).__name__}）"
        id_field = str((S.TABLES.get(table) or {}).get("id_field") or "id")
        if not any(str(r.get(id_field) or "") == obj for r in rows):
            return f"引用 {text!r} 不在 `{table}` 台账里 ⇒ 不许凭空引用（溯源链断了）"
        return ""
    if row_of(root, text) is None:
        return f"引用的前序手稿 {text!r} 不在盘上 ⇒ 不许凭空引用（溯源链断了）"
    return ""


def write(root: str | Path, *, sender: str, recipient: str, title: str = "", body: str,
          refs: Iterable[str] = (), summary: str = "", task_id: str = "",
          sid: str = "", timeout: float = 30.0) -> dict[str, Any]:
    """追加一份交接手稿，返回它的那一行（含 `id`）。

    拒绝（抛 `ValueError`，「零写入」）：发件人/收件人不是合法角色、没有一句话说明、
    正文为空。"空手稿"必须被拒：它是"我交接了"的假证据，而这一层存在的全部意义就是可溯源。

    `title` 是旧参数名：它现在与 `summary` 是同一件事（进留言的那一句话）。
    两者都给了就以 `summary` 为准，不给 `summary` 时把 `title` 当它 —— 旧调用点不用改。
    """
    sender = str(sender or "").strip()
    recipient = str(recipient or "").strip().upper()
    one_line = str(summary or "").strip() or str(title or "").strip()
    text_body = str(body or "").strip()
    if not valid_sender(sender):
        raise ValueError(f"发件人必须是 {sorted(set(S.ROLES) | {S.CONDUCTOR_ROLE})} 之一，收到 {sender!r}")
    if not valid_recipient(recipient):
        raise ValueError(f"收件人必须是 {sorted(set(S.ROLES) | {ALL})} 之一（给所有人写 {ALL}），"
                         f"收到 {recipient!r}")
    if not one_line:
        raise ValueError(
            "summary 不能为空（它就是留言里那一句 `[手稿 NNNN] <summary>`）—— "
            "没有这一句，收件人只看到一个编号，等于让他自己去翻"
        )
    if not text_body:
        raise ValueError("正文不能为空（空手稿是『我交接了』的假证据）")
    refs_list = [str(x).strip() for x in refs if str(x).strip()]
    for ref in refs_list:
        why = ref_problem(root, ref)
        if why:
            raise ValueError(why)

    d = ensure_dir(root)
    lock = FileLock(str(d / LOCK_NAME), timeout=timeout)
    try:
        with lock:
            mid = next_id(root)
            created_at = _now_iso()
            full_body = _render_body(sender, recipient, one_line, text_body,
                                     refs=refs_list, task_id=task_id, sid=sid,
                                     created_at=created_at)
            blob = full_body.encode("utf-8")
            rec: dict[str, Any] = {
                "id": mid, "sender": sender, "to": recipient, "summary": one_line,
                "body": full_body, "refs": refs_list, "created_at": created_at,
                "task_id": task_id, "sid": sid,
                "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob),
                "path": f"{MANUSCRIPTS_DIR}/{HANDOFFS_NAME}#{mid}",
                "format": "jsonl",
            }
            line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
            with handoffs_path(root).open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
            return rec
    except Timeout as exc:  # pragma: no cover - 只有并发极端场景才会撞上
        raise ValueError(f"取手稿编号锁超时（{timeout}s）：有另一个写者卡住了，稍后重试") from exc


def read(root: str | Path, mid: str) -> dict[str, Any] | None:
    """按编号读一份手稿（返回 `{record, text, path}`；编号不存在 ⇒ `None`）。"""
    rec = row_of(root, mid)
    if rec is None:
        return None
    got = str(rec.get("path") or "")
    return {"record": rec, "text": str(rec.get("body") or ""), "path": got}


def list_all(root: str | Path, *, to: str = "", sender: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """列手稿（可按收件人/发件人过滤；`to=ALL` 也把广播给所有人的那批算进来）。

    新格式（账本行）与旧格式（`.md` 文件）都列出来；旧的那些带 `format=md_legacy`。
    """
    out: list[dict[str, Any]] = [dict(r) for r in rows(root)]
    seen = {str(r.get("id") or "") for r in out}
    for mid, path, parsed in _legacy_files(root):
        if mid in seen:
            continue
        out.append(_legacy_row(root, mid, path, parsed))
    out.sort(key=lambda r: str(r.get("id") or ""))
    if to:
        want = str(to).upper()
        out = [r for r in out
               if str(r.get("to")) == want
               or (want != ALL and str(r.get("to")) == ALL)]
    if sender:
        out = [r for r in out if str(r.get("sender")) == str(sender)]
    return out[-limit:]


def query(root: str | Path, *, mid: str = "", to: str = "", sender: str = "",
          since: str = "", refs: str = "", limit: int = 50) -> tuple[list[dict[str, Any]], list[str]]:
    """脚本用的检索面（`scripts/manuscripts_query.py` 的唯一实现）。

    过滤口径：`mid` 精确；`to`/`sender` 精确（`to=ALL` 只给广播）；`since` 按 ISO 时间字符串
    前缀比（`2026-10-05` 这种日期前缀就够用）；`refs` 是"引用了这个编号/对象"的子串匹配。
    返回 `(命中行, 坏行说明)` —— 坏行照样报出来（"读不出"不许被读成"没有"）。
    """
    all_rows, problems = read_rows(root)
    out: list[dict[str, Any]] = [dict(r) for r in all_rows]
    seen = {str(r.get("id") or "") for r in out}
    for rid, path, parsed in _legacy_files(root):
        if rid not in seen:
            out.append(_legacy_row(root, rid, path, parsed))
    out.sort(key=lambda r: str(r.get("id") or ""))
    if mid:
        want = str(mid).strip()
        want = f"{int(want):04d}" if want.isdigit() else want
        out = [r for r in out if str(r.get("id")) == want]
    if to:
        # 与 `list_all` 同一口径：问"给 G 的手稿"时，广播给所有人的那些也算
        # （收件人关心的是"我该看哪些"，不是"哪几份的收件人字段逐字等于我"）。
        want = str(to).upper()
        out = [r for r in out
               if str(r.get("to") or "").upper() == want
               or (want != ALL and str(r.get("to") or "").upper() == ALL)]
    if sender:
        out = [r for r in out if str(r.get("sender") or "") == str(sender)]
    if since:
        out = [r for r in out if str(r.get("created_at") or "") >= str(since)]
    if refs:
        needle = str(refs)
        out = [r for r in out if any(needle in str(x) for x in (r.get("refs") or []))]
    return out[-limit:], problems


def missing_fields(rec: Mapping[str, Any]) -> list[str]:
    """这一行缺了哪个必填字段（`draft/39` §C2：`to` / `summary` / `body` 缺一即不合格）。"""
    return [k for k in REQUIRED_FIELDS if not str(rec.get(k) or "").strip()]


def digest(root: str | Path, *, limit: int = 5) -> str:
    """给提示词用的一小段读数：最近几份交接手稿（编号 + 谁给谁 + 一句话）。"""
    got = list_all(root, limit=limit)
    if not got:
        return "（还没有交接手稿）"
    return "\n".join(
        f"- {r.get('id')} {r.get('sender')}→{r.get('to')}：{r.get('summary') or '(没有一句话)'}"
        for r in got)


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def selftest() -> int:
    """最小自检：编号从 0000 顺次、一行一份、读得回来、按收件人过滤、拒绝空手稿。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="manuscripts_selftest_"))
    checks: list[tuple[str, bool]] = []
    a = write(root, sender="D", recipient="F", summary="把猜想交给你", body="## 任务\n证明它。")
    b = write(root, sender="F", recipient="ALL", summary="进展汇报", body="卡在第 3 步。")
    checks.append(("第一份是 0000", a["id"] == "0000"))
    checks.append(("第二份是 0001", b["id"] == "0001"))
    checks.append(("一行一份（两行）", len(rows(root)) == 2))
    checks.append(("读得回来", (read(root, "0001") or {}).get("record", {}).get("sender") == "F"))
    checks.append(("按收件人过滤（G 也能收到广播的那份）",
                   [r["id"] for r in list_all(root, to="G")] == ["0001"]))
    checks.append(("广播收件人写法是 ALL", b["to"] == ALL))
    empty_ok = False
    try:
        write(root, sender="D", recipient="F", summary="空的", body="  ")
    except ValueError:
        empty_ok = True
    checks.append(("空正文被拒（零写入）", empty_ok))
    no_summary_ok = False
    try:
        write(root, sender="D", recipient="F", body="有正文但没有一句话")
    except ValueError:
        no_summary_ok = True
    checks.append(("没有 summary 被拒（它要进留言）", no_summary_ok))
    checks.append(("被拒的那两次一行都没多", len(rows(root)) == 2))
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())

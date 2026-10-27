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

收件人的绝对编码另占两格（2026-10-26，Q2「发 / 收两栏只显示角色名」）：
`to_task_id`（具体收件人 ⇒ 它的台账号）与 `to_task_ids`（`to=ALL` ⇒ 发信人此刻的
直接子代理编号）。`task_id` 那一格本来就是发信人的台账号。两格都是「有就带上」：
改前落的那一批行一个都没有，读侧照实写「旧账无号」，不许拿角色名拼一个编号出来
（拼出来的那个数字看起来像证据，其实是猜）。

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
#: 号身认"当前宽度或旧四位"（编号宽度在 `schema.ID_DIGITS` 一处定义；
#: 2026-10-14 由四位改六位，旧文件必须照样读得进来）。
NAME_RE = re.compile(rf"^({S.ID_OR_LEGACY_PATTERN})-([A-Za-z]+)to([A-Za-z]+)\.md$")
#: 一行的必填字段（缺一 ⇒ 这一行不是一份可溯源的交接）。
REQUIRED_FIELDS: tuple[str, ...] = ("to", "summary", "body")
#: 修订行的 `kind` 取值（`draft/53` §2.1「改」/ `draft/55` §3.1）：追加修订行、不改旧行。
#: 为什么要有这一格：`revises` 指回被订正的那一份，"这一行是新写还是订正"必须机读得出来
#: ——否则读账本的人会把"订正"读成"又交接了一次"（那正是 #1 的一半）。
KIND_REVISION = "revision"


def dir_of(root: str | Path) -> Path:
    return Path(root) / MANUSCRIPTS_DIR


def handoffs_path(root: str | Path) -> Path:
    return dir_of(root) / HANDOFFS_NAME


def ensure_dir(root: str | Path) -> Path:
    d = dir_of(root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def valid_recipient(token: str) -> bool:
    """收件人：八个角色、主控（`M`）或 `ALL`。

    主控必须在列（`draft/39` §6.4）：强制 `notify` 落地后，被召唤来的角色最常见的交接对象
    就是召唤它的主控；把 M 排除在外会让"给主控的交接"在写入期被拒 ——
    而那种拒在真机上的表现是"手稿写不进去"（看起来像模型不会用这个工具）。
    """
    return str(token) in set(S.ROLES) | {S.CONDUCTOR_ROLE, ALL}


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
    """盘上出现过的全部编号（账本行 + 旧文件，两处取并集 —— 任何一处漏读都不该导致撞号）。

    ## 为什么要按数值排序（2026-10-14，四位改六位这一笔抓出来的）

    原实现只收 `len(mid) == 4` 的行、再把它当字符串排序取 `ids[-1]`：
    宽度一改，"新写的号"整类被这个长度过滤挡在外面 ⇒ 扫描结果永远看不到刚写下的
    那一行，`next_id` 于是一直返回同一个号（实测：并发 8 个写者全部拿到 `000000`，
    8 份手稿撞在一个号上）。这是"按固定宽度写死的过滤 + 字符串序当数值序"两个形态
    叠在一起的结果，所以这里两条一起改：两种宽度都收、按 int 排序。
    """
    ids: set[str] = set()
    for rec in rows(root):
        mid = str(rec.get("id") or "")
        if mid.isdigit() and S.id_width(mid) in (S.ID_DIGITS, 4):
            ids.add(mid)
    for mid, _p, _got in _legacy_files(root):
        ids.add(mid)
    return sorted(ids, key=lambda x: (int(x) if x.isdigit() else -1, x))


def next_id(root: str | Path) -> str:
    """下一个编号：盘上最大号 +1（第一份是 `000000`）。不持锁时只用于「读」，写请走 `write`。"""
    ids = [i for i in _scan_ids(root) if i.isdigit()]
    nxt = (max(int(i) for i in ids) + 1) if ids else 0
    return S.format_id(nxt)


def _mid_forms(mid: Any) -> tuple[str, ...]:
    """一个手稿号的各种写法：当前宽度 + 旧四位（读侧兼容的唯一落点）。

    盘上同时存在六位（新写）与四位（历史文件）两种号，而调用方写的是
    `"7"` / `7` / `"000007"` 里的任意一种 ⇒ 查一次要和两种都比。
    """
    text = str(mid or "").strip()
    if not text.isdigit():
        return (text,)
    n = int(text)
    forms = [S.format_id(n), f"{n:04d}"]  # LEGACY：旧四位写法，只用于读侧兼容
    return tuple(dict.fromkeys(forms))


def row_of(root: str | Path, mid: str) -> dict[str, Any] | None:
    """按编号取一行（新格式优先；找不到再回退到旧文件；都没有 ⇒ `None`）。"""
    wants = _mid_forms(mid)
    if not wants or not wants[0]:
        return None
    rows_now = rows(root)
    for want in wants:
        for rec in rows_now:
            if str(rec.get("id") or "") == want:
                return rec
    d = dir_of(root)
    if d.is_dir():
        for want in wants:
            for p in sorted(d.glob(f"{want}-*.md")):
                got = parse_name(p)
                if got:
                    return _legacy_row(root, want, p, got)
    return None


def path_of(root: str | Path, mid: str) -> Path | None:
    """按编号找旧格式文件（新格式没有一文件一手稿这回事 ⇒ 找不到返回 `None`）。"""
    wants = [w for w in _mid_forms(mid) if w]
    if not wants:
        return None
    d = dir_of(root)
    if not d.is_dir():
        return None
    for want in wants:
        for p in sorted(d.glob(f"{want}-*.md")):
            return p
    return None


def _render_body(sender: str, recipient: str, summary: str, body: str, *,
                 refs: Iterable[str] = (), task_id: str = "", sid: str = "",
                 created_at: str = "", note: str = "") -> str:
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
    ]
    if str(note or "").strip():
        # 「这一行是怎么来的」（`draft/39` §6.4）：模型自己填的表 / 框架据派活派生 ——
        # 读账本的人要能分清这两者，否则"留痕"会看起来都是模型写的。
        head.append(f"- 附注：{str(note).strip()}")
    head.append("")
    return "\n".join(head) + "\n" + str(body or "").rstrip() + "\n"


#: 引用里 `前缀:编号` 的写法能指向的台账（`draft/39` §C4：手稿的引用面不止前序手稿）。
#:
#: ## 2026-10-14 真机读数：加了 `q` / `c` 两个前缀
#:
#: 一次真机跑里 M 派的活带着 `refs=["q:000000"]`（它要引自己派出去的那条研究问题），
#: 而这张表当时只有 `stmt/exp/lit/rel` ⇒ `ref_problem` 报「前缀不认识」。
#: 后果不是"M 被拦住了"（`refs` 立不住只记一条读数、不拒写），而是那一份手稿退回成
#: 「框架据派活派生」的那一行 —— 模型自己写的那份留痕静默地没了。
#:
#: 为什么加这两个是对的（而不是"放宽判据"）：`ref_problem` 对每一个前缀都要求那一行真的
#: 在对应台账里（下面逐条核过），所以加前缀只扩大"能引什么"，不放松"引的东西必须存在"。
#: `q`（`research_questions`）与 `c`（`conjectures`）是研究过程里最上游的两个对象，
#: 派活/交接里引它们是最自然的写法；把它们挡在外面，等于逼着模型去引一个次一级的对象。
OBJECT_REFS: dict[str, str] = {
    "stmt": "statements", "exp": "experiments", "lit": "literature", "rel": "relations",
    "q": "research_questions", "c": "conjectures",
}


def ref_problem(root: str | Path, ref: str) -> str:
    """这一条引用能不能立住（空串 = 可以）。

    两条合法写法（`draft/39` §C2）：

    - 四位手稿编号（`"0007"`）⇒ 必须在盘上存在（行或旧文件）；
    - `前缀:编号`（`stmt:0007` / `exp:0002` / `lit:0004` / `rel:0011` / `q:0000` / `c:0000`）
      ⇒ 必须在对应台账里存在。

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


def rows_for_task(root: str | Path, task_id: str, *, sender: str = "") -> list[dict[str, Any]]:
    """这一条任务（`tasks.task_id`）已经留下了哪些行（可按发件人过滤）。

    用途（`draft/39` §6.6 F1）：动作驱动的一趟结束时要由框架代写一份"我干完了、交给谁"，
    而循环驱动的一趟已经由该角色自己的 `notify` 写了 —— 两种形态都要留痕、不许写两份。
    判据就是"这一条任务号下已经有行了吗"。
    """
    want = str(task_id or "").strip()
    if not want:
        return []
    return [r for r in rows(root)
            if str(r.get("task_id") or "") == want
            and (not sender or str(r.get("sender") or "") == str(sender))]


def write(root: str | Path, *, sender: str, recipient: str, title: str = "", body: str,
          refs: Iterable[str] = (), summary: str = "", task_id: str = "",
          sid: str = "", note: str = "", revises: str = "",
          to_task_id: str = "", to_task_ids: Iterable[str] | None = None,
          timeout: float = 30.0) -> dict[str, Any]:
    """追加一份交接手稿，返回它的那一行（含 `id`）。

    拒绝（抛 `ValueError`，「零写入」）：发件人/收件人不是合法角色、没有一句话说明、
    正文为空。"空手稿"必须被拒：它是"我交接了"的假证据，而这一层存在的全部意义就是可溯源。

    `to_task_id` / `to_task_ids`（2026-10-26，Q2）：收件人的绝对编码，由调用方给
    （具体收件人 ⇒ 它的台账号；`to=ALL` ⇒ 发信人此刻的直接子代理编号列表）。为什么是
    调用方给而不是这里现算：这一层不知道名册，算出来只能是猜；而解析处
    （`agent_loop._do_handoff` → `_handoff_address`）手里本来就有那个实例的 `task_id`。
    "编号在写侧就落进行里"是这一条的全部要点 —— 读侧只做展示，不许自己拼。

    `refs` 不再拒写（D10，`draft/52:103`）：立不住的引用被记进 `ref_problems`
    并可由 :func:`ref_readings` 读出来（详见那里的说明）。形状仍然管：
    `refs` 必须是字符串数组（形状错 ⇒ 抛 `ValueError`）。

    `title` 是旧参数名：它现在与 `summary` 是同一件事（进留言的那一句话）。
    两者都给了就以 `summary` 为准，不给 `summary` 时把 `title` 当它 —— 旧调用点不用改。

    `note` 是"这一行是怎么来的"（模型自己填的表 / 框架据派活派生，见 `draft/39` §6.4）：
    它进正文头部，因为读账本的人要能分清这两种留痕。

    `revises`（`draft/53` §2.1）非空 ⇒ 这一行是一条修订行（`kind="revision"`，
    指回被订正的那一份编号）。两条纪律：

    - append-only：旧行一个字节都不改（订正靠追加，不靠改写 —— 溯源链要能复现
      "当时写的是什么、后来改成了什么"）；
    - 修订行自带自己的编号（编号空间是账本的行号），`revises` 是"我订正的是谁"。

    只给 `revises` 时旧的交接行逐字节不变（不多一个键）—— 这一格是给
    `revise(...)` 用的，不是给所有行加一个恒为空的字段。
    """
    sender = str(sender or "").strip()
    recipient = str(recipient or "").strip().upper()
    one_line = str(summary or "").strip() or str(title or "").strip()
    text_body = str(body or "").strip()
    if not valid_sender(sender):
        raise ValueError(f"发件人必须是 {sorted(set(S.ROLES) | {S.CONDUCTOR_ROLE})} 之一，收到 {sender!r}")
    if not valid_recipient(recipient):
        raise ValueError(f"收件人必须是 {sorted(set(S.ROLES) | {S.CONDUCTOR_ROLE, ALL})} 之一"
                         f"（给所有人写 {ALL}），收到 {recipient!r}")
    if not one_line:
        raise ValueError(
            "summary 不能为空（它就是留言里那一句 `[手稿 NNNN] <summary>`）—— "
            "没有这一句，收件人只看到一个编号，等于让他自己去翻"
        )
    if not text_body:
        raise ValueError("正文不能为空（空手稿是『我交接了』的假证据）")
    refs_list = [str(x).strip() for x in refs if str(x).strip()]
    # ---- D10（`draft/52:103` 逐字："改成『建议』（不动 `REQUIRED_FIELDS` 其它项）+ 一条读数"）
    #
    # 以前这里对每条 ref 调 `ref_problem`，悬空就拒写。真机读数（`draft/44` D10）：
    # `refs` 在 1542 行手稿里全空 —— 一条"要么填对、要么整份手稿写不进去"的判据，
    # 在真机上的效果不是"引用得更好"，而是"没人敢引用"（引用一错，交接本身丢了）。
    # 于是这条链上最该有的东西（溯源边）在账本里一个都没有。
    #
    # 新口径：记下来 + 读数可见，不拒写。形状仍然管（`refs` 必须是字符串数组），
    # 而"这一条引用立不立得住"从写入期硬拦降成写入期的如实标记：
    # 行里多一个 `ref_problems`（哪一条引用有什么问题），并由 `ref_readings` 汇总成读数。
    ref_problems: dict[str, str] = {}
    for ref in refs_list:
        why = ref_problem(root, ref)
        if why:
            ref_problems[ref] = why
    revises_id = ""
    if str(revises or "").strip():
        revises_id = _norm_mid(revises)
        if row_of(root, revises_id) is None:
            raise ValueError(
                f"要订正的手稿 {revises!r} 不在盘上 ⇒ 订正一条不存在的交接是凭空引用"
            )

    d = ensure_dir(root)
    lock = FileLock(str(d / LOCK_NAME), timeout=timeout)
    try:
        with lock:
            mid = next_id(root)
            created_at = _now_iso()
            full_body = _render_body(sender, recipient, one_line, text_body,
                                     refs=refs_list, task_id=task_id, sid=sid,
                                     created_at=created_at, note=note)
            blob = full_body.encode("utf-8")
            rec: dict[str, Any] = {
                "id": mid, "sender": sender, "to": recipient, "summary": one_line,
                "body": full_body, "refs": refs_list, "created_at": created_at,
                "task_id": task_id, "sid": sid, "note": str(note or ""),
                "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob),
                "path": f"{MANUSCRIPTS_DIR}/{HANDOFFS_NAME}#{mid}",
                "format": "jsonl",
            }
            if revises_id:
                # 只有修订行才多这两个键：旧的交接行逐字节不变（不许给所有行
                # 加一个恒为空的字段 —— 那会让 `rows()` 的每一次对拍都漂）。
                rec["revises"] = revises_id
                rec["kind"] = KIND_REVISION
            if ref_problems:
                # 同一条纪律：只有真的有问题时才多这一个键。
                rec["ref_problems"] = dict(ref_problems)
            # 收件人的绝对编码（Q2，2026-10-26）：两格分形状，谁也不顶替谁 ——
            # `to_task_id` 是"那一个实例"（字符串），`to_task_ids` 是"广播面"（列表）。
            # 混成一格之后「发给一个实例」与「发给一批实例」在读侧就分不开了。
            # 同一条"有就带上"的纪律：缺键 = 这一行没记下编号（改前的旧行、以及写的时候
            # 名册读不成的那一批），读侧照实写「旧账无号」，不拿角色名拼一个出来。
            to_code = str(to_task_id or "").strip()
            if to_code:
                rec["to_task_id"] = to_code
            if to_task_ids is not None:
                rec["to_task_ids"] = [str(x).strip() for x in to_task_ids if str(x).strip()]
            line = json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str)
            with handoffs_path(root).open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
            return rec
    except Timeout as exc:  # pragma: no cover - 只有并发极端场景才会撞上
        raise ValueError(f"取手稿编号锁超时（{timeout}s）：有另一个写者卡住了，稍后重试") from exc


def _norm_mid(mid: Any) -> str:
    """编号归一成当前宽度的写法（`"7"` / `7` / `"0007"` ⇒ `"000007"`；不是数字就原样返回）。

    只归一"写"这一侧（新写的号统一当前宽度）；"读"那一侧要认两种写法，
    走 `_mid_forms()`。宽度在 `schema.ID_DIGITS` 一处定义。
    """
    text = str(mid or "").strip()
    return S.format_id(int(text)) if text.isdigit() else text


def revise(root: str | Path, *, mid: str, title: str = "", summary: str = "", body: str,
           sender: str = "", recipient: str = "", refs: Iterable[str] = (),
           task_id: str = "", sid: str = "", note: str = "", reason: str = "",
           timeout: float = 30.0) -> dict[str, Any]:
    """订正一份手稿：追加一条修订行，旧行一个字节都不改（`draft/53` §2.1「改」）。

    为什么是追加而不是改写（`draft/39` §C1 的同一条理由）：手稿层存在的全部意义是
    "可溯源"。改写旧行会让"当时写的是什么"永久消失，而订正本身恰恰是最需要
    留下证据的一件事 —— 读账本的人要能同时看到原文与订正版（`draft/55` §5.1 第 3 条：
    过程的原文与加工后必须并列留痕）。

    与 `write` 的关系：这是 `write` 的一层薄封装（`revises=<旧编号>`），
    所以"空手稿被拒 / 引用悬空被拒 / 编号在同一把锁里分配"这些判据只有一份实现。

    参数
    ----
    mid : 要订正的手稿编号（不在盘上 ⇒ 抛 `ValueError`，零写入）。
    sender / recipient : 不给就沿用旧行（订正的是同一份交接，收件人没有变）。
    summary / body : 至少给一个（都不给 ⇒ 抛 `ValueError`：一条什么都没改的
        "修订行"只会让账本多一行噪声）。
    reason : 为什么订正（进正文头部与 `note`，这是复核时唯一能回答"为什么改"的地方）。
    """
    old = row_of(root, mid)
    if old is None:
        raise ValueError(f"要订正的手稿 {mid!r} 不在盘上 ⇒ 订正一条不存在的交接是凭空引用")
    new_summary = str(summary or "").strip()
    new_body = str(body or "").strip()
    if not new_summary and not new_body:
        raise ValueError("修订行必须至少改一处（summary 或 body 给一个）—— "
                         "什么都没改的『修订』只会让账本多一行噪声")
    old_id = _norm_mid(mid)
    why = str(reason or "").strip()
    note_text = f"手稿订正：订正 {old_id}" + (f"（为什么：{why}）" if why else "")
    if str(note or "").strip():
        note_text = f"{note_text}；{str(note).strip()}"
    # 收件人的绝对编码跟着那一条交接走（订正的是同一份交接，收件人没有变）：
    # 旧行有就原样带过来，旧行没有就不许凭空补一个 —— 补一个看起来像编号的东西，
    # 比留着「旧账无号」更糟（那是把猜的结果写成了证据）。
    codes = {name: old[name] for name in ("to_task_id", "to_task_ids") if name in old}
    return write(
        root,
        sender=str(sender or "").strip() or str(old.get("sender") or ""),
        recipient=str(recipient or "").strip() or str(old.get("to") or ""),
        summary=new_summary or str(old.get("summary") or ""),
        body=new_body or str(old.get("body") or ""),
        refs=list(refs) or list(old.get("refs") or []),
        task_id=str(task_id or "").strip() or str(old.get("task_id") or ""),
        sid=str(sid or "").strip() or str(old.get("sid") or ""),
        note=note_text,
        revises=old_id,
        timeout=timeout,
        **codes,
    )


def revisions_of(root: str | Path, mid: str) -> list[dict[str, Any]]:
    """这一份手稿被订正过几次（按行序；空列表 = 一次都没有）。

    它是 `revise` 的读侧："没订正过"与"订正过但读不出来"必须分得开 ——
    后者是坏行，由 `read_rows` 报出来，绝不在这里折成空列表。
    """
    want = _norm_mid(mid)
    if not want:
        return []
    return [r for r in rows(root) if str(r.get("revises") or "") == want]


def ref_readings(root: str | Path) -> dict[str, Any]:
    """D10 的那条读数：账本里哪些行的 `refs` 立不住、为什么（只读，不改任何行）。

    为什么"改建议"之后必须有一条读数（`draft/52:103`）：判据从"拒写"降成"标记"之后，
    若没有读数，"引用写错了"就变成没有任何地方会说话的一件事 —— 那正是
    本项目最忌的形态（把"检查"换成"沉默"）。这条读数把它重新变成看得见的事实：

    - `rows_with_refs`：账本里有引用的行数（D10 之前这一栏在真机上恒为 0 —— 1542 行全空）；
    - `problems`：`[{id, sender, to, ref, why}]` 逐条列出立不住的那些引用；
    - `checked` / `reason`：读数本身有没有做成（坏行由 `read_rows` 报，不折成"干净"）。
    """
    all_rows, bad_lines = read_rows(root)
    problems: list[dict[str, Any]] = []
    with_refs = 0
    for rec in all_rows:
        refs = [str(x).strip() for x in (rec.get("refs") or []) if str(x).strip()]
        if refs:
            with_refs += 1
        # 写入期记下的那一条（`ref_problems`）优先——它是当时的判定；
        # 之后再复算一次，是为了抓住"写的时候在、现在被删了"这种漂移。
        recorded = rec.get("ref_problems") if isinstance(rec.get("ref_problems"), Mapping) else {}
        for ref in refs:
            why = str(recorded.get(ref) or "") or ref_problem(root, ref)
            if why:
                problems.append({"id": str(rec.get("id") or ""),
                                 "sender": str(rec.get("sender") or ""),
                                 "to": str(rec.get("to") or ""), "ref": ref, "why": why})
    return {"checked": True, "reason": "" if not bad_lines else "；".join(bad_lines),
            "rows": len(all_rows), "rows_with_refs": with_refs,
            "problems": problems, "count": len(problems)}


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
        wants = set(_mid_forms(mid))
        out = [r for r in out if str(r.get("id")) in wants]
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

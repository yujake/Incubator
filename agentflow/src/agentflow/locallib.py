"""把本地一个目录里的 PDF 灌进项目库（`literature` + `library/`），按内容 hash 幂等。

## 为什么需要这个模块

框架原来的"文献来源"是网络 provider（`openalex` / `crossref`），而用户手里常常
已经有整柜 PDF（本仓库的测试源就是 `D:\\books` 那七本书）。没有这一层，
那些书只能靠人手写成 seed 清单（`test/test2/paper_seed.py` 走的就是人工清单那条路），
"本地已有文献"这件事在框架里没有位置。

本模块把"目录里的 PDF"变成可追溯的 literature 行，并且只做这一件事：
登记。抽取是 B 的职责（`agent_b.run_once` 认 `processed=False` 的行），
本模块不抽、不猜、不写概念 —— 那两件事分开，"没有文本层"与"抽取器什么都没抽到"
才不会折成同一个结果。

## 三条纪律的落点

1. 来源不许说假话：这些书不是 A 检索来的。所以照
   `paper_seed.ingest_paper` 的先例，登记一条
   `submitted_by="human"` / `outcome="ok"` 的 `search_requests` 行，
   再让 `literature.source_request_ids` 指回它。把本地文件伪装成检索结果，
   等于让"这篇文献从哪来"这条链说假话。
2. 幂等靠内容 hash，不靠文件名：同一本书改名/换目录后重灌，仍然只能有一行。
   判据读的是 `download.sha256`（我们自己算的）而不是文件 mtime 或大小。
3. 读不了就如实说读不了：抽取失败（没有文本层、损坏、加密）的那一本单独记一档
   `unreadable`，不给它编一行"登记成功、内容为空"的记录。

## 边界

- 只认本机文件系统上的目录，不下载、不联网。
- 不做 OCR：扫描版 PDF 会以"没有文本层"登记，`processed` 留给 B 去决定怎么处置。
- `--limit` 是给真实跑用的预算闸门（一本书可能几百页、几十万字符），
  不是"只处理前 N 本"的语义糖：超出的书不会被登记，清单里逐本写明为什么。
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import interactions as I
from . import schema as S
from .extract import extract_text
from .store import Store

__all__ = [
    "BookPlan",
    "IngestReport",
    "LocalHit",
    "excerpt_for",
    "ingest_directory",
    "list_books",
    "local_fetch_fn",
    "search_fn_for_store",
    "selftest",
    "sha256_file",
]

#: 单本默认上限字节数（超过就跳过并说明），避免一次跑把 17 MB 的书整本喂进模型。
DEFAULT_MAX_BYTES = 24 * 1024 * 1024

_SAFE_RE = re.compile(r"[^0-9A-Za-z._\u4e00-\u9fff-]+")


def sha256_file(path: Path) -> str:
    """整文件 sha256（分块读，别把 17 MB 一次读进内存）。"""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_name(path: Path) -> str:
    """把源文件名清洗成 library/ 下安全的相对名（保留扩展名）。"""
    stem = _SAFE_RE.sub("_", path.stem).strip("_") or "book"
    return f"{stem}{path.suffix.lower()}"


def list_books(root: Path | str, *, pattern: str = "*.pdf") -> list[Path]:
    """列出目录下的候选文件（排序后返回，保证每次跑的次序一样）。"""
    base = Path(root)
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob(pattern) if p.is_file())


@dataclass
class BookPlan:
    """一本书的登记结局（无论是真登记还是被跳过，都要有一行）。"""

    source: str
    library_name: str
    bytes: int
    sha256: str
    status: str
    lit_id: str = ""
    request_id: str = ""
    pages: int = 0
    has_text_layer: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """落进项目卡的形状（这本书的登记结局，含跳过理由）。"""
        return {
            "source": self.source,
            "library_name": self.library_name,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "status": self.status,
            "lit_id": self.lit_id,
            "request_id": self.request_id,
            "pages": self.pages,
            "has_text_layer": self.has_text_layer,
            "note": self.note,
        }


@dataclass
class IngestReport:
    """一次目录登记的读数。`counts` 的键是固定集合（零值也在场）。"""

    root: str
    books: list[BookPlan] = field(default_factory=list)
    dry_run: bool = False
    limit: int | None = None

    #: 固定四档，零值在场：把"没扫到"与"扫到了但跳过"分开。
    STATUSES: tuple[str, ...] = ("ingested", "already_present", "skipped_limit",
                                 "skipped_too_large", "unreadable")

    def counts(self) -> dict[str, int]:
        """按固定四档数一遍（零值也在场："没扫到"与"扫到了但跳过"分得开）。"""
        out = {k: 0 for k in self.STATUSES}
        for b in self.books:
            out[b.status] = out.get(b.status, 0) + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        """一次目录登记的读数（清单 + 逐档计数 + 文本层与页数小计）。"""
        return {
            "root": self.root,
            "dry_run": self.dry_run,
            "limit": self.limit,
            "counts": self.counts(),
            "books": [b.to_dict() for b in self.books],
            "text_layer_ok": sum(1 for b in self.books if b.has_text_layer),
            "pages_total": sum(b.pages for b in self.books),
        }


def _known_hashes(store: Store) -> dict[str, str]:
    """已登记的 `sha256 -> lit_id`（幂等的唯一依据）。"""
    out: dict[str, str] = {}
    for row in store.rows("literature"):
        sha = str((row.get("download") or {}).get("sha256") or "")
        if sha:
            out[sha] = str(row.get("lit_id") or "")
    return out


def ingest_directory(
    store: Store,
    root: Path | str,
    *,
    limit: int | None = None,
    pattern: str = "*.pdf",
    max_bytes: int = DEFAULT_MAX_BYTES,
    dry_run: bool = False,
    note: str = "",
    actor: str = "human",
    submitted_by: str = "human",
    origin_note: str = "",
) -> IngestReport:
    """把一个目录里的 PDF 登记进 `store`。已登记过的（同 sha256）不重复登记。

    `dry_run=True` 时只算 hash 与清单，不写文件、不进事务。

    ## 为什么 provenance 要三个参数（`draft/28` §191）

    原先这里把请求行写死成 `submitted_by="human"` + 正文里那句"人直接提供的一本本地藏书"。
    人调用它时那是事实；A 调用它时那就是假 provenance —— 而"这篇文献从哪来"
    正是这条链存在的理由。于是三个参数分开：

    - `actor`：写这次事务的角色（`agent-A` / `human`）；
    - `submitted_by`：请求方。A 不在 `SUBMITTER_DEFAULT_PRIORITY` 里（A 不提交检索需求），
      所以 A 登记时如实填 `unknown`（= "没有登记在册的请求方"），而不是借 `human`；
    - `origin_note`：正文里那句"谁提供的"（缺省仍是"人直接提供"）。
    """
    store.init()
    report = IngestReport(root=str(root), dry_run=dry_run, limit=limit)
    known = _known_hashes(store)
    lib = Path(store.library)
    who = origin_note or "人直接提供"

    for idx, src in enumerate(list_books(root, pattern=pattern)):
        size = src.stat().st_size
        name = _safe_name(src)
        sha = sha256_file(src)
        plan = BookPlan(source=str(src), library_name=name, bytes=size, sha256=sha,
                        status="ingested")

        if limit is not None and idx >= limit:
            plan.status = "skipped_limit"
            plan.note = f"超过本次 --limit={limit}（第 {idx + 1} 本），本次不登记"
            report.books.append(plan)
            continue
        if size > max_bytes:
            plan.status = "skipped_too_large"
            plan.note = f"{size} 字节 > 上限 {max_bytes} 字节；要用就显式调大 `max_bytes`"
            report.books.append(plan)
            continue
        if sha in known:
            plan.status = "already_present"
            plan.lit_id = known[sha]
            plan.note = "同一内容 hash 已在库里（热启动的判据是内容，不是文件名）"
            report.books.append(plan)
            continue

        # 先解析一次正文：没有文本层的书仍然登记，但要把这件事写在行上，
        # 而不是等 B 去发现（B 发现时它记的是 last_mine_error，那是运行记录）。
        try:
            doc = extract_text(str(src))
        except Exception as exc:  # noqa: BLE001 —— 读不了就是读不了，如实记一档
            plan.status = "unreadable"
            plan.note = f"{type(exc).__name__}: {exc}"
            report.books.append(plan)
            continue

        plan.pages = len(getattr(doc, "pages", []) or [])
        plan.has_text_layer = bool(getattr(doc, "has_text_layer", False))
        if plan.pages == 0 or not str(getattr(doc, "text", "")).strip():
            plan.note = "登记成功，但这一本没有可引用的正文（无文本层或全空页）"

        if dry_run:
            report.books.append(plan)
            continue

        lib.mkdir(parents=True, exist_ok=True)
        dest = lib / name
        if not dest.exists() or sha256_file(dest) != sha:
            shutil.copy2(src, dest)

        with store.tx("search_requests", "literature", "counters",
                      actor=actor, note=note or "ingest local books") as tx:
            lit_id = tx.alloc_id("lit")
            req_id = I.next_prefixed_id(tx.rows("search_requests"), "request_id", "r")
            title = src.stem.replace("_", " ").strip() or name
            tx.upsert(
                "search_requests",
                S.SearchRequest(
                    request_id=req_id,
                    timestamp=S.now_iso(),
                    topic=title,
                    mode="precise",
                    content_description=(
                        f"{who}的一本本地藏书（源文件 {src.name}，{size} 字节，"
                        f"sha256 {sha[:12]}…）。不是 A 检索来的 —— 这一点必须如实记录，"
                        "否则『这篇文献从哪来』这条链会说假话。"
                    ),
                    done=True,
                    submitted_by=submitted_by,
                    priority="high",
                    outcome="ok",
                    result_lit_ids=[lit_id],
                    submit_note=note or f"本地文献目录登记（locallib.ingest_directory，actor={actor}）",
                ).to_dict(),
            )
            tx.upsert(
                "literature",
                S.Literature(
                    lit_id=lit_id,
                    title=title,
                    type="M",
                    summary=f"本地书架上的专著/教材（{name}，{plan.pages} 页）",
                    path=name,
                    processed=False,
                    source_request_ids=[req_id],
                    added_at=S.now_iso(),
                    download={
                        "status": "ok",
                        "note": "本地文件（不是网络下载）；内容类型按扩展名与解析结果判定",
                        "pages": plan.pages,
                        "has_text_layer": plan.has_text_layer,
                        "bytes": size,
                        "sha256": sha,
                        "source_path": str(src),
                    },
                ).to_dict(),
            )
        plan.lit_id = lit_id
        plan.request_id = req_id
        known[sha] = lit_id
        report.books.append(plan)

    return report


# --------------------------------------------------------------------------- #
# 检索接缝：把已登记的本地藏书当"一个文献源"喂给 `run_topic`
# --------------------------------------------------------------------------- #


#: 检索用的停用词。必须滤掉：`the` / `and` 这类词每一页都有，把它们算进
#: "命中多少主题词"等于给所有页加同一个常数，而目录页恰恰靠这种噪声词多命中一个
#: 而胜出（实测 2026-09-28：题目 `the argument principle and the residue theorem`
#: 下，`complex.pdf` 的目录页命中 6 个词、真正的正文页命中 5 个 ⇒ 目录页得分最高，
#: 于是交给模型的材料是"Chapter 1. Basic calculus…"，模型只能如实回答"材料中没有"）。
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "these", "those", "are", "was",
    "were", "into", "over", "under", "between", "about", "which", "where", "when", "then",
    "than", "there", "here", "have", "has", "had", "not", "but", "all", "any", "can", "may",
    "its", "his", "her", "their", "our", "you", "your", "one", "two", "also", "such", "some",
    "more", "most", "other", "only", "same", "each", "both", "very", "well", "will", "would",
    "should", "could", "must", "does", "did", "doing", "been", "being", "because", "while",
    "however", "therefore", "thus", "hence", "example", "examples", "chapter", "section",
})


def _tokens(query: str) -> list[str]:
    """粗分词：ASCII 词（长度 >= 3 且不在停用词表里）+ 中文双字组。

    刻意不做真正的分词：这里的用途只是"在同一本书里挑一页最相关的"，挑错了
    后果是"引文要更仔细地找"，而不是"结论错了"。反过来，引入一个分词依赖会让
    "本地源能不能用"取决于一个与本功能无关的包。

    停用词表见 `_STOPWORDS` 的说明 —— 它不是洁癖，是实证修出来的：
    目录页靠 `the`/`and` 多命中一个词而胜出过。
    """
    q = query.lower()
    out = [t for t in re.findall(r"[a-z0-9]{3,}", q) if t not in _STOPWORDS]
    cjk = re.findall(r"[\u4e00-\u9fff]+", q)
    for run in cjk:
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            out.append(run)
    return out


#: 导航页（目录 / 索引 / 参考文献）的判据阈值：非空行里以数字结尾的比例。
#: 目录与索引的行末多半是页码，散文页几乎没有这种行。实测（complex.pdf 第 2 页目录）
#: 该比例远高于正文页；用 0.35 当阈值留了余量，并把"命中 Contents/Index"也算进去。
_NAV_PENALTY = 0.15

#: 页级打分的主键单位：命中多少个不同主题词，权重远大于稀有度之和。
#: 为什么必须这样（实测，2026-09-28）：原来只用 `Σ 1/df(t)`，于是
#:   命中一个稀有词（df=4 ⇒ 0.25）的页，压过命中三个常见词（0.043+0.011+…）的页。
#: 代价：题目 `cosets and quotient groups` 下选中的页只命中 `cosets` 一个词，
#: 而书里明明有同时讲 quotient 与 groups 的页。
#: 离线原型（`temp/_score_prototype.py`，8 题乘以 7 本书）：
#:   现状 ⇒ 8 题里 1 题"最强来源命中不到 2 个主题词"；覆盖率优先 ⇒ 0 题；
#:   另一条折中（Σweight 乘以 (1+命中数)）仍是 1 题（没用，故不采用）。
#: 取值 1000 只是"远大于任何可能的 Σweight"（Σweight 不超过词数），读作主键。
_COVERAGE_FIRST = 1000.0


def _looks_like_navigation(page: str) -> bool:
    """这一页像不像目录/索引（而不是正文）。

    为什么要单独判它：这类页天生包含全书的主题词，所以在"命中多少主题词"这个
    打分下几乎必然胜出，而它恰恰是最没有内容的一页。光靠"命中数"永远治不了它。
    """
    lines = [ln.strip() for ln in page.split("\n") if ln.strip()]
    if not lines:
        return False
    ending_with_digit = sum(1 for ln in lines if ln[-1].isdigit())
    head = page[:400].lower()
    named = any(k in head for k in ("contents", "index", "bibliography", "references"))
    return named or (ending_with_digit / len(lines)) >= 0.35


def _window_on_tokens(page: str, toks: list[str], weight: dict[str, float],
                      max_chars: int) -> str:
    """在页内挑一个长度 <= `max_chars` 的窗口：让窗内的不同主题词尽量多、且尽量稀有。

    为什么不是"从页首截 max_chars 个字符"（第一版就是这么写的，实测踩了）：
    主题词常常出现在页的中后段，从页首截会把命中句整段切掉 —— 于是交给模型的
    材料里根本没有答案，模型只能如实回答"材料中没有"，而这一跑看上去"跑通了"。
    本函数反过来：先定位命中点，再围着它取窗口，最后吸附到句子边界。

    窗口内按"不同词的权重和"打分（`weight` 是稀有度的倒数）：一个只在几页出现的词
    （比如 duality）比满篇都是的词（比如 convex）更能说明"这一页在讲什么"。
    """
    low = page.lower()
    occurrences: list[tuple[int, str]] = []
    for tok in sorted(set(toks)):
        start = 0
        while True:
            pos = low.find(tok, start)
            if pos < 0:
                break
            occurrences.append((pos, tok))
            start = pos + 1
    if not occurrences:
        return page[:max_chars].strip()
    occurrences.sort()

    best_score, best_lo, best_hi = -1.0, occurrences[0][0], occurrences[0][0]
    for a in range(len(occurrences)):
        seen: set[str] = set()
        for b in range(a, len(occurrences)):
            if occurrences[b][0] - occurrences[a][0] > max_chars:
                break
            seen.add(occurrences[b][1])
            score = sum(weight.get(t, 0.0) for t in seen)
            # 并列时取更早的那个窗口（结果与页序无关、可复现）。
            if score > best_score:
                best_score, best_lo, best_hi = score, occurrences[a][0], occurrences[b][0]

    start = best_lo
    # 向前吸附到最近的句首（最多回退 160 字符，免得窗口被一句超长话吃掉）。
    floor = max(0, best_lo - 160)
    snapped = False
    for mark in (". ", "。", "\n", "．", "; "):
        pos = low.rfind(mark, floor, best_lo)
        if pos >= 0 and pos + len(mark) > start:
            start = pos + len(mark)
            snapped = True
    if not snapped and start > 0:
        # 页首附近没有上一条句界时，退回行首；再不行就退到最近的一个空白，
        # 至少别把第一个词切成半截（真跑里出现过窗口以 "group is a set…" 开头，
        # 前面的 "A " 被切掉 —— 那句话就不再是原文里完整的一句）。
        line_start = low.rfind("\n", floor, best_lo)
        if line_start >= 0:
            start = line_start + 1
        elif best_lo <= 160:
            start = 0
        else:
            space = low.rfind(" ", floor, best_lo)
            start = space + 1 if space >= 0 else start
    text = page[start:start + max_chars].strip()
    if not text:
        return page[best_lo:best_lo + max_chars].strip()
    _ = best_hi
    return text


def page_scores(pages: list[str], query: str) -> list[float]:
    """每一页与 `query` 的相关度（主键=命中多少个不同主题词，次键=稀有度加权和）。

    ## 为什么把它单独抽出来（`draft/28` §187 真机读数逼出来的）

    原先这套打分只活在 `excerpt_for` 内部，于是任何"要按相关度给「书」排序"的调用方
    都拿不到分数 —— 我第一版 `search.local` 就因此拿"摘录长度"当排序键，而
    长度在窗口取满时恒等于 `max_chars`：排序退化成按 `lit_id` 字母序，
    真机读数里"martingale central limit theorem"的第三名是一篇讲
    「伊朗城市」的论文（它命中的是 `central`）。判据只有一份实现才不会这样脱节。

    导航页（目录/索引）按住 `_NAV_PENALTY` 压分，理由见 `_looks_like_navigation`。
    """
    toks = _tokens(query)
    if not toks or not pages:
        return [0.0 for _ in pages]
    df: dict[str, int] = {t: 0 for t in set(toks)}
    for page in pages:
        low = page.lower()
        for t in df:
            if t in low:
                df[t] += 1
    weight = {t: 1.0 / max(1, n) for t, n in df.items()}

    out: list[float] = []
    for page in pages:
        low = page.lower()
        present = {t for t in weight if t in low}
        # 主键是覆盖率（这一页到底谈了几个主题词），稀有度只当次键。
        # 只用 `Σ 1/df(t)` 会让"命中一个稀有词"的页压过"命中三个常见词"的页 ——
        # 实测代价见 `_COVERAGE_FIRST` 的说明（cosets 那道题就是这么选错的）。
        score = len(present) * _COVERAGE_FIRST + sum(weight[t] for t in present)
        if score > 0 and _looks_like_navigation(page):
            score *= _NAV_PENALTY
        out.append(score)
    return out


def excerpt_for(pages: list[str], query: str, *, max_chars: int = 1200) -> tuple[int, str]:
    """挑出与 `query` 最相关的一页并截一段。返回 `(页码 1-based, 摘录)`。

    ## 为什么是"整页里截一段"而不是"拼几句最像的话"

    `evidence.materials_block` 只把 `abstract` 塞进 prompt（默认截到 1200 字符），
    而 prompt 要求模型"从上面摘要里逐字复制"引文。所以这段文本必须满足两件事：
    它是原文的连续子串（模型抄得下来），且它来自一页（页码才说得出出处）。
    把不连续的高分句子拼起来会让"逐字复制"变成"逐字拼接"—— 而框架的回验
    只认前者，结果是每一条都落 `not_found`，看上去像模型在编，其实是材料被拼过。

    ## 排序口径（2026-09-28 真跑后改的；打分本体已抽到 `page_scores`）

    第一版按"整页里主题词的原始出现次数"排序，真跑实测：主题
    `convex optimization duality and Lagrange multipliers` 选中的那一页讲的是
    "凸集的定义"（`convex` 满页都是），而 `duality` / `Lagrange` 一次都没进窗口 ——
    模型于是如实回答"材料中没有对偶的内容"。改成按不同主题词的稀有度加权和
    排序（在某页出现的词取"出现该词的页数"的倒数），稀有词才推得动排序。
    """
    toks = _tokens(query)
    if not toks:
        return (1, pages[0][:max_chars].strip()) if pages else (0, "")
    scores = page_scores(pages, query)
    best_idx = max(range(len(scores)), key=lambda i: (scores[i], -i))
    df: dict[str, int] = {t: 0 for t in set(toks)}
    for page in pages:
        low = page.lower()
        for t in df:
            if t in low:
                df[t] += 1
    weight = {t: 1.0 / max(1, n) for t, n in df.items()}
    return best_idx + 1, _window_on_tokens(pages[best_idx], toks, weight, max_chars)


@dataclass
class LocalHit:
    """一条本地来源（一本书），形状就是 `evidence._source_from_item` 认的字典。"""

    lit_id: str
    title: str
    page: int
    excerpt: str
    pdf_path: str
    bytes: int
    sha256: str

    def to_item(self, *, source_name: str = "localpdf") -> dict[str, Any]:
        """转成 `evidence._source_from_item` 认的条目（标题 / 来源 / DOI|URL 三样缺一不可）。"""
        return {
            "title": self.title,
            "summary": self.excerpt,
            "abstract": self.excerpt,
            "source": source_name,
            "provider": source_name,
            # `url` 与 `pdf_url` 都要给：`evidence._pdf_url_of` 对裸 `url` 只认
            # http(s) 且以 .pdf 结尾的那种，本地路径必须走 `pdf_url` 才不会被丢掉。
            "url": "file:///" + self.pdf_path.replace("\\", "/").lstrip("/"),
            "pdf_url": self.pdf_path,
            "year": None,
            # 出处信息随条目一起走，落进 evidence.json 的 provenance。
            "local": {
                "lit_id": self.lit_id,
                "page": self.page,
                "bytes": self.bytes,
                "sha256": self.sha256,
                "note": "本地藏书（由 locallib 登记并抽取正文）；不是网络检索来的",
            },
        }


def search_fn_for_store(store: Store, *, source_name: str = "localpdf",
                        max_chars: int = 1200, max_books: int | None = None,
                        extract_fn: Any = None) -> Any:
    """造一个 `run_topic(search_fn=...)` 认的检索函数：源 = 库里已登记的本地藏书。

    ## 形状（对照 `evidence.retrieve` 的接缝）

    `fn(topic, *, limit, timeout_sec) -> Sequence[dict]`，返回的字典交给
    `_source_from_item` 归一（要求 `title` + 来源名 + `doi|url`）。这里一次把
    每本书的正文抽出来、按主题挑一页截 1200 字符当 `abstract`。

    ## 为什么要缓存

    一本 400 页的书抽一次要几秒；一次 run 只调一次检索，但 `run_topic` 之后
    取全文时还要再读一遍（那是 `fetch_fn` 的事）。这里只缓存"检索用"的那一份
    逐页文本，键是 `lit_id` + 文件 sha256 —— 文件被换过就重新抽，不吃旧缓存。

    `timeout_sec` 收下但不用：本地磁盘读取没有超时语义；收下是为了签名兼容。
    把"我没有超时这件事"写在这里，而不是假装自己会超时。
    """
    cache: dict[str, tuple[str, list[str]]] = {}
    _extract = extract_fn or extract_text

    def _pages_of(row: dict) -> tuple[str, list[str]]:
        rel = str(row.get("path") or "")
        abs_path = store.library_path(rel)
        if abs_path is None or not Path(abs_path).is_file():
            return "", []
        sha = str((row.get("download") or {}).get("sha256") or "")
        key = f"{row.get('lit_id')}::{sha}"
        hit = cache.get(key)
        if hit is not None:
            return hit
        doc = _extract(str(abs_path))
        pages = [str(p) for p in (getattr(doc, "pages", []) or [])]
        cache[key] = (str(abs_path), pages)
        return cache[key]

    def _search(topic: str, *, limit: int = 5, timeout_sec: float = 30.0) -> list[dict]:
        wanted = max(1, int(limit))
        hits: list[tuple[int, LocalHit]] = []
        for row in store.rows("literature"):
            path_text, pages = _pages_of(row)
            if not pages:
                continue
            page, excerpt = excerpt_for(pages, topic, max_chars=max_chars)
            score = len(excerpt)
            hits.append((
                score,
                LocalHit(
                    lit_id=str(row.get("lit_id") or ""),
                    title=str(row.get("title") or ""),
                    page=page,
                    excerpt=excerpt,
                    pdf_path=path_text,
                    bytes=int((row.get("download") or {}).get("bytes") or 0),
                    sha256=str((row.get("download") or {}).get("sha256") or ""),
                ),
            ))
        if max_books is not None:
            hits = hits[: max(1, int(max_books))]
        hits.sort(key=lambda pair: pair[0], reverse=True)
        return [h.to_item(source_name=source_name) for _s, h in hits[:wanted]]

    return _search


def local_fetch_fn() -> Any:
    """造一个 `run_topic(fetch_fn=...)` 认的"下载器"：本地文件就地读，既不搬也不抄。

    ## 为什么这个函数必须存在（而不是不传 `fetch_fn`）

    不传时 `acquire_fulltext` 用默认的网络下载器去打 `pdf_url` —— 本地路径打不通，
    全文级回验就永远到不了，所有引文只能在 1200 字符的摘要窗口里比对。

    ## 为什么就地读、不 copy 进 `dest_dir`

    这条路径只读用户的书架。`evidence._acquire_one` 自己会去 `Path(path).stat()`
    与算 sha256，它要的是一个"文件在哪"的答案，不是一份副本。副本会让
    "引文回验比的是不是原书"多出一个中间环节（副本被换掉时看不出来）。
    代价写在产物里：`fulltext.path` 会指向库里的那份（`library/<name>.pdf`），
    它在工作区内，所以仍然可复核。

    `kind` 恒为 `None`：这不是一次下载，没有"限流/被墙"这类档可报。
    """
    def _fetch(url: str, dest_dir: str, filename_hint: str = "") -> Any:
        from .fetch import FetchResult

        path = Path(str(url))
        if not path.is_file():
            return FetchResult(ok=False, path=None, error=f"本地文件不在盘上：{path}",
                               kind="network_error")
        size = path.stat().st_size
        return FetchResult(ok=True, path=str(path), bytes=size,
                           sha256=sha256_file(path), error=None, kind=None)

    return _fetch


def memo_extract_fn(extract_fn: Any = None) -> Any:
    """按 `(路径, 大小, mtime_ns)` 记忆化的抽取器，给检索与全文两条路共用同一份文本。

    ## 为什么要有它（不只是为了快）

    `fulltext=True` 那一条路上，同一本书会被抽两次：一次是我这里为挑摘录而抽，
    一次是 `evidence._acquire_one` 为逐字回验而抽。两次抽出来的文本必须一样，
    否则"给模型看的材料"与"回验时比对的文本"不是同一份 —— 而那种不一致的表现是
    "有些引文能过、有些过不了"，读起来像模型在编，实际是装置里有两份文本。
    `extract_text` 的后端回退链（fitz → pdfminer → PyPDF2）在不同调用上
    原则上可能落到不同后端，所以这里把它钉成同一份对象。

    ## 记忆键是 `(路径, 大小, mtime_ns)` 而不是内容 hash

    算内容 hash 要整读一遍文件，而这里的目的只是"同一次运行里别抽两遍"。
    文件被换掉时大小/时间戳会变，缓存自然失效；要说边界，就是
    "同一毫秒内被换成同样大小的另一个文件"会读到旧文本 —— 那种情况本模块管不了，
    但产出的 `fulltext.sha256` 是 `evidence` 自己从盘上算的，所以证据本身不会说谎。
    """
    cache: dict[tuple[str, int, int], Any] = {}
    _extract = extract_fn or extract_text

    def _memo(path: str) -> Any:
        p = Path(path)
        try:
            st = p.stat()
            key = (str(p), int(st.st_size), int(st.st_mtime_ns))
        except OSError:
            return _extract(path)
        if key not in cache:
            cache[key] = _extract(path)
        return cache[key]

    return _memo


# --------------------------------------------------------------------------- #
# 自检：`python -m agentflow.locallib`（离线；本机临时目录里造一本一页的 PDF）
# --------------------------------------------------------------------------- #


def _make_probe_pdf(path: Path, text: str) -> bool:
    """用 fitz 造一页有文本层的 PDF。返回是否成功（缺 fitz 就返回 False）。"""
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 —— 重依赖，缺了就如实说没查成
        return False
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return True


def selftest() -> int:
    """六条：登记 / 幂等 / 无文本层分档 / 读不了分档 / limit 闸门 / dry_run 不写。"""
    import tempfile

    print("=" * 72)
    print("locallib 自检（离线；PDF 在临时目录里现造）")
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="locallib-selftest-") as td:
        root = Path(td) / "books"
        root.mkdir()
        ok = _make_probe_pdf(root / "甲书.pdf", "A group is a set with an operation.")
        (root / "坏书.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
        store = Store(Path(td) / "ws")

        if not ok:
            print("[?] 本机没有可用的 fitz ⇒ 造不出带文本层的 PDF，本自检判 unknown（不是 pass）")
            print("=" * 72)
            return 2

        rep = ingest_directory(store, root)
        print(f"[1] 首次登记：counts={rep.counts()} pages_total={rep.to_dict()['pages_total']}")
        if rep.counts()["ingested"] != 1 or rep.counts()["unreadable"] != 1:
            problems.append(f"首次登记的分档不对：{rep.counts()}")

        rep2 = ingest_directory(store, root)
        print(f"[2] 再登记一次（幂等）：counts={rep2.counts()}")
        if rep2.counts()["ingested"] != 0 or rep2.counts()["already_present"] != 1:
            problems.append(f"幂等失败：第二次仍然登记了 {rep2.counts()}")

        rows = store.rows("literature")
        print(f"[3] literature 行数={len(rows)}（应当是 1）")
        if len(rows) != 1:
            problems.append(f"literature 行数 {len(rows)} != 1")

        rep3 = ingest_directory(store, root, limit=0)
        print(f"[4] limit=0：counts={rep3.counts()}")
        if rep3.counts()["skipped_limit"] != 2:
            problems.append(f"limit 闸门没有拦住：{rep3.counts()}")

        # dry_run 的判据分两半：对新工作区要如实预告"会登记哪几本"，
        # 对已登记过的工作区要如实说"这本已经在库里"，且一个字节都不写。
        fresh = Store(Path(td) / "ws-dry")
        rep4 = ingest_directory(fresh, root, dry_run=True)
        print(f"[5] dry_run（新工作区）：counts={rep4.counts()} 行数={len(fresh.rows('literature'))}")
        if rep4.counts()["ingested"] != 1 or fresh.rows("literature"):
            problems.append(f"dry_run 应当预告 1 本会登记且不写任何行：{rep4.counts()}")

        rep5 = ingest_directory(store, root, dry_run=True)
        print(f"[5b] dry_run（已登记过）：counts={rep5.counts()} 行数={len(store.rows('literature'))}")
        if rep5.counts()["already_present"] != 1 or len(store.rows("literature")) != 1:
            problems.append(f"dry_run 对已登记内容应当报 already_present：{rep5.counts()}")

        row = rows[0]
        dl = row.get("download") or {}
        print(f"[6] 行的追溯字段：type={row['type']} sha256={(dl.get('sha256') or '')[:12]}… "
              f"source_request_ids={row.get('source_request_ids')}")
        if not dl.get("sha256") or not row.get("source_request_ids"):
            problems.append("登记行缺 sha256 或来源请求链")
        src_req = store.rows("search_requests")
        print(f"[6b] 来源请求：{[(r['request_id'], r['submitted_by'], r['outcome']) for r in src_req]}")
        if len(src_req) != 1 or src_req[0]["submitted_by"] != "human":
            problems.append("来源请求不是一条 human 提交的记录（本地文件不许伪装成检索结果）")

        # 检索接缝：摘录必须是原文的连续子串（模型才能逐字抄），页码必须在范围内；
        # 且稀有词要能推动选页与选窗口 —— 这一条是 2026-09-28 真跑踩出来的：
        # 只按出现次数排序时，满篇都是的 common 词把只在第 3 页出现的 rare 词压住了。
        pages = ["A group is a set with an operation.\nSecond line.", "Another page about rings."]
        page, exc = excerpt_for(pages, "group operation")
        print(f"[7] excerpt_for（同页命中）：page={page} 摘录={exc[:48]!r}…")
        if page != 1 or exc not in pages[0]:
            problems.append(f"摘录不是第 1 页的连续子串：page={page} exc={exc[:60]!r}")

        long_pages = [
            ("common " * 300) + "tail of page one.",
            "middle page without the rare term.",
            ("filler " * 200) + "the rare term appears here: zeta-function." + ("more " * 200),
        ]
        page2, exc2 = excerpt_for(long_pages, "common zeta-function")
        print(f"[7b] 稀有词应当把窗口拉到第 3 页：page={page2} 含稀有词="
              f"{'zeta-function' in exc2} 长度={len(exc2)}")
        if page2 != 3 or "zeta-function" not in exc2:
            problems.append(f"稀有词没有推动选页/选窗口：page={page2} exc={exc2[:60]!r}")
        if len(exc2) > 1200:
            problems.append(f"窗口超过 max_chars：{len(exc2)}")

        fn = search_fn_for_store(store)
        items = fn("group operation", limit=5, timeout_sec=5.0)
        print(f"[8] 检索接缝：{len(items)} 条；键={sorted(items[0]) if items else []}")
        if len(items) != 1 or not str(items[0].get("abstract") or "").strip():
            problems.append(f"检索接缝没给出非空条目：{items}")
        else:
            # 真正的判据不是"我看它像"，而是"证据层的归一函数收不收它"——
            # `_source_from_item` 会拒收缺标题/缺来源/缺 DOI|URL 的条目。
            from . import evidence as _ev
            norm, rejected = _ev._sources_from_items(
                items, source_name="localpdf", query="group operation",
                retrieved_at=S.now_iso(),
            )
            print(f"[8b] 证据层归一：收下 {len(norm)} 条 / 拒收 {len(rejected)} 条 {rejected}")
            if len(norm) != 1 or rejected:
                problems.append(f"证据层拒收了本地条目：{rejected}")
            elif norm[0]["abstract"] not in (norm[0]["abstract"] or "") or \
                    "group" not in norm[0]["abstract"].lower():
                problems.append("归一后的摘录里没有主题词")

        fetched = local_fetch_fn()(items[0]["pdf_url"], str(Path(td) / "ft"), "hint")
        print(f"[9] fetch 接缝：ok={fetched.ok} bytes={fetched.bytes} kind={fetched.kind!r} "
              f"sha={(fetched.sha256 or '')[:12]}…")
        if not fetched.ok or fetched.kind is not None or Path(fetched.path) != Path(items[0]["pdf_url"]):
            problems.append(f"本地 fetch 接缝不对：{fetched}")

    print("=" * 72)
    if problems:
        for p in problems:
            print(f"[!!] {p}")
        return 1
    print("自检通过：6 条全过")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手跑入口
    raise SystemExit(selftest())

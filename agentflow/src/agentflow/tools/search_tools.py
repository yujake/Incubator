"""A 专用检索工具：provider 探测 / 文献检索 / 下载 / 判重检查 / 文献登记。
基于 ``tools/base.py`` 的 ``ToolSpec`` / ``ToolResult`` 写（见 ``DESIGN-TOOLS.md`` §1）。
## 为什么需要这一层
A 的思维链只该花在"判断该调哪个工具、该用哪个检索词"上，不该花在"怎么把 provider 的参数拼对"、"这条是不是已经登记过"上。工具层把这些标准动作固化成有名字、有 schema、有校验、有结构化返
回、声明副作用的原子动作。
## 三条贯穿全模块的原则
``search.literature`` 的每条候选都带``dedup_key`` / ``existing`` / ``is_new``：A 看到候选列表的同时就知道哪几条是新的。
2. "没做"与"做了没结果"必须分开（与 ``DESIGN.md`` §6.3 的"无文本层返回``None`` 而不是 ``False``"同源）：- provider 检索抛异常 ⇒ ``fail``（没
做成）；检索正常但零命中 ⇒``ok`` + 空列表（做了，结论就是"没有"）。- 未配置 ``store`` 时无法比对既有文献表 ⇒ 候选的 ``existing`` 是 ``None``（未知），而不是
``False``（"新的"）。
``search.providers`` 对每个 provider 发一次极小的真实请求；``ABFLOW_SKIP_NETWORK=1`` 时明确标 ``unverified``（未探测），而不是把"没探测
"写成"可用"或"不可用"。
正因为它真的发 HTTP，它的 ``side_effect`` 是 ``network``（需要审批），不是 ``read``。这一处曾经声明成 ``read``：那等于在权限面上说"这个工具不联网、不必审批
"，而它每次调用都会向外部源发起请求 ——声明与实际不符的副作用等级会让"审批"这个闸门在该拦的地方不拦。（``ABFLOW_SKIP_NETWORK=1`` 只是"这一次没探测"，不是"这个工具不联网"；
## 文件落点（为什么这样定）
- ``search.download`` 下到 ``<workspace>/downloads/`` —— 这是一个中间态：文件名由 ``fetch`` 层 slug 化并去重，下载器保证"不覆盖已有文件"。
- ``search.register`` 把文件收编进 ``<store.library>/<lit_id>/``：因为``schema.Literature.path`` 必须是 library/ 下的相
对路径，绝对路径会被``Literature.validate()`` 直接拒绝。收编失败时行照建、``path`` 置 ``null``并给 warning —— "知道有这篇但拿不到全文"本身就是有价值的
结果（DESIGN.md §2.4）。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import urllib.parse
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .base import ToolError, ToolRegistry, ToolSpec, fail, ok, tool
from .. import dedup as D
from .. import fetch as F
from .. import providers as P
from .. import schema as S
from .. import textutil as T
from ..store import Store

__all__ = [
    "PROVIDER_CATALOG",
    "NETWORK_PROVIDERS",
    "DEFAULT_MAX_DOWNLOAD_BYTES",
    "register",
]

#: 默认 provider。OpenAlex 元数据最全（被引数/摘要倒排索引/OA 链接），是主力源。
DEFAULT_PROVIDER = "openalex"

#: 内置 provider 目录：名字 → 一句话说明。顺序即探测顺序。
#: 这里的说明是给人/LLM 看的"该选谁"的依据，不是能力承诺。
PROVIDER_CATALOG: tuple[tuple[str, str], ...] = (
    ("openalex", "主力源：标题/年份/DOI/类型/摘要/OA 的 PDF 链接，支持被引降序（找奠基性文献）"),
    ("crossref", "补充源：页码、container-title、publisher 等元数据补齐；摘要覆盖不如 OpenAlex"),
    ("doaj", "开放获取期刊文章（类型固定 J）；只覆盖 OA 期刊，范围窄"),
    ("europepmc", "生命科学领域覆盖好，其它领域仅作补充"),
    ("fixture", "离线 fixture（读 demo/fixtures/candidates.json）：不联网、确定性，供离线跑通与测试"),
)

#: 需要联网的 provider（探测时会发一次真实请求）。fixture 是本地文件，不算。
NETWORK_PROVIDERS: frozenset[str] = frozenset({"openalex", "crossref", "doaj", "europepmc"})

#: ``search.download`` 的默认单文件上限：50 MB。与 ``extract.DEFAULT_MAX_BYTES``
#: 取同一个量级 —— 超过 50MB 的"单篇文献"多半是误抓的整库 PDF，抽关系没有意义。
DEFAULT_MAX_DOWNLOAD_BYTES: int = 50 * 1024 * 1024

#: 单个 provider 探测的超时（秒）。探测是"极小请求 + 明确结论"，不该拖住工具调用；
#: 8 秒足够判断可达性，又不至于让四个源依次超时把 ``search.providers`` 挂上几分钟。
_PROBE_TIMEOUT: float = 8.0

#: 环境开关：置 1 时一律不发探测请求，把 network provider 标成 ``unverified``。
#: 离线 CI / 无网环境需要一个"别去连网"的确定开关，而不是靠超时等待。
_SKIP_NETWORK_ENV = "ABFLOW_SKIP_NETWORK"


def _skip_network() -> bool:
    return (os.environ.get(_SKIP_NETWORK_ENV) or "").strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------- 上下文


@dataclass
class _Ctx:
    """工具闭包共享的上下文。

    工具是"注册时就绑定好依赖"的闭包（``Store`` / provider / downloader 由外部注入），
    这样脚本模式与 LLM 模式能用同一份实现，也让离线测试可以注入假对象。
    """

    workspace: Path
    store: Store | None = None
    downloader: Any | None = None
    config: dict = field(default_factory=dict)
    provider_config: dict = field(default_factory=dict)
    actor: str = "agent-A"
    #: 名字 → provider 实例。注入的与惰性构造的都缓存在这里（限速状态是进程级全局的，
    #: 复用一个实例不会破坏礼貌访问；反复新建反而会重复付初始化的代价）。
    providers: dict[str, Any] = field(default_factory=dict)
    #: max_bytes → downloader 实例。避免每次调用都重新构造 opener。
    downloaders: dict[int, Any] = field(default_factory=dict)

    @property
    def downloads_dir(self) -> Path:
        return self.workspace / "downloads"

    @property
    def fixture_path(self) -> Path:
        """离线 fixture 的位置：配置 > 工作区 > providers 模块自带的默认位置。

        为什么要三级回退：``providers.FixtureProvider()`` 在 path 为 None 时用的就是
        模块自带的默认路径，工具层若只认"工作区下的 demo/fixtures"，
        在临时工作区（测试/CI）里会把一个本来可用的离线源误报为不可用。
        """
        for p in self._fixture_candidates:
            if p.exists():
                return p
        return self._fixture_candidates[0]

    @property
    def _fixture_candidates(self) -> list[Path]:
        out: list[Path] = []
        cfg = self.provider_config.get("fixture_path")
        if cfg:
            out.append(Path(cfg))
        out.append(self.workspace / "demo" / "fixtures" / "candidates.json")
        default = Path(P.DEFAULT_FIXTURE_PATH)
        if default not in out:
            out.append(default)
        return out


# --------------------------------------------------------------------------- 小工具


def _timed(fn, *args: Any, **kwargs: Any) -> tuple[Any, float]:
    t0 = time.monotonic()
    out = fn(*args, **kwargs)
    return out, round(time.monotonic() - t0, 3)


def _sha256_of(path: Path, chunk: int = 1 << 20) -> str | None:
    """流式算文件哈希；失败返回 ``None``（哈希是诊断信息，不该让登记整体失败）。"""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            while True:
                block = fh.read(chunk)
                if not block:
                    break
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _rel_to(path: Path, root: Path) -> str:
    """相对路径（posix 风格）；不在 root 下则退回文件名，绝不返回绝对路径。"""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path.name


def _lit_summary(row: Mapping[str, Any]) -> dict:
    """既有文献行的摘要视图（只挑判重/追溯用得上的字段）。"""
    return {
        "lit_id": row.get("lit_id"),
        "title": row.get("title"),
        "year": row.get("year"),
        "doi": row.get("doi"),
        "type": row.get("type"),
        "path": row.get("path"),
        "processed": bool(row.get("processed")),
        "source_request_ids": list(row.get("source_request_ids") or []),
    }


# --------------------------------------------------------------------------- 本地书架（离线）

#: 抽取器在进程内记忆化（键是 `(路径, 大小, mtime_ns)`，见 `locallib.memo_extract_fn`）。
#: 为什么放在模块级：A 的一个回合里可能连问几次 `search.local`（换一次检索词就是一次），
#: 一本 400 页的书抽一次要几秒，不记忆化就等于每次重抽整架书。
_SHELF_EXTRACT: Any = None


def _shelf_extract() -> Any:
    """取（并惰性构造）书架抽取器。惰性是为了注册工具时不必导入抽取后端。"""
    global _SHELF_EXTRACT
    if _SHELF_EXTRACT is None:
        from ..locallib import memo_extract_fn

        _SHELF_EXTRACT = memo_extract_fn()
    return _SHELF_EXTRACT


def _shelf_row(ctx: _Ctx, row: Mapping[str, Any]) -> dict[str, Any] | None:
    """把一条 literature 行变成书架条目；`path` 不在盘上则返回 None（不是书架上的书）。"""
    rel = str(row.get("path") or "")
    if not rel or ctx.store is None:
        return None
    abs_path = ctx.store.library_path(rel)
    if abs_path is None or not Path(abs_path).is_file():
        return None
    dl = dict(row.get("download") or {})
    return {
        "lit_id": str(row.get("lit_id") or ""),
        "title": str(row.get("title") or ""),
        "path": rel,
        "abs_path": str(abs_path),
        "bytes": int(dl.get("bytes") or Path(abs_path).stat().st_size),
        "pages": dl.get("pages"),
        "has_text_layer": dl.get("has_text_layer"),
        # 来源如实分两档：「人放到本地目录」进来的（`source_path` 有值）与
        # 「A 从网上下来」的（没有 `source_path`）。这一栏决定"离线可引用"是否成立，
        # 也决定"这篇文献从哪来"这条链会不会说假话。
        "origin": "local_ingest" if dl.get("source_path") else "downloaded",
        "sha256_12": str(dl.get("sha256") or "")[:12],
    }


def _h_shelf(ctx: _Ctx, limit: int | None = None, lit_id: str = "", query: str = "") -> Any:
    """``search.shelf``：不联网，列出库里「全文在盘上」的文献（可按 `query` 过滤题名/路径）。"""
    if ctx.store is None:
        return fail(
            "未配置 store：读不到文献表，也就说不出书架上有什么"
            "（空书架与读不到是两件事，不许折叠成一个空列表）。",
            kind="no_store",
            counted=False,
        )
    rows, read_error = _literature_rows(ctx)
    if read_error is not None:
        return fail(f"{read_error} ⇒ 书架**没数成**（不是「书架是空的」）。", kind="table_unreadable",
                    counted=False, read_error=read_error)

    books: list[dict] = []
    missing = 0
    # 「2026-10-16（亲测 A 的工具面时加的）」：这一件叫 `search.shelf`，可它的参数里
    # 「没有 `query`」 —— 我第一次凭感觉敲的就是 `query=`，吃了一个"未声明的参数"。
    # 按业主口径（"第一次凭感觉敲红的，真实智能体也会在这里困惑"）⇒ 让「第一猜能 work」：
    # 可选 `query`，按「题名/路径」做子串过滤（大小写不敏感）。它不读全文
    # （全文按主题取片段是 `search.local` 的事，两者的分工在说明里写清）。
    needle = str(query or "").strip().lower()
    matched = 0
    for row in rows:
        if lit_id and str(row.get("lit_id") or "") != lit_id:
            continue
        item = _shelf_row(ctx, row)
        if item is None:
            if row.get("path"):
                missing += 1
            continue
        if needle:
            hay = f"{item.get('title') or ''} {item.get('path') or ''}".lower()
            if needle not in hay:
                continue
            matched += 1
        books.append(item)
    books.sort(key=lambda b: b["lit_id"])
    truncated = False
    if limit is not None and len(books) > limit:
        books = books[:limit]
        truncated = True
    return ok(
        {
            "count": len(books),
            "query": str(query or ""),
            "filtered_out": (len(books) + sum(
                1 for r in rows if needle and needle not in
                f"{r.get('title') or ''} {r.get('path') or ''}".lower()))
                - len(books) if needle else 0,
            "rows_total": len(rows),
            "have_path": sum(1 for r in rows if r.get("path")),
            "missing_files": missing,
            "local_ingest": sum(1 for b in books if b["origin"] == "local_ingest"),
            "downloaded": sum(1 for b in books if b["origin"] == "downloaded"),
            "truncated": truncated,
            "books": books,
            "note": (
                "这是**离线**来源：这些文件的正文就在工作区里，"
                "可以用 search.local 按主题取逐字摘录。"
                "`missing_files` 是「行上写了 path、但文件不在盘上」的条数 —— "
                "它不是 0 时，那些书**取不到正文**，不要当它们存在。"
            ),
        }
    )


def _h_local(ctx: _Ctx, query: str, limit: int = 5, max_chars: int = 1200,
             lit_id: str = "", max_books: int | None = None) -> Any:
    """``search.local``：不联网，在书架的全文里按主题取最相关的一页与逐字摘录。"""
    import time as _time

    if ctx.store is None:
        return fail(
            "未配置 store：读不到书架（不是「书架上没有相关内容」）。",
            kind="no_store",
            searched=False,
        )
    rows, read_error = _literature_rows(ctx)
    if read_error is not None:
        return fail(f"{read_error} ⇒ 检索**没做成**（不是「没有命中」）。", kind="table_unreadable",
                    searched=False, read_error=read_error)

    from ..locallib import excerpt_for, page_scores

    t0 = _time.monotonic()
    extract = _shelf_extract()
    hits: list[dict] = []
    skipped_no_file: list[str] = []
    unreadable: list[dict] = []
    no_text: list[str] = []
    scanned = 0
    for row in rows:
        if lit_id and str(row.get("lit_id") or "") != lit_id:
            continue
        item = _shelf_row(ctx, row)
        if item is None:
            if row.get("path"):
                skipped_no_file.append(str(row.get("lit_id") or ""))
            continue
        if max_books is not None and scanned >= max(1, int(max_books)):
            break
        scanned += 1
        try:
            doc = extract(item["abs_path"])
        except Exception as exc:  # noqa: BLE001 —— 抽不了就是抽不了，逐本如实记一档
            unreadable.append({"lit_id": item["lit_id"], "why": f"{type(exc).__name__}: {exc}"})
            continue
        pages = [str(p) for p in (getattr(doc, "pages", []) or [])]
        if not pages or not any(p.strip() for p in pages):
            no_text.append(item["lit_id"])
            continue
        # 打分口径不在这里重写：`page_scores` 就是 `excerpt_for` 挑页用的同一份实现
        # （覆盖率优先 + 导航页惩罚，理由见它的 docstring）。一本书的分数取它最高的那一页。
        scores = page_scores(pages, query)
        best_page_score = max(scores) if scores else 0.0
        page, excerpt = excerpt_for(pages, query, max_chars=max_chars)
        hits.append({**{k: item[k] for k in ("lit_id", "title", "path", "sha256_12")},
                     "page": page, "excerpt": excerpt, "pages": len(pages),
                     "score": round(float(best_page_score), 4)})

    # 排序键是相关度，不是摘录长度：窗口取满时长度恒等于 `max_chars`，
    # 拿它当主键等于按 lit_id 字母序排（§187 真机读数里"martingale central limit
    # theorem"的第三名是一篇讲伊朗城市的论文，就是这么来的）。
    hits.sort(key=lambda h: (-h["score"], h["lit_id"]))
    kept = hits[: max(1, int(limit))]
    return ok(
        {
            "query": query,
            "searched": True,
            "count": len(kept),
            "candidates": len(hits),
            "scanned": scanned,
            "skipped_no_file": skipped_no_file,
            "unreadable": unreadable,
            "no_text_layer": no_text,
            "hits": kept,
            "elapsed_s": round(_time.monotonic() - t0, 3),
            "note": (
                "每条命中给的是**原文里连续的一段**（不是拼起来的句子），"
                "并带 lit_id 与页码 —— 引文回验比的就是这段原文。"
                "`skipped_no_file` / `unreadable` / `no_text_layer` 是"
                "「这一本没查到」的三个不同理由：它们不等于「这本书里没有这个主题」。"
            ),
        }
    )


# --------------------------------------------------------------------------- provider 解析


def _known_names(ctx: _Ctx) -> list[str]:
    """可用名字 = 内置目录 ∪ 调用方注入的 provider。保持稳定顺序（目录顺序在前）。"""
    names = [n for n, _ in PROVIDER_CATALOG]
    names += [n for n in ctx.providers if n not in names]
    return names


def _resolve_provider(ctx: _Ctx, name: str) -> Any:
    """按名字取 provider 实例；未知名字抛 ``ToolError``（由 handler 转成 ``fail``）。"""
    key = (name or "").strip().lower()
    if not key:
        raise ToolError(f"provider 不能为空；可用：{_known_names(ctx)}")
    if key in ctx.providers:
        return ctx.providers[key]
    if key not in dict(PROVIDER_CATALOG):
        raise ToolError(f"未知 provider {name!r}；可用：{_known_names(ctx)}")
    built = P.build_providers([key], config=ctx.provider_config, fixture_path=ctx.fixture_path)
    if not built:
        raise ToolError(f"provider {key!r} 构造失败（build_providers 返回空）")
    ctx.providers[key] = built[0]
    return built[0]


def _provider_diagnostics(prov: Any) -> dict:
    """把 provider 自带的统计/查询串捞出来。
    这是"为什么只回来 2 条"的唯一可查证据：``last_query_text`` 说明实际发出去的检索串，``filter_notes`` 说明有多少条被
    precise 的标题过滤筛掉。``last_phrase_fallbacks`` 与 ``last_channel_errors`` 是 `C-4` 之后新增的两条（短语
    零召回 ⇒ 退了词项检索 / 这一路抛了异常）：缺了它们，"只回来 2 条"与"整串短语把召回打成 0"在读数上长得一模一样。
    `FINAL-R3-05`：`stats` 里那几个计数是跨多跑累积的（同一个 provider 对象被反复读时它一直涨），而 `last_*` 全是逐跑读数 —— 两组数
    并排放着容易被读成同一时刻的同一件事。产物里没有"这一跑的 stats 快照"这一档（本次没有加：加字段要动 `evidence` 侧的折算），所以读的时候请以 
    `last_*` 为准，`stats` 只用来看"这个对象一共发过多少请求"。
    E-10（`draft/44`）：`last_topicality` 必须在这一屏里 —— 它是"返回 0 条"与"这一问根本没问出去"的唯一分界（`QueryApplicability`
    的第三态：`query_empty` /`query_not_applicable_cjk`）。此前这一屏只捞 `stats`/`last_query_text`/…，于是
    空 topic 那次 `return []` 在生产读数上与"问了、零命中"长得一模一样。`last_query_provenance` 同理：它逐条记"这一路
    query 发没发出去（`dispatched`）"。
    """
    out: dict[str, Any] = {}
    for attr in ("stats", "last_query_text", "last_filter_notes", "last_filtered_out",
                 "last_phrase_fallbacks", "last_channel_errors",
                 "last_topicality", "last_query_provenance"):
        value = getattr(prov, attr, None)
        if value is not None:
            out[attr] = value
    return out


# --------------------------------------------------------------------------- 探测


def _probe_network_provider(name: str, timeout: float = _PROBE_TIMEOUT) -> dict:
    """对网络 provider 发一次极小的真实请求，返回如实标注的探测结论。

    判据刻意保守：能取回可解析的 JSON 结构就算可用。不做检索质量判断 ——
    "这个源能不能连上"与"这个源对这个 topic 有没有结果"是两件事，
    混在一起会让"某话题没结果"被误读成"源坏了"。
    """
    targets: dict[str, tuple[str, dict, str]] = {
        "openalex": (
            P.OpenAlexProvider.BASE_URL,
            {"search": "abelian group", "per-page": 1, "select": "id"},
            "GET /works?search=…&per-page=1",
        ),
        "crossref": (
            P.CrossrefProvider.BASE_URL,
            {"query.bibliographic": "abelian group", "rows": 1, "select": "DOI"},
            "GET /works?query.bibliographic=…&rows=1",
        ),
        "doaj": (
            P.DoajProvider.BASE_URL + urllib.parse.quote('bibjson.title:("group")'),
            {"pageSize": 1},
            "GET /api/search/articles/bibjson.title:…",
        ),
        "europepmc": (
            P.EuropePmcProvider.BASE_URL,
            {"query": "abelian group", "format": "json", "pageSize": 1},
            "GET /search?query=…&pageSize=1",
        ),
    }
    entry = targets.get(name)
    if entry is None:
        return {
            "available": None,
            "status": "unverified",
            "reason": "无内置探测端点（可能是调用方注入的自定义 provider），未探测",
            "latency_s": None,
            "evidence": "",
        }
    url, params, evidence = entry

    t0 = time.monotonic()
    try:
        payload = P.http_get_json(url, params, timeout=timeout, retries=0)
    except Exception as exc:  # noqa: BLE001 - provider 层异常类型不统一，探测要兜住全部
        return {
            "available": False,
            "status": "probed_fail",
            "reason": f"{type(exc).__name__}: {str(exc)[:240]}",
            "latency_s": round(time.monotonic() - t0, 3),
            "evidence": evidence,
        }
    latency = round(time.monotonic() - t0, 3)
    if isinstance(payload, (Mapping, list)):
        return {
            "available": True,
            "status": "probed_ok",
            "reason": f"真实请求成功并返回可解析 JSON（{evidence}）",
            "latency_s": latency,
            "evidence": evidence,
        }
    # 请求没抛异常但载荷形态不对：可能是被劫持/网关错误页顶替。不能算可用。
    return {
        "available": False,
        "status": "probed_fail",
        "reason": f"请求未报错但载荷形态异常：{type(payload).__name__}",
        "latency_s": latency,
        "evidence": evidence,
    }


def _probe_provider(ctx: _Ctx, name: str) -> dict:
    """探测一个 provider，返回"可用 / 未探测 / 不可用 + 理由"。

    ``fixture`` 走本地文件检查（它本来就不联网）；其余走真实请求。
    ``ABFLOW_SKIP_NETWORK=1`` 时不发请求，如实标 ``unverified``。
    """
    notes = dict(PROVIDER_CATALOG)
    row: dict[str, Any] = {
        "name": name,
        "note": notes.get(name, "调用方注入的 provider（不在内置目录里）"),
        "requires_network": name in NETWORK_PROVIDERS,
    }

    if name == "fixture":
        path = ctx.fixture_path
        exists = path.exists()
        tried = ctx._fixture_candidates
        row.update(
            available=exists,
            status="probed_ok" if exists else "probed_fail",
            reason=(
                f"离线 fixture 文件存在：{path}"
                if exists
                else f"离线 fixture 文件不存在（依次找过 {[str(p) for p in tried]}）；"
                "它是纯本地源，不联网，无法退化为网络检索"
            ),
            latency_s=None,
            evidence=str(path),
        )
        return row

    if _skip_network():
        row.update(
            available=None,
            status="unverified",
            reason=(
                f"{_SKIP_NETWORK_ENV}=1：按约定未发探测请求。**这是「未探测」，"
                "既不代表可用也不代表不可用**；要得到结论请去掉该环境变量重跑。"
            ),
            latency_s=None,
            evidence="",
        )
        return row

    row.update(_probe_network_provider(name, timeout=float(ctx.config.get("probe_timeout", _PROBE_TIMEOUT))))
    return row


# --------------------------------------------------------------------------- 工具 handler


def _h_providers(ctx: _Ctx) -> Any:
    """``search.providers``：列出可用 provider（真实探测可用性）。"""
    rows = [_probe_provider(ctx, name) for name in _known_names(ctx)]
    available = [r["name"] for r in rows if r["available"] is True]
    unavailable = [r["name"] for r in rows if r["available"] is False]
    unverified = [r["name"] for r in rows if r["available"] is None]
    return ok(
        {
            "skip_network": _skip_network(),
            "providers": rows,
            "available": available,
            "unavailable": unavailable,
            "unverified": unverified,
            # 刻意给出"本次探测到底做了什么"的一句话总结，避免把 unverified 读成可用。
            "summary": (
                f"{len(available)} 个已探测可用、{len(unavailable)} 个已探测不可用、"
                f"{len(unverified)} 个未探测。"
                + ("（未探测 ≠ 不可用：见各行 reason）" if unverified else "")
            ),
            "default_provider": DEFAULT_PROVIDER,
        }
    )


def _multi_source_reading(mp: Any) -> dict[str, Any]:
    """把 `MultiProvider` 的逐源台账翻成工具层读数（`R2b` ⑱ 的"逐源三态"）。

    `MultiProvider.last_stats` 已经是按源的三态（`ProviderStat.status`：
    `ok` / `failed` / `not_run` / `query_not_applicable_cjk` / `query_empty`），
    这里只做搬运，不重新判一遍 —— 判据在 `providers.ProviderStat` 里，
    在这里再判一次就是第二份口径（`FC-03`）。
    """
    stats = getattr(mp, "last_stats", None) or {}
    rows: list[dict[str, Any]] = []
    for name, st in stats.items():
        rows.append({
            "name": str(name),
            "status": str(getattr(st, "status", "") or ""),
            "count": int(getattr(st, "count", 0) or 0),
            "error_kind": str(getattr(st, "error_kind", "") or ""),
            "error": str(getattr(st, "error", "") or ""),
            # `delivered` / `refused` 是 `ProviderStat` 自己的两个属性（它明说读者该用它们
            # 而不是拿 `failed` 当"没结果"的含括判据）。
            "delivered": bool(getattr(st, "delivered", False)),
            "refused": bool(getattr(st, "refused", False)),
        })
    return {
        "sources": rows,
        "refusals": dict(getattr(mp, "last_refusals", None) or {}),
        # 两支"没交货"的分开列：`failed` 是上游坏了，`refused` 是这一问根本没发出去。
        # 折成一个"没结果"会让"被墙/限流"与"这问对这条通道不适用"同形。
        "failed": sorted(r["name"] for r in rows if r["status"] == "failed"),
        "refused": sorted(r["name"] for r in rows if r["refused"]),
        "delivered": sorted(r["name"] for r in rows if r["delivered"]),
    }


def _single_source_reading(prov: Any, candidates: Iterable[Any]) -> list[dict[str, Any]]:
    """单源那一路的逐源读数（与多源同一形状）。

    为什么单源也要给：`sources[]` 是声明的一部分，而"这次问了谁、它交没交货"在单源调用上
    同样要读得到；只给多源会让同一条声明的键随调用方式时有时无（声明就变成半个真话）。

    第三态（这一问根本没发出去）复用 `providers._provider_refusal` —— 那是它的唯一实现，
    本函数只把结论翻成同一形状的一行。用 `ProviderStat` 而不是手写 dict：它的构造器自己
    校验不变量（`failed` 必须给 `error_kind`、第三态必须给理由、二者都不许报条数），
    手写就等于把这些校验绕过去了。
    """
    name = str(getattr(prov, "name", type(prov).__name__))
    listed = list(candidates)
    state, why = P._provider_refusal(prov, listed)
    stat = (P.ProviderStat(status=state, count=0, error_kind="", error=why or state)
            if state else P.ProviderStat(status="ok", count=len(listed)))
    return [{
        "name": name,
        "status": stat.status,
        "count": stat.count,
        "error_kind": stat.error_kind,
        "error": stat.error,
        "delivered": bool(getattr(stat, "delivered", False)),
        "refused": bool(getattr(stat, "refused", False)),
    }]


def _h_literature(
    ctx: _Ctx,
    topic: str,
    mode: str = "topical",
    description: str = "",
    limit: int = 10,
    provider: str = DEFAULT_PROVIDER,
    providers: Iterable[str] | None = None,
) -> Any:
    """``search.literature``：检索候选，并把判重结论一并算好。
    ## `providers=[…]`：一次问多源（`R2b` ⑱）
    给了它就忽略 `provider`，走 `providers.MultiProvider` 把多个源合并（按`_merge_identity_key` 去重、
    `raw.providers` 留住"这条来自哪些源"）。三条硬要求在这里的落点：
    1. 逐源三态：`sources[]` 逐源给出 `status`/`count`/`error_kind`/`error`；某个源失败不影响别的源的结果（`fail_fast=False`）；
    一个源都没交货（全 `failed` 或全 `refused`）⇒ 这一调用落 `fail`，绝不折成"检索正常、零命中"——那会把"没查成"写成"查了没有"。 2. 去重
    口径只留一处：本函数不自己合并，跨源合并在 `MultiProvider` 里、与文献表比对仍走 `dedup.literature_keys` / 
    `find_existing_literature`（同一份）。 3. 成本可读：`cost.provider_calls`（这次向上游发了几次）+ 
    `cost.elapsed_s`。
    """
    description = description or ""
    # 与 schema.SearchRequest 的约束保持一致：精确模式必须给出内容描述，
    # 否则 providers 层会构造出 ``search=""`` 这种无意义查询（§1.1）。
    if mode == "precise" and not description.strip():
        return fail(
            "mode=precise 时必须提供 description（内容描述）：精确模式以 description 为主检索词、"
            "topic 为约束，缺了它就构造不出有效查询。这与 schema.SearchRequest 的校验一致。",
            kind="param_constraint",
            mode=mode,
        )

    wanted: list[str] = []
    for raw_name in (providers or []):
        name = str(raw_name or "").strip()
        if name and name not in wanted:
            wanted.append(name)
    if providers is not None and not wanted:
        return fail(
            "providers 是空列表：要么不给这个参数（按 provider 走单源），要么至少给一个源名。"
            "给空列表既不是单源也不是多源，只会让'这次到底问了谁'变得没法读。",
            kind="bad_providers",
            available=_known_names(ctx),
        )

    multi: dict[str, Any] | None = None
    sources: tuple[str, ...] = ()
    if wanted:
        try:
            provs = [_resolve_provider(ctx, name) for name in wanted]
        except ToolError as exc:
            return fail(str(exc), kind="unknown_provider", available=_known_names(ctx),
                        providers_requested=wanted)
        sources = tuple(getattr(p, "name", n) for p, n in zip(provs, wanted))
        mp = P.MultiProvider(provs, name="multi")
        # ---- S-E 协作式截止的检查点（裁定 13甲 / 12-D「不机械杀进程」）：
        # 多源检索是最容易把一步拖到分钟级的一件（每个源各有自己的网络超时）。
        # 检查点放在打出去之前：已经到点就不要再发新的请求了。
        from ..tool_timeout import raise_if_timed_out

        raise_if_timed_out()
        try:
            candidates, elapsed = _timed(mp.search, topic, mode, description, int(limit))
        except Exception as exc:  # noqa: BLE001 - 检索失败必须如实上报（"没做成"）
            return fail(
                f"providers={list(wanted)!r} 检索失败：{type(exc).__name__}: {exc}",
                kind="provider_error",
                providers_requested=wanted,
                topic=topic,
                mode=mode,
            )
        multi = _multi_source_reading(mp)
        if not multi["delivered"]:
            # 三态：没有任何源交货 ⇒ 没查成。逐源理由一起带出去，
            # 这样调用方能分清"上游坏了"（failed）与"这一问没发出去"（refused）。
            return fail(
                "这一次一个源都没有交货 ⇒ 没查成（不是'检索正常、零命中'）："
                f"failed={multi['failed']}、refused={multi['refused']}；逐源读数见 sources[]",
                kind="provider_error",
                providers_requested=wanted,
                sources=multi["sources"],
                source_failures=multi["failed"],
                source_refusals=multi["refusals"],
                topic=topic,
                mode=mode,
            )
        prov: Any = None
    else:
        try:
            prov = _resolve_provider(ctx, provider)
        except ToolError as exc:
            return fail(str(exc), kind="unknown_provider", available=_known_names(ctx))

        # 同一条检查点（单源那一支）：到点了就别再打这一个源。
        from ..tool_timeout import raise_if_timed_out

        raise_if_timed_out()
        try:
            candidates, elapsed = _timed(prov.search, topic, mode, description, int(limit))
        except Exception as exc:  # noqa: BLE001 - 检索失败必须如实上报（"没做成"）
            return fail(
                f"provider={getattr(prov, 'name', provider)!r} 检索失败：{type(exc).__name__}: {exc}",
                kind="provider_error",
                provider=getattr(prov, "name", provider),
                topic=topic,
                mode=mode,
            )
    provider_label = "multi" if wanted else getattr(prov, "name", provider)
    # 逐源读数两条路都给（同一形状）：多源来自 `MultiProvider` 的台账，
    # 单源来自 `_single_source_reading`（同样复用 providers 层那两处判据）。
    source_rows = (multi["sources"] if multi else
                   _single_source_reading(prov, candidates))
    source_failures = sorted(r["name"] for r in source_rows if r["status"] == "failed")
    source_refusals = sorted(r["name"] for r in source_rows if r["refused"])

    candidates = list(candidates or [])
    rows, read_error = _literature_rows(ctx)
    # "有 store"不等于"读到了表"：表坏了的时候也没查成，
    # 于是所有候选的 is_new 必须是 None（未知），而不是 True（新的）。
    store_known = ctx.store is not None and read_error is None

    items: list[dict] = []
    seen_keys: set[str] = set()
    for cand in candidates:
        keys = D.literature_keys(cand.title, cand.year, cand.doi)
        key = keys[0] if keys else None
        if store_known:
            existing, hit_key = D.find_existing_literature(rows, cand.title, cand.year, cand.doi)
        else:
            # 没有 store 就没有比对基准。这里是三态而不是布尔：
            # ``None`` = 没查过（未知），``True`` = 表里已有，``False`` = 已确认是新的。
            # 把"没查"写成"新的"会让 A 重复登记同一篇文献。
            existing, hit_key = None, None
        batch_dup = key is not None and key in seen_keys
        is_new: bool | None
        if not store_known:
            is_new = None if not batch_dup else False
        else:
            is_new = (existing is None) and (not batch_dup)
        if key:
            seen_keys.add(key)
        items.append(
            {
                "title": cand.title,
                "year": cand.year,
                "doi": cand.doi,
                "type_code": cand.type_code,
                "authors": list(cand.authors or []),
                "venue": cand.venue,
                "language": cand.language,
                # 摘要按 providers 层同样的上限裁剪：候选只是"要不要它"的判断依据，
                # 不该挤占 prompt 预算（完整摘要已在候选对象里，登记时会落库）。
                "summary": T.clip(cand.summary, P.SUMMARY_MAX_CHARS),
                "pdf_url": cand.pdf_url,
                "landing_url": cand.landing_url,
                "provider": cand.provider or provider_label,
                # ---- 判重（A 一眼看出哪几条是新的，不必再跑一次判重工具）
                "dedup_key": key,
                "dedup_keys": keys,
                "existing": (existing is not None) if store_known else None,
                "existing_lit_id": (existing or {}).get("lit_id") if existing else None,
                "dedup_hit_key": hit_key,
                "batch_duplicate": batch_dup,
                "is_new": is_new,
                # `R2b` ⑱：这条合并结果来自哪几个源 —— "哪几条重复"的读数就在这里
                # （`MultiProvider` 把来源写进 `raw.providers`；单源时它是那一源的名单）。
                # 不读 `raw.sources`（那是完整原始记录，属于 providers 层内部）。
                "sources": list((cand.raw or {}).get("providers") or []),
                "channel": (cand.raw or {}).get("channel"),
                "cited_by_count": (cand.raw or {}).get("cited_by_count"),
            }
        )

    new_count = sum(1 for i in items if i["is_new"] is True)
    existing_count = sum(1 for i in items if i["existing"] is True)
    unknown_count = sum(1 for i in items if i["is_new"] is None)
    data: dict[str, Any] = {
        "provider": provider_label,
        "mode": mode,
        "topic": topic,
        "description": description,
        "limit": int(limit),
        "count": len(items),
        "new_count": new_count,
        "existing_count": existing_count,
        "unknown_count": unknown_count,
        "batch_duplicate_count": sum(1 for i in items if i["batch_duplicate"]),
        "store_checked": store_known,
        "store_read_error": read_error,
        "existing_table_size": len(rows) if store_known else None,
        "candidates": items,
        "elapsed_s": elapsed,
        "diagnostics": _provider_diagnostics(prov) if prov is not None else {},
        # ---- `R2b` ⑱：逐源读数（两条路都给；`providers_requested` 才是"这次问没问多源"的标记）
        "providers_requested": list(wanted) if wanted else None,
        "sources": source_rows,
        "source_count": len(source_rows),
        "source_failures": source_failures,
        "source_refusals": source_refusals,
        # 成本：多源 = 多次出网。`provider_calls` 数的是"这次向上游发了几次"，
        # 不是为了精确计费（检索没有 token 账），而是让"多源贵在哪"一眼可见。
        "cost": {"provider_calls": len(source_rows), "elapsed_s": elapsed},
    }
    warnings: list[str] = []
    if source_failures:
        # 一个源失败不许吞掉别的源的结果，但也不许静默：候选里少了它的那几条，
        # 而"少了"与"它没命中"是两件事 —— 所以每次点名。
        warnings.append(
            f"这些源这次失败了（候选里没有它们的贡献，但它们不是「没命中」）："
            f"{source_failures}；逐源理由见 sources[]。"
        )
    if source_refusals:
        warnings.append(
            f"这些源这一问**根本没发出去**（第三态：查询对它不适用/为空，不是上游坏了）："
            f"{source_refusals}；理由见 sources[]。这一档**不是「零命中」**。"
        )
    if read_error is not None:
        warnings.append(
            f"{read_error} ⇒ **判重没查**（不是「都是新的」）：候选的 existing/is_new 均为 null（未知）。"
            "「表读不出来」与「表里确实没有这篇」是两件事，不允许折叠。"
        )
    if not store_known and read_error is None:
        warnings.append(
            "未配置 store：无法与既有文献表比对，候选的 existing/is_new 均为 null（未知）。"
            "要得到判重结论请用 register(..., store=store) 构造工具，或改用 search.dedup_check。"
        )
    if not items:
        warnings.append(
            "检索正常执行但零命中——这是一个**有效结论**（topic 下确实没有候选），不是故障。"
            "diagnostics 里有实际发出的检索串与被过滤条数，可据此判断下一步换词。"
        )
    data["warnings"] = warnings
    return ok(data)


def _downloader_for(ctx: _Ctx, max_bytes: int) -> tuple[Any, int]:
    """取下载器：调用方注入的优先，否则按 ``max_bytes`` 现造一个并缓存。

    注入的下载器不改它的属性（那是别人的对象）：如果它的上限与请求的不一致，
    如实把生效值返回给调用方，让"我要求 50MB，实际生效 200MB"这件事可见。
    """
    if ctx.downloader is not None:
        return ctx.downloader, int(getattr(ctx.downloader, "max_bytes", max_bytes) or max_bytes)
    if max_bytes not in ctx.downloaders:
        cfg = dict(ctx.config.get("download") or {})
        cfg["max_bytes"] = int(max_bytes)
        ctx.downloaders[max_bytes] = F.default_downloader(cfg)
    return ctx.downloaders[max_bytes], int(max_bytes)


def _h_download(ctx: _Ctx, url: str, hint: str = "paper", max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES) -> Any:
    """``search.download``：把 URL 下到工作区 downloads/ 下的临时位置。"""
    dest = ctx.downloads_dir
    downloader, effective = _downloader_for(ctx, int(max_bytes))
    try:
        res, elapsed = _timed(downloader.download, url, dest, hint or "paper")
    except Exception as exc:  # noqa: BLE001 - 下载器理论上不抛，但注入的实现可能抛
        return fail(f"下载异常：{type(exc).__name__}: {exc}", kind="download_error", url=url)

    if not res.ok:
        # 「2026-10-16（把 A 做成会应变的智能体）」：这里要把「下载层那一档」
        # 原样带出去（`fetch_kind`）。改前只给一个笼统的 `download_failed`，
        # 细分类（`tls_cert` / `tls_timeout` / `http_403` / `network_error` …）只剩在
        # 自由文本里 ⇒ 「A 读不到"为什么没下到"，也就没法决定"换源还是重试"」。
        # 现场读数（我亲自下的那一轮）：`tls_cert` 类同一个 URL 每次要 122 秒才判死
        # （本机证书/吊销检查），而 `http_403` 是明确不给脚本 ⇒ 两者的正确处置相反
        # （前者换源/改客户端开关，后者直接换源），不看类别就只能在原地耗时间。
        return fail(
            f"下载失败：{res.error}",
            kind="download_failed",
            fetch_kind=res.kind,
            url=url,
            http_status=res.http_status,
            bytes=res.bytes,
            elapsed_s=elapsed,
        )

    path = Path(res.path) if res.path else None
    data: dict[str, Any] = {
        "ok": True,
        "url": url,
        "hint": hint,
        "path": str(path) if path else None,
        "rel_path": _rel_to(path, ctx.workspace) if path else None,
        "dest_dir": str(dest),
        "filename": path.name if path else None,
        "bytes": res.bytes,
        "sha256": res.sha256,
        "http_status": res.http_status,
        "max_bytes_requested": int(max_bytes),
        "max_bytes_effective": effective,
        "elapsed_s": elapsed,
        # 下载器的 ``error`` 在 ok=True 时是软警告（例如 URL 自称 .pdf、
        # 内容却是 text/html）。文件已完整落盘，但绝不能默认当论文抽取 ——
        # 这正是 agent_a 里那条"12.4MB HTML 被当成论文"的教训，必须显式传下去。
        "content_warning": res.error,
        "warnings": [],
    }
    if res.error:
        data["warnings"].append(
            f"内容类型可疑：{res.error}。文件已完整落盘（可作证据），"
            "但**不要**直接当作论文交给 B 抽取；登记时应在 summary/download 里保留这个警告。"
        )
    if effective != int(max_bytes):
        data["warnings"].append(
            f"max_bytes 未生效：请求 {int(max_bytes)}，实际生效 {effective}"
            "（调用方注入的 downloader 自带上限，工具不擅自改别人的对象）。"
        )
    return ok(data)


def _literature_rows(ctx: _Ctx) -> tuple[list[dict], str | None]:
    """读文献表快照（无锁）。返回 ``(行, 读表失败原因)``。

    为什么不用 ``tx``：判重检查与检索候选的比对是纯读、不写盘、不产生事件。
    ``Store`` 的写路径是"临时文件 + os.replace"原子替换，读方只会看到旧的或新的
    完整快照，不会读到半个文件；为一次纯读去抢 A/B 的写锁反而会互相拖慢。

    失败时绝不能返回 `[]`（这是本函数曾经的缺陷）：空表在下游是一个
    有效结论 —— ``search.dedup_check`` 会说"不是重复"、
    ``search.literature`` 会把每条候选标成 ``is_new=True``。
    于是"表坏了"（更隐蔽的假阴性路径）反而比"没配 store"（严格 fail-closed）
    更宽松。三态纪律：读到了 / 读了但表坏了 / 根本没配 store，三者必须分开。
    """
    if ctx.store is None:
        return [], "未配置 store（不是表坏了）"
    try:
        return ctx.store.rows("literature"), None
    except Exception as exc:  # noqa: BLE001 - 表坏了不该让"判重检查"变成崩溃
        return [], f"读 literature 表失败：{type(exc).__name__}: {exc}"


def _h_dedup_check(ctx: _Ctx, title: str, year: int | None = None, doi: str | None = None) -> Any:
    """``search.dedup_check``：不联网，说明"这会不会被判成已有的某篇"。"""
    if ctx.store is None:
        # 不返回"看起来是新的"—— 那是假阴性。没做成的事就说没做成。
        return fail(
            "未配置 store：无法读取既有文献表，任何判重结论都会是假阴性"
            "（「看起来新的」其实可能已经登记过）。请用 register(..., store=store) 构造工具。",
            kind="no_store",
            checked=False,
            keys=D.literature_keys(title, year, doi),
        )

    rows, read_error = _literature_rows(ctx)
    keys = D.literature_keys(title, year, doi)
    if read_error is not None:
        # 与上面那条同样 fail-closed：读了但没读成，任何"不是重复"都是假阴性。
        # 此前这里退化成 `would_be_duplicate=False` + `existing_table_size=0`
        # 且没有任何 warning —— 调用方据此会重复登记同一篇文献。
        return fail(
            f"{read_error} ⇒ 判重**没做成**（不是「没有重复」）。"
            "`would_be_duplicate=False` 在这种前提下是假阴性：表读不出来时，"
            "「看起来是新的」与「已登记过」无法区分。请先修复/重建该表再问。",
            kind="table_unreadable",
            checked=False,
            keys=keys,
            read_error=read_error,
        )

    existing, hit_key = D.find_existing_literature(rows, title, year, doi)

    data: dict[str, Any] = {
        "checked": True,
        "title": title,
        "year": year,
        "doi": D.normalize_doi(doi),
        "keys": keys,
        "primary_key": keys[0] if keys else None,
        "would_be_duplicate": existing is not None,
        "matched_key": hit_key,
        "existing_table_size": len(rows),
        "store_read_error": None,
        "existing": _lit_summary(existing) if existing else None,
        "rule": (
            "三级硬键判重（dedup.find_existing_literature）：① DOI 精确 → ② 标题+年份精确 → "
            "③ 仅标题（年份容差 ±2，兜预印本/正式版的年份漂移）。没有模糊档。"
        ),
    }
    if existing is None:
        # 判"新"的同时给出相似的近邻：判重是确定性规则，相似度不是判据，
        # 但它能解释"为什么这条没被判重"，供人工复核（例如标题写法差异）。
        near: list[dict] = []
        norm = T.normalize(title)
        for row in rows:
            other = T.normalize(row.get("title", ""))
            if not other:
                continue
            score = T.similarity(norm, other)
            if score > 0.0:
                near.append({"lit_id": row.get("lit_id"), "title": row.get("title"), "similarity": round(score, 4)})
        near.sort(key=lambda x: (-x["similarity"], str(x["lit_id"])))
        data["near_misses"] = near[:3]
        data["note"] = (
            "未被判为重复。near_misses 里的相似标题**不是**判重依据（判重只用上面的三级硬键），"
            "仅供人工复核标题写法差异。"
        )
    else:
        data["note"] = f"会命中的键：{hit_key}。登记的既有行见 existing。"
    return ok(data)


def _adopt_file(ctx: _Ctx, lit_id: str, raw_path: str | None, warnings: list[str]) -> tuple[str | None, int, str | None]:
    """把本地文件收编进 ``library/<lit_id>/``，返回 ``(相对路径, 字节数, sha256)``。

    三种情形分别处理：
    1. 已在 ``library/`` 内 ⇒ 原地保留（可能已被 B 引用过，移动会打断追溯）；
    2. 在 library 之外（如 ``downloads/``）⇒ 移动进 ``library/<lit_id>/``；
    3. 文件不存在 ⇒ ``path`` 置 ``None`` 并记 warning，不编造路径。
    """
    if not raw_path:
        return None, 0, None
    if ctx.store is None:
        # 收编的目标是 library/，没有 store 就没有 library；调用方已在 _h_register 挡掉。
        warnings.append("未配置 store，无法收编文件，path 置空")
        return None, 0, None

    p = Path(raw_path)
    if not p.is_absolute():
        # 相对路径优先按 library/ 解释（表里存的就是这个坐标系），
        # 不存在再按 workspace 解释（例如 "downloads/xxx.pdf"）。
        candidate = ctx.store.library / p
        p = candidate if candidate.exists() else (ctx.workspace / p)
    try:
        p = p.resolve()
    except OSError as exc:
        warnings.append(f"路径解析失败，path 置空：{raw_path!r}（{exc}）")
        return None, 0, None

    if not p.exists() or not p.is_file():
        warnings.append(f"path 指向的文件不存在或不是普通文件，path 置空：{p}")
        return None, 0, None

    lib = ctx.store.library.resolve()
    try:
        rel = p.relative_to(lib).as_posix()
        return rel, p.stat().st_size, _sha256_of(p)
    except ValueError:
        pass  # 不在 library 内 → 需要收编

    target_dir = lib / lit_id
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        warnings.append(f"无法创建 {target_dir}，path 置空：{exc}")
        return None, 0, None

    target = target_dir / p.name
    if target.exists():
        # 同名文件已存在：加短哈希后缀，绝不覆盖（覆盖会毁掉已经建立的引文定位）
        target = target_dir / f"{p.stem}-{T.short_hash(str(p), 8)}{p.suffix}"
    try:
        shutil.move(str(p), str(target))
    except Exception as exc:  # noqa: BLE001 - 跨盘/权限/占用都可能失败
        warnings.append(f"收编文件失败（{type(exc).__name__}: {exc}），path 置空；原文件仍在 {p}")
        return None, 0, None
    rel = f"{lit_id}/{target.name}"
    return rel, target.stat().st_size, _sha256_of(target)


def _h_ingest_local(ctx: _Ctx, books_dir: str, pattern: str = "*.pdf",
                     limit: int | None = None, max_bytes: int = 25165824,
                     dry_run: bool = False) -> Any:
    """``search.ingest_local``：不联网，把一个本地目录登记进书架。

    provenance 三件事如实写（`draft/28` §191）：事务 `actor="agent-A"`、
    请求行 `submitted_by="unknown"`（A 不在 `SUBMITTER_DEFAULT_PRIORITY` 里 ——
    A 不提交检索需求）、正文里那句"谁提供的"写成"由 agent-A 从一个本地目录登记"。
    借 `human` 会把"这篇文献从哪来"这条链说成假话，而那正是它存在的理由。
    """
    if ctx.store is None:
        return fail(
            "未配置 store：没有库就没有书架可登记（不是「目录里没有书」）。",
            kind="no_store", recorded=False,
        )
    from ..locallib import ingest_directory

    base = Path(books_dir)
    target = base if base.is_absolute() else (ctx.workspace / base)
    if not target.is_dir():
        return fail(f"目录不在盘上：{target}", kind="io_error", recorded=False,
                    books_dir=str(target))
    try:
        report = ingest_directory(
            ctx.store, target, limit=limit, pattern=pattern or "*.pdf",
            max_bytes=int(max_bytes), dry_run=bool(dry_run),
            note=f"agent-A 登记本地文献目录（{target}）",
            actor="agent-A", submitted_by="unknown",
            origin_note="由 agent-A 从一个本地目录登记",
        )
    except Exception as exc:  # noqa: BLE001 —— 登记失败如实报，不编"登记成功"
        return fail(f"登记没做成：{type(exc).__name__}: {exc}", kind="io_error", recorded=False)
    data = report.to_dict()
    counts = dict(data.get("counts") or {})
    data["count"] = len(data.get("books") or [])
    # 计数直接取报告自己的 `counts`（一份实现）：另算一遍会让"谁在数"有两处口径，
    # 而两处一旦漂移，读的人无法判断哪一个才是"这次登记的结果"。
    data["ingested"] = counts.get("ingested", 0)
    data["already_present"] = counts.get("already_present", 0)
    data["unreadable"] = counts.get("unreadable", 0)
    data["skipped"] = counts.get("skipped_limit", 0) + counts.get("skipped_too_large", 0)
    data["provenance"] = {"actor": "agent-A", "submitted_by": "unknown",
                          "origin_note": "由 agent-A 从一个本地目录登记",
                          "note": "A 不是检索请求的提交方；这条链如实写「谁登记的」"}
    # 成功支写成字面量键表：让"返回了哪些键"静态可见（与论文包那几件同一条纪律；
    # `tests/test_tools_branch_key_sets.py` 抓的就是"看不清的成功支"）。
    # 键与 `returns=` 声明逐字一致；值仍取自登记的读数（不重算）。
    return ok({
        "root": data["root"], "dry_run": data["dry_run"], "limit": data["limit"],
        "books": data["books"], "count": data["count"], "ingested": data["ingested"],
        "already_present": data["already_present"], "skipped": data["skipped"],
        "unreadable": data["unreadable"], "provenance": data["provenance"],
    })


def _h_register(
    ctx: _Ctx,
    title: str,
    type_code: str,
    summary: str,
    path: str | None = None,
    doi: str | None = None,
    year: int | None = None,
    request_id: str | None = None,
) -> Any:
    """``search.register``：走 ``tx`` + ``alloc_id("lit")`` 建一条 literature 行。

    先判重再建行：命中已有行时复用它的代号，只追加 ``source_request_ids``。
    这不是"偷懒"——同一篇文献出现两个代号会污染全部下游溯源（``lit_id`` 是
    关系表、引文校验、报告引用的共同锚点）。
    """
    if ctx.store is None:
        return fail("未配置 store：无法建行。请用 register(..., store=store) 构造工具。", kind="no_store")

    code = (type_code or "").strip().upper()
    if code not in S.LIT_TYPES:
        return fail(
            f"type_code 必须是 GB/T 7714 类型码 {S.LIT_TYPES} 之一，收到 {type_code!r}",
            kind="param_constraint",
            valid=list(S.LIT_TYPES),
        )
    if not (title or "").strip():
        return fail("title 不能为空", kind="param_constraint")

    warnings: list[str] = []
    keys = D.literature_keys(title, year, doi)

    with ctx.store.tx("literature", "search_requests", actor=ctx.actor, note="search.register") as tx:
        existing, hit_key = D.find_existing_literature(tx.rows("literature"), title, year, doi)
        if existing is not None:
            updated = _link_request(tx, request_id, existing.get("lit_id"), warnings)
            # 判重命中支与"新建成功"支返回同一套 13 个键（`G-23`）：两条分支给不同
            # 键集合时，`returns=` 只能描述一支，另一支永远是声明看不见的缺口，
            # 调用方得先判 `created` 才能安全读 `lit_id`。本支的 `matched_key` 是
            # 判重真的命中的那个键，新建支没有这个事实、如实给 `None`。
            # 分支无关的字段给诚实的 `None`/`False`（不许用 `""`/`0` 冒充"没有"）。
            return ok(
                {
                    "created": False,
                    "reason": "duplicate",
                    "lit_id": existing.get("lit_id"),
                    "matched_key": hit_key,
                    "existing": _lit_summary(existing),
                    "keys": keys,
                    "request_linked": updated,
                    "path": None,
                    "dedup_key": existing.get("dedup_key"),
                    "type_code": existing.get("type"),
                    "processed": bool(existing.get("processed")),
                    "download": None,
                    "warnings": warnings + [
                        "判重命中：复用既有 lit_id，未新建行（同一篇文献两个代号会污染下游溯源）。"
                    ],
                }
            )

        lit_id = tx.alloc_id("lit")
        rel_path, size, sha = _adopt_file(ctx, lit_id, path, warnings)

        dl: dict[str, Any]
        if rel_path:
            # 内容确实在本地（我们刚收编并算了哈希），故记 ok；http 元数据未知就留 None，
            # 不编造状态码。B 只看 status/path，不会被这里的 None 影响。
            dl = {"status": "ok", "http_status": None, "bytes": size, "sha256": sha, "error": None}
        else:
            dl = {
                "status": "skipped",
                "http_status": None,
                "bytes": 0,
                "sha256": None,
                "error": "no_local_path",
            }

        row = S.Literature(
            lit_id=lit_id,
            title=title.strip(),
            type=code,
            summary=T.clip(summary or "", 1200),
            path=rel_path,
            processed=False,  # B 负责置 true
            source_request_ids=[request_id] if request_id else [],
            dedup_key=keys[0] if keys else f"title:{T.normalize(title)}|*",
            doi=D.normalize_doi(doi),
            year=year,
            authors=[],
            venue=None,
            language=None,
            added_at=S.now_iso(),
            download=dl,
        )
        # `validate()` 必须包住：它会抛 `ValueError`，而这里在工具 handler 内。
        # 不包的话异常会逃出工具层，被 `base.py:381-382` 兜成一个没有类型信息的
        # `kind="unexpected"`（脚本模式直接调 handler 时更是直接抛）。
        # 同一调用类型在下面 `_link_request`（`:862-871`）里被显式 guard 了 ——
        # 说明这个函数会抛是已知事实，这里的遗漏只是没走完。
        try:
            row.validate()
        except ValueError as exc:
            return fail(
                f"search.register：构造出的 literature 行**没通过 schema 校验**：{exc}。"
                f"（字段：lit_id={lit_id!r}、title={title.strip()!r}、type={code!r}、"
                f"doi={D.normalize_doi(doi)!r}、year={year!r}、path={rel_path!r}）"
                "⇒ 本行**未写入**（同一事务里的分配号也会随回滚作废）。",
                kind="validation_error",
                lit_id=lit_id,
                fields={
                    "title": title.strip(),
                    "type": code,
                    "doi": D.normalize_doi(doi),
                    "year": year,
                    "path": rel_path,
                    "download": dl,
                },
            )
        rowd = row.to_dict()
        # `_keys` 是诊断字段（记录全部候选键），dedup._row_keys 会读它 ——
        # 与 agent_a 的写入保持一致，否则将来"只认 dedup_key"会让判重悄悄失效。
        rowd["_keys"] = keys
        tx.upsert("literature", rowd, note="search.register")
        linked = _link_request(tx, request_id, lit_id, warnings)

    return ok(
        {
            "created": True,
            "lit_id": lit_id,
            "path": rel_path,
            "dedup_key": rowd["dedup_key"],
            "keys": keys,
            "type_code": code,
            "processed": False,
            "download": dl,
            "request_linked": linked,
            "warnings": warnings,
            # 判重命中支才有的三个键，这里如实给 None/False（`G-23`：两条分支同一套
            # 13 键，分支无关处给诚实的 None）。`matched_key` 是判重命中的那个键，
            # 新建支根本没有"命中"这件事 —— 用 None 说"没有"，而不是不出现；
            # `reason` 只在 duplicate 支有意义，`existing` 只在命中时才有那一行。
            "matched_key": None,
            "reason": None,
            "existing": None,
        }
    )


def _link_request(tx: Any, request_id: str | None, lit_id: str | None, warnings: list[str]) -> bool:
    """把 lit_id 追加到请求的 ``result_lit_ids``（保持升序去重）。

    这一步是"请求→文献"的可追溯链。请求不存在时只记 warning 不失败：
    工具调用的价值在于把文献登记下来，链路缺失是次要问题，不该因此整笔回滚。
    """
    if not request_id or not lit_id:
        return False
    req = tx.find("search_requests", request_id=request_id)
    if req is None:
        warnings.append(f"request_id={request_id} 不在 search_requests 表里，未建立来源关联")
        return False
    ids = set(req.get("result_lit_ids") or [])
    ids.add(lit_id)
    req["result_lit_ids"] = S.sorted_unique(ids)
    try:
        # 先校验再写：请求行可能处于"done=true 但三样凭据都没有"的历史脏状态，
        # 那种行本该由 rebuild/verify 处理，不该被本工具的写入顺手"修好"或炸掉。
        S.row_from_dict("search_requests", req).validate()
    except ValueError as exc:
        warnings.append(f"request_id={request_id} 的行校验未通过，未追加 result_lit_ids：{exc}")
        return False
    tx.upsert("search_requests", req, note="search.register")
    return True


# --------------------------------------------------------------------------- 注册


def _pick_workspace(
    workspace: str | Path | None,
    workspace_root: str | Path | None,
    root: str | Path | None,
    store: Store | None,
) -> Path:
    """确定工作区根目录。

    接受 ``workspace`` / ``workspace_root`` / ``root`` 三个别名：``tools/__init__.py``
    的装配器按固定依赖名（``store`` / ``root`` / ``workspace_root``）反射注入，
    只认一个名字的话，"调用方显式指定的沙箱根"就会静默失效（退回 store.root），
    这属于"配置改了却毫无效果"的静默故障。
    """
    for cand in (workspace, workspace_root, root):
        if cand is not None:
            return Path(cand)
    return Path(store.root) if store is not None else Path.cwd()


@tool(
    "search.providers",
    "列出可用检索源并**真实探测**各自是否可用（发一次极小请求；ABFLOW_SKIP_NETWORK=1 时标为未探测而不是猜）。",
    {"type": "object", "properties": {}, "additionalProperties": False},
    # external=egress：探测会给每个网络源发一次真实 HTTP 请求（见模块 docstring 第 3 条）。
    # 声明成 read + external=none 会让这个工具绕过审批，而它确实在对外发请求。
    side_effect="read",
    roles=("A",),
    # 键名逐个从 `_h_providers` 的 ok(...) 读出（该分支不需要真跑：
    # 数据字典在源码里逐字写着）。providers[] 每项是
    # {'name','available','status','reason','latency_s','evidence'}。
    returns=(
            "{'skip_network','providers','available','unavailable','unverified',"
            "'summary','default_provider'}；"
            "providers[] 每项是 {'name','available','status','reason','latency_s','evidence'}"
            ),
    tags=("search", "provider"),
    external="egress",
)
def _search_providers(ctx):
    """search.providers 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（ctx）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return _h_providers(ctx)

@tool(
    "search.shelf",
    "**不联网**：列出工作区里**全文在盘上**的文献（**本地书架**）—— 离线能引用哪些只看得到它。可按题名/路径筛。",
    {
           "type": "object",
           "properties": {
            "query": {"type": "string", "maxLength": 200,
                      "description": "可选：按题名/路径子串过滤（大小写不敏感）"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            "lit_id": {"type": "string", "maxLength": 40},
           },
           "required": [],
           "additionalProperties": False,
           },
    side_effect="read",
    roles=("A", "C", "H"),
    returns=(
            "{'count','rows_total','have_path','missing_files','local_ingest','downloaded',"
            "'truncated','books','note','query','filtered_out'}；"
            "books[] 每项是 {'lit_id','title','path','abs_path','bytes','pages',"
            "'has_text_layer','origin','sha256_12'}（origin ∈ local_ingest/downloaded）；"
            "失败：ok=False + kind(no_store/table_unreadable) + counted=False"
            "（**没数成**，不是「书架是空的」）"
            ),
    tags=("search", "offline", "shelf"),
)
def _search_shelf(ctx, limit=None, lit_id="", query=""):
    """search.shelf 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（ctx）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return _h_shelf(ctx, limit, lit_id, query)

@tool(
    "search.local",
    "**不联网**：在本地书架的全文里按主题取最相关的一页与**逐字摘录**（带 lit_id 与页码，引文回验用得上）。",
    {
           "type": "object",
           "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 400},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            "max_chars": {"type": "integer", "minimum": 200, "maximum": 8000},
            "lit_id": {"type": "string", "maxLength": 40},
            "max_books": {"type": "integer", "minimum": 1, "maximum": 500},
           },
           "required": ["query"],
           "additionalProperties": False,
           },
    side_effect="read",
    roles=("A", "C", "H"),
    returns=(
            "{'query','searched','count','candidates','scanned','skipped_no_file',"
            "'unreadable','no_text_layer','hits','elapsed_s','note'}；"
            "hits[] 每项是 {'lit_id','title','path','sha256_12','page','excerpt','pages',"
            "'score'}（按 score 降序；score 是 locallib.page_scores 的同一份口径）；"
            "失败：ok=False + kind(no_store/table_unreadable) + searched=False"
            "（**没做成检索**，不是「没有命中」）"
            ),
    tags=("search", "offline", "local"),
)
def _search_local(ctx, query, limit=5, max_chars=1200, lit_id="", max_books=None):
    """search.local 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（ctx）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _h_local(
               ctx, query, limit, max_chars, lit_id, max_books
               )
    )

@tool(
    "search.download",
    "把候选的 `pdf_url` 下到工作区 downloads/（同名不覆盖；落盘后给 sha256）。**失败先读 `fetch_kind`**：`tls_cert`/`"
    "http_403` ⇒ 换源；`tls_timeout` ⇒ 至多再试一次；`network_error` ⇒ 可重试；`all_sources_failed` ⇒ "
    "这条路走完了。`ok=True` 但 `content_warning=content_type_mismatch` ⇒ 落地页，别当全文。",
    {
           "type": "object",
           "properties": {
            "url": {"type": "string", "minLength": 8, "maxLength": 2000},
            "hint": {"type": "string", "maxLength": 200},
            "max_bytes": {"type": "integer", "minimum": 1024, "maximum": 2_000_000_000},
           },
           "required": ["url"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=("A",),
    # 键名逐个从 `_h_download` 的 data 字典读出（没真跑过：需要一次
    # 成功的真实下载；本轮观测到的是 fail 分支 —— 如实留痕）。
    returns=(
            "{'ok','url','hint','path','rel_path','dest_dir','filename','bytes','sha256',"
            "'http_status','max_bytes_requested','max_bytes_effective','elapsed_s',"
            "'content_warning','warnings'}；"
            "失败：ok=False + kind(download_failed/download_error) + "
            "fetch_kind（下载层那一档：tls_cert/tls_timeout/http_403/http_401/"
            "network_error/timeout/all_sources_failed …，见 fetch.ERROR_KINDS）"
            ),
    tags=("search", "download"),
    external="egress",
)
def _search_download(ctx, url, hint="paper", max_bytes=DEFAULT_MAX_DOWNLOAD_BYTES):
    """search.download 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（ctx）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _h_download(
               ctx, url, hint, max_bytes
               )
    )

@tool(
    "search.dedup_check",
    "**不联网**：按三级硬键（DOI → 标题+年 → 仅标题带年容差）说明『这条会不会被判成已有的某篇』，并给出会命中的键。",
    {
           "type": "object",
           "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 600},
            "year": {"type": "integer", "minimum": 1000, "maximum": 2999},
            "doi": {"type": "string", "maxLength": 300},
           },
           "required": ["title"],
           "additionalProperties": False,
           },
    side_effect="read",
    roles=("A",),
    # 键名从一个真实调用读出（`_h_dedup_check`）：`existing` 命中时是既有行的
    # 摘要字典，未命中时是 None（键仍在）。
    returns=(
            "{'checked','title','year','doi','would_be_duplicate','matched_key','keys',"
            "'existing','near_misses','primary_key','rule','note','existing_table_size',"
            "'store_read_error'}；"
            "失败：ok=False + kind(no_store/table_unreadable) + checked=False（**没有做成判重**，不是「没有重复」）"
            ),
    tags=("search", "dedup"),
)
def _search_dedup_check(ctx, title, year=None, doi=None):
    """search.dedup_check 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（ctx）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return _h_dedup_check(ctx, title, year, doi)

@tool(
    "search.ingest_local",
    "**不联网**：把本地目录里的 PDF 登记进书架（按内容 sha256 幂等；dry_run 只算不写）。provenance 如实写「由 A 登记」，不借「人直接提供」。",
    {
           "type": "object",
           "properties": {
            "books_dir": {"type": "string", "minLength": 1, "maxLength": 1000,
                          "description": "本地目录（绝对路径或相对工作区）"},
            "pattern": {"type": "string", "maxLength": 40},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            "max_bytes": {"type": "integer", "minimum": 1024, "maximum": 2_000_000_000},
            "dry_run": {"type": "boolean",
                        "description": "只算 hash 与清单，不写盘、不进事务"},
           },
           "required": ["books_dir"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=("A",),
    returns=(
            "{'root','dry_run','limit','books','count','ingested','already_present','skipped',"
            "'unreadable','provenance'}；"
            "books[] 每项是 {'source','library_name','bytes','sha256','status','note','lit_id',"
            "'request_id','pages','has_text_layer'}；失败：ok=False + kind(no_store/io_error) "
            "+ recorded=False（**没登记成**，不是「目录里没有书」）"
            ),
    tags=("search", "offline", "ingest"),
)
def _search_ingest_local(ctx, books_dir, pattern="*.pdf", limit=None, max_bytes=25165824, dry_run=False):
    """search.ingest_local 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（ctx）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _h_ingest_local(ctx, books_dir, pattern, limit,
                               max_bytes, dry_run)
    )

@tool(
    "search.register",
    "登记一条文献（literature 行，processed=false）：先判重，命中复用既有 lit_id；未命中则 alloc_id('lit') 并收编进 "
    "library/<lit_id>/。",
    {
           "type": "object",
           "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 600},
            "type_code": {"type": "string", "enum": list(S.LIT_TYPES)},
            "summary": {"type": "string", "maxLength": 20000},
            "path": {"type": "string", "maxLength": 1000},
            "doi": {"type": "string", "maxLength": 300},
            "year": {"type": "integer", "minimum": 1000, "maximum": 2999},
            "request_id": {"type": "string", "maxLength": 100},
           },
           "required": ["title", "type_code", "summary"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=("A",),
    # 键名从一个真实调用读出（`search.register`）。`created=true` 与
    # `created=false`（判重命中）两支返回同一套 13 个键：判重支的
    # `matched_key` 是命中的那个键、新建支为 `None`，新建支的
    # `dedup_key`/`path`/`download` 在判重支为 `None` —— 调用方不必先判
    # `created` 才能安全读键（`G-23`）。
    returns=(
            "{'created','reason','lit_id','matched_key','existing','keys','request_linked',"
            "'path','dedup_key','type_code','processed','download','warnings'}"
            "（created=false 表示判重命中，复用了既有 lit_id；两支键集合相同）"
            ),
    tags=("search", "register"),
)
def _search_register(ctx, title, type_code, summary, path=None, doi=None, year=None, request_id=None):
    """search.register 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（ctx）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _h_register(
               ctx, title, type_code, summary, path, doi, year, request_id
               )
    )

# --------------------------------------------------------------------------- 待新增文献列表
#
# 业主 2026-10-20 口径（逐条落在这七件工具上）：
#   ① 一次委托正式入库至多 10 篇（`lit.admit` / `lit.admit_all` 挡住；广搜本身可以超过 10 条）；
#   ② 入库前要审内容 —— 即使只拿到 3 篇也要逐篇过（`lit.stage_list` 看得到每一条）；
#   ③ 内容不好可以撤掉换一篇：撤 = 槽位置空 + 写理由（`lit.stage_withdraw`），
#      序号不复用、记录不物理删除；拒收走 `lit.stage_reject`；
#   ④ 与本地库重叠度高的：只有给了 `new_content` 才许入库（`lit.overlap_check` 的读数）；
#   ⑤ 待新增列表支持增/删/查、可多次追加（第 2 批序号接着第 1 批）；
#   ⑥ 列表按「委托」重置（默认视图只看当前委托）+ 一键迁移 `lit.admit_all`（迁移后清空、
#      写委托报告 `reports/lit-<request_id>.md`：已入库一块 + 未入库（含受控理由）一块）。
#
# 判据的真身全在 `agentflow/litstage.py`（上限、阈值、状态机、报告结构只有那一处）；
# 这七件只做两件事：把参数校验交给 schema、把结论翻成 `ToolResult`。


def _stage_fail(exc: Exception) -> Any:
    """把 `litstage` 的受控错翻成工具层的 `fail`（模型据此能改）。"""
    from ..litstage import LitStageError

    if isinstance(exc, LitStageError):
        return fail(str(exc), kind=exc.kind, **dict(exc.detail or {}))
    if isinstance(exc, StoreError):
        return fail(f"待新增列表这次没读成/没写成：{type(exc).__name__}: {exc}",
                    kind="store_error")
    return fail(f"{type(exc).__name__}: {exc}", kind="unexpected")


#: "本次没有全文"这一档的标记值（写进 `literature.download.fulltext`，不新增列）。
#:
#: 为什么它必须是一个受控取值而不是一句散文：B 的读侧要按它把"这一篇有定位符、
#: 只是这次没下字节"与"这一篇从哪来都不知道"分开（见 `agent_b.run_once`
#: 的 acquire 段）。散文只能被人读，机器读不出两档的差别。
NO_FULLTEXT_THIS_TIME = "no_fulltext_this_time"


def _mark_candidate_locator(ctx: _Ctx, lit_id: str, row: Mapping[str, Any]) -> bool:
    """把候选行的 url 写进 literature 行的 download 栏，并标明"本次无全文"。

    为什么必须做（审计读数）：一键迁移原来这样登记 —— `_h_register(..., path=None)`，
    于是 literature 行上 `path=null`、`download={"status":"skipped",
    "error":"no_local_path"}`。B 领取到这样一行只能写 `no_local_file`：这一篇
    从哪来、还能去哪取，盘上一个字都没有。候选行上本来就有 `url`（provider
    给的检索/落地链接），它是"这篇在哪"的唯一证据，不落下来就等于丢掉了。

    为什么写 download 栏而不是新加一列：`download` 是既有字段（`schema` 是禁改区，
    列不许加），它本来就是"这一篇的字节从哪来、到了没有"的落点。写入的键：
    `url`（定位符）、`fulltext`（本次没拿到全文的标记）、`error`、`note`。

    已登记行如果真的有本地全文（`path` 非空），一律不碰："本次无全文"不许
    覆盖一个真的有字节的行。返回是否真的写了（幂等：同一个 url 且已标过就不写）。
    """
    url = str(row.get("url") or "").strip()
    if not url or not lit_id or ctx.store is None:
        return False
    with ctx.store.tx("literature", actor=ctx.actor, note="search.register.locate") as tx:
        got = tx.find("literature", lit_id=lit_id)
        if got is None or got.get("path"):
            return False
        dl = dict(got.get("download") or {})
        if dl.get("url") == url and dl.get("fulltext") == NO_FULLTEXT_THIS_TIME:
            return False
        dl.setdefault("status", "skipped")
        have = str(dl.get("url") or "").strip()
        if have and have != url:
            # 行上已经有一个不同的定位符（同一篇由另一个源登记过）：不丢它 ——
            # 两个 url 都是真的，覆盖等于让"上一次登记的是哪个"不可查。
            dl["url_previous"] = have
        dl["url"] = url
        dl["fulltext"] = NO_FULLTEXT_THIS_TIME
        dl["error"] = dl.get("error") or NO_FULLTEXT_THIS_TIME
        dl["note"] = ("本次无全文：只登记了候选源给出的定位链接（url 这一格），"
                      "没有下载字节；要全文请按它重取")
        got["download"] = dl
        S.Literature(**{k: got[k] for k in got
                        if k in S.Literature.__dataclass_fields__}).validate()
        tx.upsert("literature", got, note="search.register.locate")
    return True


def _registrar_from_candidate(ctx: _Ctx, row: Mapping[str, Any]) -> dict:
    """把一条待新增候选走现有的 `search.register` 登记路径落成 literature 行。

    两条入口（`lit.admit` 逐条入库与 `lit.admit_all` 一键迁移）共用这一份。
    它们原来各有一段逐字相同的闭包：改一处漏一处，"一键迁移出来的行没有
    定位栏、B 一用就是 unreadable"就会在原地复发。

    登记之后补写定位栏（`_mark_candidate_locator`）：登记路径自己只认
    `path`（library 下的相对路径），而候选行手上只有 url —— 两件事分开写，
    谁也不冒充谁。
    """
    res = _h_register(
        ctx,
        title=str(row.get("title") or ""),
        type_code=str(row.get("type_code") or "Z"),
        summary=str(row.get("summary") or ""),
        path=None,
        doi=row.get("doi"),
        year=row.get("year"),
        request_id=None,
    )
    if not res.ok:
        return {"lit_id": None, "reason": res.error}
    data = dict(res.data or {})
    _mark_candidate_locator(ctx, str(data.get("lit_id") or ""), row)
    return data


def _h_lit_overlap_check(ctx: _Ctx, title: str, doi: str | None = None) -> Any:
    """``lit.overlap_check``：「不联网」，说明"这一条与本地库重叠多少、要不要 new_content"。
    
    口径（与 `litstage.overlap_check` 「同一份实现」，这里只补两句读数）：
    
    - 「DOI 完全相同 ⇒ 视为重复」（`duplicate=True`）：同一篇文献说不出"新内容"，所以给不给 `new_content` 都不入库；- 否则按「标题词
    集 Jaccard」 算重叠度，阈值 ``OVERLAP_HIGH_JACCARD = 0.60``（取值依据见 
    `litstage.OVERLAP_HIGH_JACCARD` 的 docstring）：≥ 0.60 ⇒ `requires_new_content=True`，调用方必
    须给 `new_content`。
    
    三态：未配置 store ⇒ `fail(kind="no_store")` + `checked=False`（「不是」"没有重叠"）；表读不出来 ⇒ 
    `fail(kind="store_error")`（同样不是"没有重叠"）。
    """
    from ..litstage import overlap_check

    if ctx.store is None:
        return fail(
            "未配置 store：读不到本地库 ⇒ 重叠**没查**（不是「没有重叠」）。"
            "请用 register(..., store=store) 构造工具。",
            kind="no_store", checked=False,
        )
    try:
        got = overlap_check(ctx.store, title, doi)
    except StoreError as exc:
        return fail(f"本地库读不出来 ⇒ 重叠**没查成**（不是「没有重叠」）：{exc}",
                    kind="store_error", checked=False)
    # 字面量键表（`tests/test_tools_branch_key_sets.py` 的"看不清的成功支"那一档）：
    # 键集合必须静态可见，所以这里逐键搬，不用 `**got`。
    return ok({
        "title": title,
        "doi": D.normalize_doi(doi),
        "checked": got.get("checked"),
        "duplicate": got.get("duplicate"),
        "overlap_score": got.get("overlap_score"),
        "overlap_kind": got.get("overlap_kind"),
        "overlap_with": got.get("overlap_with"),
        "requires_new_content": got.get("requires_new_content"),
        "reason": got.get("reason"),
    })


def _h_lit_stage_add(
    ctx: _Ctx,
    request_id: str,
    entries: Iterable[Mapping[str, Any]],
    batch: int | None = None,
) -> Any:
    """``lit.stage_add``：把候选「追加」进本次委托的待新增列表（一次可追加任意条，>10 也允许）。

    为什么暂存不设 10 的上限：上限管的是「入库」（业主口径 ①）；"广搜 30 条、精选 8 条入库"
    是正路，把上限提前到暂存这一档会让它直接走不通。

    槽位号由 `store.alloc_id("candidate")` 发：「只增不复用」。所以第 2 批的序号接着
    第 1 批往下排（12 条 + 3 条 = 1..15；中间被撤掉的号空着，不会被再发一次）。

    `request_id` 「必须给」（业主 2026-10-20 第 1 条：列表按委托重置）—— 换一个
    `request_id` 就是"从空列表开始下一次委托"，旧委托的行不删、也不参与本次筛选。
    """
    from ..litstage import stage_entries

    try:
        got = stage_entries(ctx.store, entries, request_id=request_id, batch=batch,
                            actor=ctx.actor)
    except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
        return _stage_fail(exc)
    return ok({
        "request_id": got["request_id"],
        "batch": got["batch"],
        "count": got["count"],
        "staged": got["staged"],
    })


def _h_lit_stage_list(
    ctx: _Ctx,
    request_id: str | None = None,
    batch: int | None = None,
    status: str | None = None,
) -> Any:
    """``lit.stage_list``：按委托 / batch / status 查待新增列表（「空槽位照样在列表里」）。

    「默认视图只看当前委托」（业主 2026-10-20 第 1 条）：`request_id` 不给 ⇒ 取
    "最近一次暂存的那次委托"；要看旧委托请显式给号，`request_id="*"` 表示全查。

    `status` 五选一：`pending` / `withdrawn` / `rejected` / `admitted` / `cleared`（不传 = 全查）。
    `withdrawn` 的那些行就是"空槽位"：序号不复用、题名与 `withdrawn_reason` 都留着 ——
    于是"第 3 号被撤了哪一篇、为什么"查得出来（这正是"撤掉 ≠ 删掉"的落点）。
    """
    from ..litstage import list_candidates

    try:
        got = list_candidates(ctx.store, request_id=request_id, batch=batch, status=status)
    except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
        return _stage_fail(exc)
    return ok({
        "request_id": got["request_id"],
        "current_request_id": got["current_request_id"],
        "batch": got["batch"],
        "status": got["status"],
        "count": got["count"],
        "counts": got["counts"],
        "gaps": got["gaps"],
        "rows": got["rows"],
        "total_all_delegations": got["total_all_delegations"],
        "note": got["note"],
    })


def _h_lit_stage_withdraw(ctx: _Ctx, slot: str, reason_code: str, note: str = "") -> Any:
    """``lit.stage_withdraw``：撤掉某一槽 —— 「不改序号、不物理删除」，写理由。

    `reason_code` 必须是受控取值（`schema.CANDIDATE_REASON_CODES`：例如
    `withdrawn_by_reviewer`）；`note` 是给人看的那一句（可空，空则用理由码的标签顶上）。
    撤掉之后可以再 `lit.stage_add` 补位，但新条进的是「新序号」（旧号不复用）。
    """
    from ..litstage import withdraw

    try:
        got = withdraw(ctx.store, slot, reason_code, note, actor=ctx.actor)
    except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
        return _stage_fail(exc)
    return ok({
        "slot": got["slot"],
        "status": got["status"],
        "reason_code": got["reason_code"],
        "reason": got["reason"],
        "title": got["title"],
        "request_id": got["request_id"],
        "batch": got["batch"],
    })


def _h_lit_stage_reject(ctx: _Ctx, slot: str, reason_code: str, note: str = "") -> Any:
    """``lit.stage_reject``：审内容后拒收 —— 写 `reject_reason` + 受控 `reason_code`，保留行。

    `reason_code` 用 `rejected_off_topic` / `rejected_low_quality` /
    `overlap_without_new_content` / `duplicate_doi` 这几档（见 `schema.CANDIDATE_REASON_CODES`）。
    """
    from ..litstage import reject

    try:
        got = reject(ctx.store, slot, reason_code, note, actor=ctx.actor)
    except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
        return _stage_fail(exc)
    return ok({
        "slot": got["slot"],
        "status": got["status"],
        "reason_code": got["reason_code"],
        "reason": got["reason"],
        "title": got["title"],
        "request_id": got["request_id"],
        "batch": got["batch"],
    })


def _h_lit_admit(
    ctx: _Ctx,
    slots: Iterable[str] | None = None,
    items: Iterable[Mapping[str, Any]] | None = None,
    request_id: str | None = None,
    batch: int | None = None,
    new_content: str = "",
    overlap_ok: bool | None = None,
) -> Any:
    """``lit.admit``：正式入库（逐条）—— 「条数上限 + 重叠检查」都过了才走现有登记路径。
    ## 两个上限（业主口径 ①，超了「整笔拒绝」）
    - 本次调用 ≤ ``MAX_ADMIT_PER_CALL = 10`` 条；- 该委托累计已入库 + 本次 ≤ ``MAX_ADMIT_PER_DELEGATION = 10`` 条。
    ## 逐条拒收（业主口径 ②④）
    - `status != "pending"`（已撤 / 已拒 / 已入库 / 已清空）⇒ 拒；- DOI 与本地库某一行「完全相同」 ⇒ 视为重复，拒（这一档 `new_content` 救不了）；- 标题词集
    Jaccard ≥ 0.60 且「没有」 `new_content` ⇒ 拒（行上写的 `new_content` 优先，`items[].new_content` / 调用级 `new_content` 兜底）。
    `overlap_ok=True` 「不替代」 `new_content`：它只如实记下"调用方表过态"，真正的放行仍要有那句新内容。`overlap_ok=False` 则直接拒这一条。
    ## 入库走的是现有路径
    registrar 就是 `search.register` 的 handler（`_h_register`：判重 → `alloc_id("lit")`→ 落 `literature` 行 → 收编文件）。本工具里没有
    一处直接写 `literature` ——"绕开登记路径"在结构上做不到（判据见 `tests/test_search_tools_stage_admit.py`）。
    「它不清空列表」：清空是一次委托的收尾动作，属于 `lit.admit_all`。
    """
    from ..litstage import LitStageError, admit as _admit

    if ctx.store is None:
        return fail("未配置 store：入不了库（不是「都重复了」）", kind="no_store")

    wanted: list[str] | None
    payload: dict[str, dict] = {}
    if items is not None:
        wanted = []
        for raw in items:
            slot = str((raw or {}).get("slot") or "").strip()
            if not slot:
                return fail("items 里有一条没有 slot", kind="bad_item")
            if slot not in wanted:
                wanted.append(slot)
            payload[slot] = {
                "new_content": str((raw or {}).get("new_content") or "").strip(),
                "overlap_ok": (raw or {}).get("overlap_ok"),
            }
    else:
        wanted = [str(s).strip() for s in (slots or []) if str(s or "").strip()] or None
        if wanted:
            for slot in wanted:
                payload[slot] = {"new_content": str(new_content or "").strip(),
                                 "overlap_ok": overlap_ok}
    if wanted is None and batch is None:
        return fail("admit 要么给 slots / items，要么给 batch", kind="no_target")

    # 每条自带的 `new_content` / `overlap_ok` 先落回候选行：这样它们在 `lit.stage_list`
    # 里查得到（"这一篇凭什么被放行"要留在盘上，而不是只活在某一次工具调用的返回里）。
    if payload:
        try:
            with ctx.store.tx("lit_candidates", actor=ctx.actor, note="lit.admit.prepare") as tx:
                for row in tx.rows("lit_candidates"):
                    got_payload = payload.get(str(row.get("slot") or ""))
                    if not got_payload:
                        continue
                    if got_payload["new_content"]:
                        row["new_content"] = got_payload["new_content"]
                    if got_payload["overlap_ok"] is not None:
                        row["overlap_ok"] = bool(got_payload["overlap_ok"])
                    S.LitCandidate(**{k: row[k] for k in row
                                      if k in S.LitCandidate.__dataclass_fields__}).validate()
                    tx.upsert("lit_candidates", row, note="lit.admit.prepare")
        except (StoreError, ValueError) as exc:
            return _stage_fail(exc)

    def _registrar(row: Mapping[str, Any]) -> dict:
        # 判据只有一份：与 `lit.admit_all` 共用 `_registrar_from_candidate`
        # （那里也补写定位栏，于是"逐条入库"与"一键迁移"落出来的行同形）。
        return _registrar_from_candidate(ctx, row)

    try:
        got = _admit(ctx.store, registrar=_registrar, request_id=request_id, slots=wanted,
                     batch=batch, new_content=new_content, actor=ctx.actor)
    except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
        return _stage_fail(exc)
    if got.get("whole_call_refused"):
        # 整笔拒绝也要让模型读到读数（`fail` 的 meta 就是给这个用的）。
        return fail(got.get("reason") or "入库被拒", kind=got.get("kind") or "over_cap",
                    request_id=got.get("request_id"), batch=got.get("batch"),
                    call_size=got.get("call_size"), call_limit=got.get("call_limit"),
                    delegation_admitted=got.get("delegation_admitted"),
                    delegation_limit=got.get("delegation_limit"),
                    refused=got.get("refused"))
    return ok({
        "ok": got["ok"],
        "kind": got["kind"],
        "whole_call_refused": got["whole_call_refused"],
        "reason": got["reason"],
        "request_id": got["request_id"],
        "batch": got["batch"],
        "call_size": got["call_size"],
        "call_limit": got["call_limit"],
        "delegation_admitted": got["delegation_admitted"],
        "delegation_limit": got["delegation_limit"],
        "admitted": got["admitted"],
        "refused": got["refused"],
        "cleared": got["cleared"],
        "registered": got["registered"],
        "report": got["report"],
        "report_path": got["report_path"],
    })


def _h_lit_admit_all(
    ctx: _Ctx,
    request_id: str | None = None,
    new_content: str = "",
) -> Any:
    """``lit.admit_all``：「一键迁移」 —— 把本委托待审且过筛的行一次迁进 literature，然后清空。
    
    业主 2026-10-20 第 2 条，四件事顺序固定（实现见 `litstage.admit_all`）：
    
    1. 取本委托所有 `pending` 行，逐条过「重叠检查」（DOI 重复 / 高重叠无 `new_content`⇒ 拒收；超配额 ⇒ 这一条不入库）； 2. 通过的走
    「现有登记路径」（与 `search.register` 同一条）； 3. 「结算清空本委托」：成功落 `admitted`、被拒落 `rejected(理由码)`、其余落
    `cleared(over_cap / not_screened)` + `cleared_at` ⇒ 迁移后本委托没有 `pending` 残留，下一次委托看不到本委托的
    行（`request_id` 已经换了）。「不物理删」； 4. 写「委托报告」 `reports/lit-<request_id>.md`：已入库一块（含一句相关性）+未入
    库一块（含受控理由）—— 这是交付物，不是可选（业主第 3 条）。
    
    它仍守"一次委托至多入库 10 篇"与"重叠高需 `new_content`"两条。
    """
    from ..litstage import LitStageError, admit_all as _admit_all

    if ctx.store is None:
        return fail("未配置 store：入不了库（不是「都重复了」）", kind="no_store")

    def _registrar(row: Mapping[str, Any]) -> dict:
        # 判据只有一份：与 `lit.admit_all` 共用 `_registrar_from_candidate`
        # （那里也补写定位栏，于是"逐条入库"与"一键迁移"落出来的行同形）。
        return _registrar_from_candidate(ctx, row)

    try:
        got = _admit_all(ctx.store, registrar=_registrar, request_id=request_id,
                         new_content=new_content, actor=ctx.actor)
    except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
        return _stage_fail(exc)
    if not got.get("ok"):
        return fail(got.get("reason") or "一键迁移被拒", kind=got.get("kind") or "over_cap",
                    request_id=got.get("request_id"), refused=got.get("refused"))
    return ok({
        "ok": got["ok"],
        "kind": got["kind"],
        "whole_call_refused": got["whole_call_refused"],
        "reason": got["reason"],
        "request_id": got["request_id"],
        "call_size": got["call_size"],
        "call_limit": got["call_limit"],
        "delegation_admitted": got["delegation_admitted"],
        "delegation_limit": got["delegation_limit"],
        "admitted": got["admitted"],
        "refused": got["refused"],
        "cleared": got["cleared"],
        "registered": got["registered"],
        "report": got["report"],
        "report_path": got["report_path"],
    })


#: 待新增文献列表那七件的「声明」（`@tool` 写进 `fn.__tool_spec__`，`register` 时绑定 ctx）。
#: 键名逐个从 `litstage` 的实现里读出（`ok(...)` 的数据字典 / `report_markdown` 的两块）。
_LIT_PARAMS_ADMIT_ITEM = {
    "type": "object",
    "properties": {
        "slot": {"type": "string", "minLength": 1, "maxLength": 40},
        "new_content": {"type": "string", "maxLength": 2000,
                        "description": "本次检索要的新内容（重叠度高时必须有）"},
        "overlap_ok": {"type": "boolean",
                       "description": "调用方对「重叠也可以收」的表态；不替代 new_content"},
    },
    "required": ["slot"],
    "additionalProperties": False,
}

_LIT_PARAMS_ENTRY = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 600},
        "doi": {"type": "string", "maxLength": 300},
        "provider": {"type": "string", "maxLength": 80},
        "year": {"type": "integer", "minimum": 1000, "maximum": 2999},
        "type_code": {"type": "string", "enum": list(S.LIT_TYPES)},
        "summary": {"type": "string", "maxLength": 4000},
        "url": {"type": "string", "maxLength": 1000},
        "relevance": {"type": "string", "maxLength": 400,
                      "description": "一句「它为什么与本次检索相关」，委托报告要用"},
    },
    "required": ["title"],
    "additionalProperties": False,
}


@tool(
    "lit.overlap_check",
    "**不联网**：这一条与本地库重叠多少？DOI 完全相同 ⇒ 视为重复；否则标题词集 Jaccard"
    "（阈值 0.60）≥ 阈值 ⇒ 必须给 new_content 才许入库。",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 600},
            "doi": {"type": "string", "maxLength": 300},
        },
        "required": ["title"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("A",),
    returns=(
        "{'title','doi','checked','duplicate','overlap_score','overlap_kind','overlap_with',"
        "'requires_new_content','reason'}；"
        "失败：ok=False + kind(no_store/store_error) + checked=False（**重叠没查**，不是「没有重叠」）"
    ),
    tags=("lit", "stage", "overlap"),
)
def _lit_overlap_check(ctx, title, doi=None):
    """lit.overlap_check 的工具体。"""
    return _h_lit_overlap_check(ctx, title, doi)


@tool(
    "lit.stage_add",
    "把广搜结果**追加**进本次委托的待新增列表（一次任意条，超过 10 条也允许）："
    "槽位号自动分配、只增不复用。入库是另一件事（lit.admit_all）。",
    {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "minLength": 1, "maxLength": 40,
                           "description": "这一次查询委托（search_requests 的行号，如 r-000001）；"
                                          "换一个号就是开始下一次委托"},
            "entries": {"type": "array", "minItems": 1, "maxItems": 500,
                        "items": _LIT_PARAMS_ENTRY},
            "batch": {"type": "integer", "minimum": 1, "maximum": 100000,
                      "description": "第几批（不给 = 本委托的下一批）"},
        },
        "required": ["request_id", "entries"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("A",),
    returns=(
        "{'request_id','batch','count','staged'}；"
        "staged[] 每项是 {'slot','batch','title'}；"
        "失败：ok=False + kind(no_store/no_delegation/bad_delegation/empty_batch/bad_batch/"
        "bad_entry/store_error) 之一 + 明细"
    ),
    tags=("lit", "stage", "add"),
)
def _lit_stage_add(ctx, request_id, entries, batch=None):
    """lit.stage_add 的工具体。"""
    return _h_lit_stage_add(ctx, request_id, entries, batch)


@tool(
    "lit.stage_list",
    "查待新增列表：默认**只看当前委托**（列表按委托重置）；status 五态"
    "（pending/withdrawn/rejected/admitted/cleared），**撤掉的空槽位照样在列表里并带理由**。",
    {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "maxLength": 40,
                           "description": "哪一次委托（不给 = 当前委托；*= 全部委托）"},
            "batch": {"type": "integer", "minimum": 1, "maximum": 100000},
            "status": {"type": "string", "enum": list(S.CANDIDATE_STATUSES)},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("A",),
    returns=(
        "{'request_id','current_request_id','batch','status','count','counts','gaps','rows',"
        "'total_all_delegations','note'}；"
        "counts 是 {'pending','withdrawn','rejected','admitted','cleared'} 五个计数；"
        "rows[] 每项是 {'slot','batch','status','title','request_id','doi','provider','year',"
        "'type_code','summary','url','added_at','relevance','lit_id','admitted_at',"
        "'reason_code','withdrawn_reason','reject_reason','cleared_at','clear_reason',"
        "'new_content','overlap_score','overlap_kind','overlap_with','overlap_ok'}；"
        "失败：ok=False + kind(no_store/bad_status/no_delegation/store_error)"
    ),
    tags=("lit", "stage", "list"),
)
def _lit_stage_list(ctx, request_id=None, batch=None, status=None):
    """lit.stage_list 的工具体。"""
    return _h_lit_stage_list(ctx, request_id, batch, status)


@tool(
    "lit.stage_withdraw",
    "撤掉某一槽：**序号不变、不物理删除**，写受控理由码（withdrawn_by_reviewer）+ 一句说明；"
    "撤掉后可再 stage_add 补位（新条进新序号）。",
    {
        "type": "object",
        "properties": {
            "slot": {"type": "string", "minLength": 1, "maxLength": 40},
            "reason_code": {"type": "string", "enum": list(S.CANDIDATE_REASON_CODES)},
            "note": {"type": "string", "maxLength": 400, "description": "给人看的那一句（可空）"},
        },
        "required": ["slot", "reason_code"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("A",),
    returns=(
        "{'slot','status','reason_code','reason','title','request_id','batch'}；"
        "失败：ok=False + kind(no_store/bad_reason_code/unknown_slot/not_pending/store_error)"
    ),
    tags=("lit", "stage", "withdraw"),
)
def _lit_stage_withdraw(ctx, slot, reason_code, note=""):
    """lit.stage_withdraw 的工具体。"""
    return _h_lit_stage_withdraw(ctx, slot, reason_code, note)


@tool(
    "lit.stage_reject",
    "审内容后**拒收**某一槽：写受控理由码（rejected_off_topic / rejected_low_quality / "
    "overlap_without_new_content / duplicate_doi）+ 一句说明；行保留、不物理删除。",
    {
        "type": "object",
        "properties": {
            "slot": {"type": "string", "minLength": 1, "maxLength": 40},
            "reason_code": {"type": "string", "enum": list(S.CANDIDATE_REASON_CODES)},
            "note": {"type": "string", "maxLength": 400},
        },
        "required": ["slot", "reason_code"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("A",),
    returns=(
        "{'slot','status','reason_code','reason','title','request_id','batch'}；"
        "失败：ok=False + kind(no_store/bad_reason_code/unknown_slot/not_pending/store_error)"
    ),
    tags=("lit", "stage", "reject"),
)
def _lit_stage_reject(ctx, slot, reason_code, note=""):
    """lit.stage_reject 的工具体。"""
    return _h_lit_stage_reject(ctx, slot, reason_code, note)


@tool(
    "lit.admit",
    "正式入库（逐条）：条数上限（单次 ≤10、单委托累计 ≤10）与重叠检查都过了才走现有登记路径；"
    "超限整笔拒绝。**不清空列表**（清空属于 lit.admit_all）。",
    {
        "type": "object",
        "properties": {
            "slots": {"type": "array", "items": {"type": "string", "maxLength": 40},
                      "minItems": 1, "maxItems": 200},
            "items": {"type": "array", "minItems": 1, "maxItems": 200,
                      "items": _LIT_PARAMS_ADMIT_ITEM,
                      "description": "逐条带 new_content / overlap_ok（优先于调用级参数）"},
            "request_id": {"type": "string", "maxLength": 40,
                           "description": "哪一次委托（不给 = 当前委托）"},
            "batch": {"type": "integer", "minimum": 1, "maximum": 100000},
            "new_content": {"type": "string", "maxLength": 2000},
            "overlap_ok": {"type": "boolean"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("A",),
    returns=(
        "{'ok','kind','whole_call_refused','reason','request_id','batch','call_size',"
        "'call_limit','delegation_admitted','delegation_limit','admitted','refused','cleared',"
        "'registered','report','report_path'}；"
        "admitted[] 每项是 {'slot','title','lit_id','created','overlap_score','overlap_kind',"
        "'overlap_with','new_content'}；"
        "refused[] / cleared[] 每项是 {'slot','title','why','code','overlap'}；"
        "report 是 {'path','rel_path','chars','admitted','not_admitted','request_id'}；"
        "失败：ok=False + kind(no_store/over_cap_call/over_cap_delegation/unknown_slot/"
        "no_target/mixed...) + 三个上限读数"
    ),
    tags=("lit", "admit"),
)
def _lit_admit(ctx, slots=None, items=None, request_id=None, batch=None, new_content="",
               overlap_ok=None):
    """lit.admit 的工具体。"""
    return _h_lit_admit(ctx, slots, items, request_id, batch, new_content, overlap_ok)


@tool(
    "lit.admit_all",
    "**一键迁移**：本委托待审且过筛（重叠检查）的行一次性迁进 literature（≤10 条），"
    "然后结算清空本委托的列表（全终态、不物理删），并写委托报告 reports/lit-<request_id>.md"
    "（已入库 + 未入库含受控理由，两块都要有）。",
    {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "maxLength": 40,
                           "description": "哪一次委托（不给 = 当前委托）"},
            "new_content": {"type": "string", "maxLength": 2000,
                            "description": "本委托统一的「要的新内容」（逐条优先）"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("A",),
    returns=(
        "{'ok','kind','whole_call_refused','reason','request_id','call_size','call_limit',"
        "'delegation_admitted','delegation_limit','admitted','refused','cleared','registered',"
        "'report','report_path'}；"
        "admitted[] 每项是 {'slot','title','lit_id','created','overlap_score','overlap_kind',"
        "'overlap_with','new_content'}；"
        "refused[] / cleared[] 每项是 {'slot','title','why','code','overlap'}；"
        "report 是 {'path','rel_path','chars','admitted','not_admitted','request_id'}；"
        "失败：ok=False + kind(no_store/no_delegation/bad_delegation/store_error)"
    ),
    tags=("lit", "admit", "report"),
)
def _lit_admit_all(ctx, request_id=None, new_content=""):
    """lit.admit_all 的工具体。"""
    return _h_lit_admit_all(ctx, request_id, new_content)


#: 装配清单（`T-8`）：`(工具体函数, 需要从装配期注入的名字)`。
_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (_search_providers, ('ctx',)),
    (_search_shelf, ('ctx',)),
    (_search_local, ('ctx',)),
    (_search_download, ('ctx',)),
    (_search_dedup_check, ('ctx',)),
    (_search_ingest_local, ('ctx',)),
    (_search_register, ('ctx',)),
    # ---- 待新增文献列表（业主 2026-10-20 口径）：按委托暂存 → 审 → 一键迁移 → 报告 ----
    (_lit_overlap_check, ('ctx',)),
    (_lit_stage_add, ('ctx',)),
    (_lit_stage_list, ('ctx',)),
    (_lit_stage_withdraw, ('ctx',)),
    (_lit_stage_reject, ('ctx',)),
    (_lit_admit, ('ctx',)),
    (_lit_admit_all, ('ctx',)),
)


def _h_walk_citations(
    ctx: _Ctx, lit_id: str, direction: str = "backward", limit: int = 20
) -> Any:
    """``search.walk_citations``：由一篇「已登记的」文献出发，在引文图上走一步。
    业主 2026-10-15 裁定：引文图「用新动作的方式落」 —— 本函数是那件动作的工具面。
    - ``backward``（「回溯」）：这一篇「引了谁」 —— 读它的 ``referenced_works`` 再批量解析；- ``forward``（「前推」）：「谁引了这一篇」 —— 
    ``filter=cites:<W…>``。
    ## 为什么这里「不」替判重（与 ``search.literature`` 的差别是刻意的）
    ``search.literature`` 会给每条候选标 ``is_new``，好让 A 少跑一次判重工具。本工具「不做这件事」：判重（``dedup_key`` / ``existing``
    / ``is_new``）在本模块里只有 ``_h_literature`` 那一处内联实现，在这里再写一份就是"同一件事两处实现" ——而"同一篇文献只留一个键"正是本仓划进禁改区的那条纪律（``dedup.py``）。
    所以这里只交「书目字段」；要不要登记、怎么登记，走既有的``search.dedup_check`` → ``search.register`` 那条路。
    ## 为什么源必须是「盘上已登记」的那一篇
    引文走查要从"我们手上的这一篇"出发（拿它的 DOI / OpenAlex id）。不接受任意 DOI：那样它就成了第二个检索入口，而"检索"这件事的账（``search_requests`` 的
    终局、I7 准入闸门）只在 ``search.literature`` 那一处记。``lit_id`` 不在 ``literature`` 表里 ⇒ ``ok=False`` 并说明（不是空列表）。
    """
    fail_meta = {"lit_id": lit_id, "direction": direction, "count": 0}
    if ctx.store is None:
        return fail("未配置 store：读不到 literature 表，于是不知道这一篇是哪一篇",
                    kind="no_store", **fail_meta)
    rows, read_error = _literature_rows(ctx)
    if read_error:
        # 三态：表坏了「不是」"这一篇不在表里"（后者是有效结论）
        return fail(f"{read_error} ⇒ 引文走查**没做成**（不是「它没有引文邻居」）",
                    kind="table_unreadable", **fail_meta)
    row = next((r for r in rows if str(r.get("lit_id")) == str(lit_id)), None)
    if row is None:
        return fail(f"literature 表里没有 {lit_id!r}（引文走查从盘上这一篇出发）",
                    kind="unknown_lit_id", known=len(rows), **fail_meta)

    doi = row.get("doi")
    oa_id = row.get("openalex_id") or ((row.get("raw") or {}).get("openalex_id")
                                       if isinstance(row.get("raw"), dict) else None)
    if not doi and not oa_id:
        return fail("这一行既没有 doi 也没有 openalex_id ⇒ 没法在引文图上定位它",
                    kind="no_source_key", **fail_meta)

    prov = _resolve_provider(ctx, "openalex")
    if not hasattr(prov, "walk_citations"):
        return fail(f"provider {getattr(prov, 'name', prov)!r} 不支持引文走查",
                    kind="provider_cannot_walk", **fail_meta)
    try:
        cands = prov.walk_citations(doi=doi, openalex_id=oa_id,
                                    direction=direction, limit=limit)
    except Exception as exc:  # noqa: BLE001 - 走查失败要如实回报，不该让工具层崩
        return fail(f"引文走查失败：{type(exc).__name__}: {exc}",
                    kind="walk_failed", **fail_meta)

    items = [
        {
            "title": c.title,
            "year": c.year,
            "doi": c.doi,
            "type_code": c.type_code,
            "authors": list(c.authors or []),
            "venue": c.venue,
            "language": c.language,
            "summary": T.clip(c.summary, P.SUMMARY_MAX_CHARS),
            "pdf_url": c.pdf_url,
            "landing_url": c.landing_url,
            "provider": c.provider,
            # 这一条是怎么被找到的：引文图上的「方向」与它的 OA 位置来源。
            # `oa_source` 直接决定"这篇的全文取不取得到"（`_pdf_url_rank` 用同一格）。
            "is_oa": (c.raw or {}).get("is_oa"),
            "oa_source": (c.raw or {}).get("pdf_url_source"),
            "openalex_id": (c.raw or {}).get("openalex_id"),
        }
        for c in cands
    ]
    # 成功也要走 `ok(...)`，「不许直接 return 一个普通 dict」。
    #
    # 为什么（这是实测踩出来的）：注册表两种都收（普通 dict 会被它包成 `ToolResult`），
    # 所以"直接 return dict"在「工具调用」那一侧看不出问题。但「动作层」是直接调
    # 这个处理器的（`agent_a/walk_citations.py` 走 `_h_walk_citations`），它按
    # `ToolResult` 读 `ok` / `data` —— 于是普通 dict 会让它把一次「成功」读成
    # `ok=False`、`kind=''`（"没做成"却没有理由），而那正是本仓最忌讳的形状：
    # 「读数与事实不符」。本文件其余处理器一律 `ok(...)` / `fail(...)`，照它办。
    return ok({
        "lit_id": lit_id,
        "doi": doi,
        "openalex_id": oa_id,
        "direction": direction,
        "count": len(items),
        "candidates": items,
        # 一句留给下游的话：这份候选没做过判重标注（本工具不复制判重实现）
        "note": ("候选**没有**判重标注（本工具不复制判重实现）：登记前先 search.dedup_check，"
                 "登记走 search.register。"),
    })


def register(
    registry: ToolRegistry,
    *,
    store: Store | None = None,
    providers: Iterable[Any] | None = None,
    downloader: Any | None = None,
    workspace: str | Path | None = None,
    workspace_root: str | Path | None = None,
    root: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    provider_config: Mapping[str, Any] | None = None,
    actor: str = "agent-A",
) -> list[ToolSpec]:
    """把 A 的检索工具注册进 ``registry``，返回注册的 ``ToolSpec`` 列表。
    
    参数（全部可选，按需注入 —— 没注入的能力只是少一点便利，不会让工具层起不来）：
    
    - ``store``：文献表所在的工作区。不传时 ``search.dedup_check`` /``search.register`` 会明确 ``fail``（而不是
    给出假结论），``search.literature``的 ``is_new`` 会是 ``null``。这是刻意的：判重结论宁可说"没查"，不能说错。- 
    ``providers``：provider 实例列表（离线测试注入假对象用）。不传则按名字惰性构造内置 provider（``providers.build_providers``），
    注册本身不联网。- ``downloader``：下载器实例（不传则用 ``fetch.default_downloader``）。- ``workspace``：工作区根
    目录（``downloads/`` 落在它下面）。别名``workspace_root`` / ``root`` 也接受（装配器用这两个名字注入）。默认取 
    ``store.root``，再退回当前目录。- ``provider_config``：透传给 provider 构造函数的参数（如 ``mailto``、
    ``fixture_path``、``min_interval``）。
    """
    ws = _pick_workspace(workspace, workspace_root, root, store)
    ctx = _Ctx(
        workspace=ws.resolve(),
        store=store,
        downloader=downloader,
        config=dict(config or {}),
        provider_config=dict(provider_config or {}),
        actor=actor,
    )
    for prov in providers or []:
        name = (getattr(prov, "name", None) or type(prov).__name__).lower()
        ctx.providers[name] = prov

    provider_enum = _known_names(ctx)

    specs= [
        ToolSpec(
            name="search.literature",
            summary="按 topic/mode 检索文献候选，每条带 dedup_key 与 is_new（A 不必再跑一次判重）。mode=precise 时必须给 "
            "description。",
            params={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "minLength": 1, "maxLength": 400},
                    "mode": {"type": "string", "enum": list(S.SEARCH_MODES)},
                    "description": {"type": "string", "maxLength": 4000},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "provider": {"type": "string", "enum": provider_enum},
                    # `R2b` ⑱：一次问多源。给了它就忽略 `provider`；每个源各自的
                    # 成败与条数落在 `sources[]`，成本落在 `cost`。
                    "providers": {
                        "type": "array",
                        "items": {"type": "string", "enum": provider_enum},
                        "minItems": 1,
                        "maxItems": len(provider_enum),
                        "description": ("一次问多个源并合并（忽略 provider）："
                                        "逐源三态见 sources[]、成本见 cost。"),
                    },
                },
                "required": ["topic"],
                "additionalProperties": False,
            },
            handler=lambda topic, mode="topical", description="", limit=10,
            provider=DEFAULT_PROVIDER, providers=None: _h_literature(
                ctx, topic, mode, description, limit, provider, providers
            ),
            side_effect="read",
            declared_external="egress",
            roles=("A",),
            # 键名逐个从 `_h_literature` 的 data 字典读出（没真跑过联网检索：
            # 本轮观测到的是一次真实 429 之后的 fail，不是 ok 分支 —— 如实留痕）。
            # candidates[] 每项除下列字段外还带 authors/venue/language/
            # dedup_keys/dedup_hit_key/channel/cited_by_count。
            # `sources`/`source_count`/`source_failures`/`source_refusals`/`cost`
            # 与 `providers_requested` 是 `R2b` ⑱ 加的多源读数（单源调用时为 null）。
            returns=(
                "{'provider','mode','topic','description','limit','count','new_count',"
                "'existing_count','unknown_count','batch_duplicate_count','store_checked',"
                "'store_read_error','existing_table_size','candidates','elapsed_s',"
                "'diagnostics','warnings','providers_requested','sources','source_count',"
                "'source_failures','source_refusals','cost'}；"
                "candidates[] 每项是 {'title','year','doi','type_code','authors','venue','language',"
                "'summary','pdf_url','landing_url','provider','dedup_key','dedup_keys','existing',"
                "'existing_lit_id','dedup_hit_key','batch_duplicate','is_new','sources','channel',"
                "'cited_by_count'}；"
                "sources[] 每项是 {'name','status','count','error_kind','error','delivered','refused'}；"
                "cost 是 {'provider_calls','elapsed_s'}"
            ),
            tags=("search", "literature"),
        ),
        ToolSpec(
            name="search.walk_citations",
            summary="由一篇**已登记**的文献出发走一步引文图：backward = 它引了谁、forward = 谁引了它。候选不带判重标注，登记走 `"
            "search.dedup_check` / register。",
            params={
                "type": "object",
                "properties": {
                    "lit_id": {
                        "type": "string", "minLength": 1, "maxLength": 40,
                        "description": "盘上 literature 表的行号；引文走查从这一篇出发",
                    },
                    "direction": {
                        "type": "string", "enum": ["backward", "forward"],
                        "description": "backward=这一篇引了谁；forward=谁引了这一篇",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["lit_id"],
                "additionalProperties": False,
            },
            handler=lambda lit_id, direction="backward", limit=20: _h_walk_citations(
                ctx, lit_id, direction, limit
            ),
            side_effect="read",
            declared_external="egress",
            roles=("A",),
            returns=(
                "{'lit_id','doi','openalex_id','direction','count','candidates','note'}；"
                "失败时按本模块的统一口径走 `fail(...)`（`ok=False` ＋ `error` 一句，"
                "`kind` 分四档：no_store / table_unreadable / unknown_lit_id / "
                "no_source_key / provider_cannot_walk / walk_failed）；"
                "candidates[] 每项是 {'title','year','doi','type_code','authors','venue',"
                "'language','summary','pdf_url','landing_url','provider','is_oa',"
                "'oa_source','openalex_id'}"
            ),
            tags=("search", "citation"),
        ),
    ]
    _bound: dict[str, Any] = {}
    _bound['ctx'] = ctx
    for _fn, _deps in _TOOL_FUNCTIONS:
        specs.append(replace(_fn.__tool_spec__,
                             handler=partial(_fn, *[_bound[k] for k in _deps])))
    registry.register_all(specs)
    return specs


# --------------------------------------------------------------------------- 自检


def _selftest() -> int:
    """自检：真实探测 + 真实检索 + 离线判重 + 登记回环。

    全部落在 ``tempfile`` 临时工作区里，不碰 test/test1/data 或 demo/run。
    """
    import json
    import sys
    import tempfile

    try:  # Windows 控制台默认 GBK，中文/符号会抛 UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

    from ..store import Store

    ws = Path(tempfile.mkdtemp(prefix="agentflow-search-selftest-"))
    store = Store(ws)
    store.init()
    registry = ToolRegistry(name="selftest-A")
    # 绑定角色（`P-14`）：本自检调的是 `search.*`，它们的 `roles` 只有 A。
    registry.bound_role = "A"
    register(registry, store=store, workspace=ws)

    print("=" * 78)
    print("agentflow.tools.search_tools 自检")
    print(f"临时工作区：{ws}")
    print("=" * 78)
    print(registry.text_catalog(role="A"))

    failed = 0

    # ---- [1] provider 真实探测
    print("-" * 78)
    print("[1] search.providers —— 真实探测（不是写死）")
    res = registry.call("search.providers")
    if not res.ok:
        print(f"    [失败] {res.error}")
        failed += 1
    else:
        data = res.unwrap()
        for row in data["providers"]:
            print(
                f"    - {row['name']:<11} available={row['available']!s:<5} status={row['status']:<12} "
                f"latency={row['latency_s']}s\n        reason: {row['reason']}"
            )
        print(f"    汇总：{data['summary']}")
        print(f"    available={data['available']} unavailable={data['unavailable']} unverified={data['unverified']}")

    # ---- [2] 真实检索（联网）
    print("-" * 78)
    print("[2] search.literature topic='abelian group' mode=topical limit=3 （联网）")
    search_ok = True
    res = registry.call("search.literature", topic="abelian group", mode="topical", limit=3)
    if not res.ok:
        search_ok = False
        print(f"    [失败·如实报告] {res.error}")
        print(f"    meta={json.dumps(res.meta, ensure_ascii=False, default=str)}")
    else:
        data = res.unwrap()
        print(
            f"    provider={data['provider']} count={data['count']} new={data['new_count']} "
            f"existing={data['existing_count']} unknown={data['unknown_count']} "
            f"elapsed={data['elapsed_s']}s"
        )
        print(f"    diagnostics={json.dumps(data['diagnostics'], ensure_ascii=False, default=str)[:300]}")
        for i, c in enumerate(data["candidates"], 1):
            print(
                f"    [{i}] {c['title'][:70]}\n"
                f"        year={c['year']} type={c['type_code']} doi={c['doi']} provider={c['provider']}\n"
                f"        dedup_key={c['dedup_key']}  is_new={c['is_new']}  (existing={c['existing']})\n"
                f"        pdf_url={c['pdf_url']}"
            )
        for w in data["warnings"]:
            print(f"    [warning] {w}")

    # ---- [3] 离线判重
    print("-" * 78)
    print("[3] search.dedup_check —— 不联网的判重结论")
    # 3a. 造一条"已存在的文献"，再用同一个 DOI 问一次 → 必须判重
    with store.tx("literature", actor="selftest") as tx:
        lit_id = tx.alloc_id("lit")
        row = S.Literature(
            lit_id=lit_id,
            title="On the commutativity of abelian groups",
            type="J",
            summary="selftest fixture",
            path=None,
            processed=True,
            dedup_key="doi:10.1000/selftest.abelian",
            doi="10.1000/selftest.abelian",
            year=1930,
            added_at=S.now_iso(),
        )
        row.validate()
        tx.upsert("literature", row.to_dict(), note="selftest")
    print(f"    预置一条既有文献：lit_id={lit_id} doi=10.1000/selftest.abelian")

    res = registry.call("search.dedup_check", title="Commutativity in abelian groups", doi="10.1000/selftest.abelian")
    print(f"    (a) 同 DOI → ok={res.ok}")
    if res.ok:
        d = res.unwrap()
        print(
            f"        would_be_duplicate={d['would_be_duplicate']} matched_key={d['matched_key']} "
            f"existing={json.dumps(d['existing'], ensure_ascii=False, default=str)}"
        )
        if not d["would_be_duplicate"]:
            print("        [失败] 同 DOI 未被判重")
            failed += 1
    else:
        print(f"        [失败] {res.error}")
        failed += 1

    res = registry.call("search.dedup_check", title="A wholly unrelated topic nobody wrote about", year=2099)
    print(f"    (b) 全新标题 → ok={res.ok}")
    if res.ok:
        d = res.unwrap()
        print(
            f"        would_be_duplicate={d['would_be_duplicate']} keys={d['keys']} "
            f"near_misses={json.dumps(d.get('near_misses'), ensure_ascii=False, default=str)}"
        )
        if d["would_be_duplicate"]:
            print("        [失败] 全新标题被判成重复")
            failed += 1
    else:
        print(f"        [失败] {res.error}")
        failed += 1

    # 3c. precise 缺 description → 必须 fail（与 schema.SearchRequest 一致）
    res = registry.call("search.literature", topic="abelian group", mode="precise")
    print(f"    (c) mode=precise 且 description 为空 → ok={res.ok} error={res.error!r}")
    if res.ok:
        print("        [失败] precise 缺 description 居然通过了")
        failed += 1

    # ---- [4] 登记回环（离线）
    print("-" * 78)
    print("[4] search.register 回环（离线；search.download 需要真实 URL，自检里不跑）")
    src = ws / "downloads" / "selftest-paper.txt"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("An abelian group is a group in which the commutative law holds.", encoding="utf-8")
    res = registry.call(
        "search.register",
        title="Selftest paper about abelian groups",
        # 注意：schema 的 enum 只允许大写类型码，所以经 registry.call 进来的必然已是大写；
        # handler 里仍做一次 .upper() 以兼容直接调用 handler 的场景。
        type_code="J",
        summary="selftest",
        path=str(src),
        doi="10.1000/selftest.new",
        year=2024,
    )
    print(f"    register → ok={res.ok}")
    if res.ok:
        d = res.unwrap()
        print(f"        created={d['created']} lit_id={d['lit_id']} path={d['path']} download={d['download']}")
        target = store.library / (d["path"] or "")
        print(f"        收编到 library：exists={target.exists()} 原 downloads/ 文件仍在={src.exists()}")
        # 再来一次同样的登记 → 应命中判重，created=False
        res2 = registry.call(
            "search.register",
            title="Selftest paper about abelian groups",
            type_code="J",
            summary="selftest again",
            doi="https://doi.org/10.1000/selftest.new",  # URL 形态的 DOI 必须归一化到同一个键
            year=2024,
        )
        print(f"    重复登记 → ok={res2.ok} created={res2.unwrap()['created'] if res2.ok else None}")
        if not res2.ok or res2.unwrap()["created"]:
            print("        [失败] 同一 DOI（URL 形态）未判重")
            failed += 1
    else:
        print(f"        [失败] {res.error}")
        failed += 1

    print("=" * 78)
    if not search_ok:
        print("[注意] 联网检索这一步失败（见上方 error）。本地判重/登记逻辑已全部通过。")
    print(f"SELF-CHECK {'DONE' if failed == 0 else f'FAILED({failed})'}")
    return 0 if failed == 0 and search_ok else 1


if __name__ == "__main__":  # pragma: no cover - 手工自检入口
    raise SystemExit(_selftest())

"""A 专用检索工具：provider 探测 / 文献检索 / 下载 / 判重检查 / 文献登记。

基于 ``tools/base.py`` 的 ``ToolSpec`` / ``ToolResult`` 写（见 ``DESIGN-TOOLS.md`` §1）。

## 为什么需要这一层

A 的思维链只该花在"判断该调哪个工具、该用哪个检索词"上，不该花在"怎么把
provider 的参数拼对"、"这条是不是已经登记过"上。工具层把这些标准动作固化成
有名字、有 schema、有校验、有结构化返回、声明副作用的原子动作。

## 三条贯穿全模块的原则

1. 判重结论随候选一起返回。``search.literature`` 的每条候选都带
   ``dedup_key`` / ``existing`` / ``is_new``：A 看到候选列表的同时就知道哪几条是
   新的。否则 A 必须"搜完再问一次判重"——白占一轮思维链，还多打一次工具。

2. "没做"与"做了没结果"必须分开（与 ``DESIGN.md`` §6.3 的"无文本层返回
   ``None`` 而不是 ``False``"同源）：
   - provider 检索抛异常 ⇒ ``fail``（没做成）；检索正常但零命中 ⇒
     ``ok`` + 空列表（做了，结论就是"没有"）。二者绝不能混。
   - 未配置 ``store`` 时无法比对既有文献表 ⇒ 候选的 ``existing`` 是 ``None``
     （未知），而不是 ``False``（"新的"）。把"没查"写成"新的"会让 A 重复登记。

3. 可用性靠真探测，不靠假设。``search.providers`` 对每个 provider 发一次
   极小的真实请求；``ABFLOW_SKIP_NETWORK=1`` 时明确标 ``unverified``（未探测），
   而不是把"没探测"写成"可用"或"不可用"。

   正因为它真的发 HTTP，它的 ``side_effect`` 是 ``network``（需要审批），
   不是 ``read``。这一处曾经声明成 ``read``：那等于在权限面上说
   "这个工具不联网、不必审批"，而它每次调用都会向外部源发起请求 ——
   声明与实际不符的副作用等级会让"审批"这个闸门在该拦的地方不拦。
   （``ABFLOW_SKIP_NETWORK=1`` 只是"这一次没探测"，不是"这个工具不联网"；
   副作用等级声明的是能力，不是某一次调用的结果。）

## 文件落点（为什么这样定）

- ``search.download`` 下到 ``<workspace>/downloads/`` —— 这是一个中间态：
  文件名由 ``fetch`` 层 slug 化并去重，下载器保证"不覆盖已有文件"。
- ``search.register`` 把文件收编进 ``<store.library>/<lit_id>/``：因为
  ``schema.Literature.path`` 必须是 library/ 下的相对路径，绝对路径会被
  ``Literature.validate()`` 直接拒绝。收编失败时行照建、``path`` 置 ``null``
  并给 warning —— "知道有这篇但拿不到全文"本身就是有价值的结果（DESIGN.md §2.4）。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .base import ToolError, ToolRegistry, ToolSpec, fail, ok
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

    这是"为什么只回来 2 条"的唯一可查证据：``last_query_text`` 说明实际发出去的
    检索串，``filter_notes`` 说明有多少条被 precise 的标题过滤筛掉。
    ``last_phrase_fallbacks`` 与 ``last_channel_errors`` 是 `C-4` 之后新增的两条
    （短语零召回 ⇒ 退了词项检索 / 这一路抛了异常）：缺了它们，"只回来 2 条"
    与"整串短语把召回打成 0"在读数上长得一模一样。

    `FINAL-R3-05`：`stats` 里那几个计数是跨多跑累积的（同一个 provider 对象被
    反复读时它一直涨），而 `last_*` 全是逐跑读数 —— 两组数并排放着容易被读成
    同一时刻的同一件事。产物里没有"这一跑的 stats 快照"这一档（本次没有加：
    加字段要动 `evidence` 侧的折算），所以读的时候请以 `last_*` 为准，
    `stats` 只用来看"这个对象一共发过多少请求"。
    """
    out: dict[str, Any] = {}
    for attr in ("stats", "last_query_text", "last_filter_notes", "last_filtered_out",
                 "last_phrase_fallbacks", "last_channel_errors"):
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


def _h_literature(
    ctx: _Ctx,
    topic: str,
    mode: str = "topical",
    description: str = "",
    limit: int = 10,
    provider: str = DEFAULT_PROVIDER,
) -> Any:
    """``search.literature``：检索候选，并把判重结论一并算好。"""
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
    try:
        prov = _resolve_provider(ctx, provider)
    except ToolError as exc:
        return fail(str(exc), kind="unknown_provider", available=_known_names(ctx))

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
                "provider": cand.provider or getattr(prov, "name", provider),
                # ---- 判重（A 一眼看出哪几条是新的，不必再跑一次判重工具）
                "dedup_key": key,
                "dedup_keys": keys,
                "existing": (existing is not None) if store_known else None,
                "existing_lit_id": (existing or {}).get("lit_id") if existing else None,
                "dedup_hit_key": hit_key,
                "batch_duplicate": batch_dup,
                "is_new": is_new,
                "channel": (cand.raw or {}).get("channel"),
                "cited_by_count": (cand.raw or {}).get("cited_by_count"),
            }
        )

    new_count = sum(1 for i in items if i["is_new"] is True)
    existing_count = sum(1 for i in items if i["existing"] is True)
    unknown_count = sum(1 for i in items if i["is_new"] is None)
    data: dict[str, Any] = {
        "provider": getattr(prov, "name", provider),
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
        "diagnostics": _provider_diagnostics(prov),
    }
    warnings: list[str] = []
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
        return fail(
            f"下载失败：{res.error}",
            kind="download_failed",
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

    - ``store``：文献表所在的工作区。不传时 ``search.dedup_check`` /
      ``search.register`` 会明确 ``fail``（而不是给出假结论），``search.literature``
      的 ``is_new`` 会是 ``null``。这是刻意的：判重结论宁可说"没查"，不能说错。
    - ``providers``：provider 实例列表（离线测试注入假对象用）。不传则按名字
      惰性构造内置 provider（``providers.build_providers``），注册本身不联网。
    - ``downloader``：下载器实例（不传则用 ``fetch.default_downloader``）。
    - ``workspace``：工作区根目录（``downloads/`` 落在它下面）。别名
      ``workspace_root`` / ``root`` 也接受（装配器用这两个名字注入）。
      默认取 ``store.root``，再退回当前目录。
    - ``provider_config``：透传给 provider 构造函数的参数（如 ``mailto``、
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

    specs = [
        ToolSpec(
            name="search.providers",
            summary="列出可用检索源，并**真实探测**各自是否可用（发一次极小请求；"
            "ABFLOW_SKIP_NETWORK=1 时标为未探测而不是猜）。",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: _h_providers(ctx),
            # external=egress：探测会给每个网络源发一次真实 HTTP 请求（见模块 docstring 第 3 条）。
            # 声明成 read + external=none 会让这个工具绕过审批，而它确实在对外发请求。
            side_effect="read",
            declared_external="egress",
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
        ),
        ToolSpec(
            name="search.literature",
            summary="按 topic/mode 检索文献候选；每条候选都带 dedup_key 与 is_new，"
            "A 不必为了判重再跑一次工具。mode=precise 时必须给 description。",
            params={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "minLength": 1, "maxLength": 400},
                    "mode": {"type": "string", "enum": list(S.SEARCH_MODES)},
                    "description": {"type": "string", "maxLength": 4000},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "provider": {"type": "string", "enum": provider_enum},
                },
                "required": ["topic"],
                "additionalProperties": False,
            },
            handler=lambda topic, mode="topical", description="", limit=10, provider=DEFAULT_PROVIDER: _h_literature(
                ctx, topic, mode, description, limit, provider
            ),
            side_effect="read",
            declared_external="egress",
            roles=("A",),
            # 键名逐个从 `_h_literature` 的 data 字典读出（没真跑过联网检索：
            # 本轮观测到的是一次真实 429 之后的 fail，不是 ok 分支 —— 如实留痕）。
            # candidates[] 每项除下列字段外还带 authors/venue/language/
            # dedup_keys/dedup_hit_key/channel/cited_by_count。
            returns=(
                "{'provider','mode','topic','description','limit','count','new_count',"
                "'existing_count','unknown_count','batch_duplicate_count','store_checked',"
                "'store_read_error','existing_table_size','candidates','elapsed_s',"
                "'diagnostics','warnings'}；"
                "candidates[] 每项是 {'title','year','doi','type_code','authors','venue','language',"
                "'summary','pdf_url','landing_url','provider','dedup_key','dedup_keys','existing',"
                "'existing_lit_id','dedup_hit_key','batch_duplicate','is_new','channel','cited_by_count'}"
            ),
            tags=("search", "literature"),
        ),
        ToolSpec(
            name="search.download",
            summary="把候选的 pdf_url 下到工作区 downloads/（不覆盖同名文件）；"
            "filename 由 fetch 层 slug 化。返回 ok/bytes/sha256/path 与内容类型警告。",
            params={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "minLength": 8, "maxLength": 2000},
                    "hint": {"type": "string", "maxLength": 200},
                    "max_bytes": {"type": "integer", "minimum": 1024, "maximum": 2_000_000_000},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            handler=lambda url, hint="paper", max_bytes=DEFAULT_MAX_DOWNLOAD_BYTES: _h_download(
                ctx, url, hint, max_bytes
            ),
            side_effect="write_local",
            declared_external="egress",
            roles=("A",),
            # 键名逐个从 `_h_download` 的 data 字典读出（没真跑过：需要一次
            # 成功的真实下载；本轮观测到的是 fail 分支 —— 如实留痕）。
            returns=(
                "{'ok','url','hint','path','rel_path','dest_dir','filename','bytes','sha256',"
                "'http_status','max_bytes_requested','max_bytes_effective','elapsed_s',"
                "'content_warning','warnings'}"
            ),
            tags=("search", "download"),
        ),
        ToolSpec(
            name="search.dedup_check",
            summary="**不联网**：按三级硬键（DOI → 标题+年 → 仅标题带年容差）说明"
            "'这条会不会被判成已有的某篇'，并给出会命中的键。",
            params={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 600},
                    "year": {"type": "integer", "minimum": 1000, "maximum": 2999},
                    "doi": {"type": "string", "maxLength": 300},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
            handler=lambda title, year=None, doi=None: _h_dedup_check(ctx, title, year, doi),
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
        ),
        ToolSpec(
            name="search.register",
            summary="登记一条文献（literature 行，processed=false）：先判重，命中则复用既有 "
            "lit_id；未命中则 alloc_id('lit') 并把文件收编进 library/<lit_id>/。",
            params={
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
            handler=lambda title, type_code, summary, path=None, doi=None, year=None, request_id=None: _h_register(
                ctx, title, type_code, summary, path, doi, year, request_id
            ),
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
        ),
    ]
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
        print(f"    meta={json.dumps(res.meta, ensure_ascii=False)}")
    else:
        data = res.unwrap()
        print(
            f"    provider={data['provider']} count={data['count']} new={data['new_count']} "
            f"existing={data['existing_count']} unknown={data['unknown_count']} "
            f"elapsed={data['elapsed_s']}s"
        )
        print(f"    diagnostics={json.dumps(data['diagnostics'], ensure_ascii=False)[:300]}")
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
            f"existing={json.dumps(d['existing'], ensure_ascii=False)}"
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
            f"near_misses={json.dumps(d.get('near_misses'), ensure_ascii=False)}"
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

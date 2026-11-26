"""A 专用检索工具：provider 探测 / 文献检索 / 下载 / 判重检查 / 文献登记。

基于 ``tools/base.py`` 的 ``ToolSpec`` / ``ToolResult`` 写（见 ``DESIGN-TOOLS.md`` §1）。

## 为什么需要这一层
A 的思维链只该花在"判断该调哪个工具、该用哪个检索词"上，不该花在"怎么把 provider 的参数
拼对""这条是不是已经登记过"上。工具层把这些标准动作固化成有名字、有 schema、有校验、有
结构化返回、声明副作用的原子动作。

## 三条贯穿全模块的原则
1. ``search.literature`` 的每条候选都带 ``dedup_key`` / ``existing`` / ``is_new``：A 看到
   候选列表的同时就知道哪几条是新的。
2. "没做"与"做了没结果"必须分开（与 ``DESIGN.md`` §6.3 同源）：provider 检索抛异常 ⇒
   ``fail``（没做成）；检索正常但零命中 ⇒ ``ok`` + 空列表（结论就是"没有"）；未配置
   ``store`` 时无法比对既有文献表 ⇒ 候选的 ``existing`` 是 ``None``（未知），不是 ``False``。
3. ``search.providers`` 对每个 provider 发一次极小的真实请求；``ABFLOW_SKIP_NETWORK=1`` 时
   明确标 ``unverified``（未探测），而不是把"没探测"写成"可用"或"不可用"。正因为它真的发
   HTTP，``side_effect`` 是 ``network``（需要审批）而不是 ``read`` —— 声明成 ``read`` 等于
   在权限面上说"这个工具不联网、不必审批"，而它每次调用都会向外部源发起请求；声明与实际
   不符会让审批这个闸门在该拦的地方不拦。

## 文件落点（为什么这样定）
- ``search.download`` 下到 ``<workspace>/downloads/`` —— 中间态：文件名由 ``fetch`` 层
  slug 化并去重，下载器保证"不覆盖已有文件"。
- ``search.register`` 把文件收编进 ``<store.library>/<内容 hash 前缀-名>``（扁平、
  唯一落点；落点名由 ``locallib.library_landing`` 一处给，与 ``search.ingest_local``
  共用）：``schema.Literature.path`` 必须是 library/ 下的相对路径，绝对路径会被
  ``Literature.validate()`` 直接拒绝。旧 ``<store.library>/<lit_id>/<名>`` 布局
  读侧也不再支持（2026-11-22 业主裁定「旧工作区不必兼容」；``wellformed`` 把它
  报成 ``literature_layout_legacy`` 的 ``error``），读口只有 ``store.library_path``
  一处真身。收编失败
  时行照建、``path`` 置 ``null`` 并给 warning —— "知道有这篇但拿不到全文"本身就是有价值的
  结果（DESIGN.md §2.4）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.parse
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .base import ToolError, ToolRegistry, ToolSpec, fail, ok, tool
from .. import dedup as D
from .. import fetch as F
from .. import litavail as LAV
from .. import litread as LR
from .. import providers as P
from .. import schema as S
from .. import sysresidue as _SR   # SYSRESIDUE ④：`_keys` / `dedup_key` 与 A、locallib 同一处算
from .. import textutil as T
from ..litstage import CONTENT_CLAIM_WITHOUT_READ, LitStageError
from ..store import Store, StoreError

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
    ("fixture", "离线 fixture（读调用方给的候选清单，缺省 `<工作区>/fixtures/candidates.json`）："
                "不联网、确定性，供离线跑通与测试"),
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
    #: 装配期显式绑定的写者（空串 = 每次调用按 `identity` 现算，见 :meth:`actor`）。
    bound_actor: str = ""

    @property
    def actor(self) -> str:
        """这一次调用的写者名：实例级（K1 / AL-12，2026-11-19）。

        改前这里是 dataclass 的默认值 `"agent-A"` —— 装配期一次定死，于是走工具面落下的
        每一笔（`lit_availability` / `lit_reads` 的 actor 等）全是光秃秃的角色名，而同一张
        表上走实例内部链路的那几笔是 `agent-A-<名册名>`：同一件事两种粒度（lp-ball-8 实测
        98 条 vs 77 条）。现在与类路径同一个来源：`identity.resolve_identity`（唯一实现），
        每次调用现算 —— 调用点落在 `conductor.calling_as` 的临界区里，名册名 / 召唤标签
        都读得到。显式绑定且带实例标签的那一档优先（装配期折进来的身份）；读不到身份
        ⇒ 退回角色名（直调 / 单测逐字不变）。
        """
        from ..identity import actor_for, resolve_identity, split_actor

        bound = str(self.bound_actor or "").strip()
        if split_actor("A", bound).get("instance"):
            return bound
        got = resolve_identity(self.store, "A")
        resolved = str(got.get("actor") or "").strip()
        if got.get("attributed") and resolved:
            return resolved
        return bound or resolved or actor_for("A", "")

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
        """离线 fixture 的位置：配置 > 工作区。没有"仓库自带"的那一档（2026-11-22）。

        DEMORETIRE 之前这里还退到仓库里的 `demo/fixtures/candidates.json`
        （`providers` 里那个默认夹具常量已随 demo 退场删掉）；夹具必须由调用方
        提供（配置 `fixture_path`，或放在工作区的 `fixtures/candidates.json`）。
        返回"最像真的那一个"：存在的那一条优先，否则第一条候选（调用方据此报"不存在"）。
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
        out.append(self.workspace / "fixtures" / "candidates.json")
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


def _lit_file(ctx: _Ctx, rel: str) -> Path | None:
    """把一条 literature 行的 `path` 解析成盘上的文件；读不到 ⇒ `None`。

    ## 唯一真身：`store.library_path`（2026-11-22 业主裁定「旧工作区不必兼容」）

    改前这里有一段 workspace 回退（`except StoreError:` ⇒ 按工作区基准再拼一次）。
    它 2026-10-28 是有理由的：`_adopt_file` 当时承认两个坐标系（"先 `library/`，
    不存在再按 workspace 解释"），而真机 `projects/paper-rewrite-78` 有 4 行被
    `table.update` 改写成 `downloads/lit-*.pdf`，文件真在盘上而书架只数到 1 本
    （`have_path=5` / `missing_files=4` / `count=1`）。那时放宽的是"文件在哪"。

    裁定之后 `literature.path` 只有一种合法形态（扁平落点、相对 `library/`，
    `locallib.library_landing_name` 写、`store.library_path` 判），`_adopt_file`
    也不再产出第二个坐标系。所以回退整段删掉：它只服务过旧写法，而旧写法
    （`<lit_id>/<名>`、带 `library/` 前缀、`downloads/…` 工作区相对路径）现在
    明确"不再支持"。留着它就是同一份 `path` 写侧拒、读侧收 —— `litread` 与
    `store.library_path` 已经在 2026-11-22 对齐过同一条口径，这里不比它们宽。

    三态：`path` 是旧形态 ⇒ `None`（不读），但不算"文件不在" —— 旧形态与
    缺失是两种处置（改哪一行 vs 找哪一份文件）。逐行的受控读数由
    `_lit_blocked_note()` 在 `search.shelf` / `search.local` 的 `note` 里点名。
    越界（`../`、绝对路径绕出 `library/`）同样 `None`：`store.library_path` 是
    那道闸，这里不另开一条。
    """
    if not rel or ctx.store is None:
        return None
    try:
        inside = ctx.store.library_path(rel)
    except StoreError:
        # 旧形态 / 越界：唯一真身已经拒了。这里不许再拼第二个基准 ——
        # 那正是 2026-11-22 删掉的那段回退（它让旧写法照样被读回来）。
        return None
    return inside if (inside is not None and inside.is_file()) else None


def _lit_blocked_note(ctx: _Ctx, rows: Iterable[Mapping[str, Any]]) -> str:
    """读不到的行的受控读数：逐行点名 `lit_id=path`（空串 = 这一批里没有）。

    两种"读不到"要分开说，因为处置相反：

    * 形状非法（`library/` 前缀 / 带斜杠而首段不是文献号）—— 改这一行的 `path`；
    * 越界（`../` / 绝对路径绕出 `library/`）—— 这一份根本不是这一行的全文。

    历史形态（`<4位号>/<名>`、扁平一段）不在这里报"读不到"：它们读得通
    （`store.library_path` 只拒非法形状），形态的 legacy 读数归 `wellformed`。

    为什么要有它：`_lit_file` 对这几种形态返回 `None`，于是行落进 `missing_files`。
    那是"读不到"没错，但理由丢了。工具面的 `note` 是已声明的键，逐条点名，
    模型与读报告的人都不必去猜"这一条为什么不在书架上"。
    """
    bad_shape: list[str] = []
    outside: list[str] = []
    for row in rows:
        rel = str(row.get("path") or "").strip()
        if not rel:
            continue
        who = f"{row.get('lit_id') or '?'}={rel}"
        if LR.path_shape(rel) == LR.SHAPE_BAD:
            bad_shape.append(who)
            continue
        if ctx.store is not None:
            try:
                ctx.store.library_path(rel)
            except StoreError:
                outside.append(who)
    parts: list[str] = []
    if bad_shape:
        parts.append(
            f"另有 {len(bad_shape)} 条 `path` 形状非法：" + "、".join(bad_shape)
            + " —— 规范是 `<6位号>/<文件名>`（2026-11-25 业主裁定）；扁平落点已退役"
            "（2026-11-25 起），带 `library/` 前缀的写法也不读。它们被算进 `missing_files`，"
            "理由不是「文件不在」，而是「这一行的 path 写法不再支持」：要离线引用请把文件"
            "放进 `library/<6位号>/` 并把这行的 `path` 改成 `<6位号>/<文件名>`。")
    if outside:
        parts.append(
            f"另有 {len(outside)} 条 `path` 越出 `library/`：" + "、".join(outside)
            + " —— 唯一真身 `store.library_path` 拒了它（`../` 或绝对路径绕出库根），"
            "工作区外的文件不是这一行的全文；它们同样算进 `missing_files`。")
    if not parts:
        return ""
    return "；" + "；".join(parts)


def _shelf_row(ctx: _Ctx, row: Mapping[str, Any]) -> dict[str, Any] | None:
    """把一条 literature 行变成书架条目；`path` 不在盘上则返回 None（不是书架上的书）。"""
    rel = str(row.get("path") or "")
    if not rel or ctx.store is None:
        return None
    abs_path = _lit_file(ctx, rel)
    if abs_path is None:
        return None
    dl = dict(row.get("download") or {})
    return {
        "lit_id": str(row.get("lit_id") or ""),
        "title": str(row.get("title") or ""),
        "path": rel,
        "abs_path": str(abs_path),
        "bytes": int(dl.get("bytes") or abs_path.stat().st_size),
        "pages": dl.get("pages"),
        "has_text_layer": dl.get("has_text_layer"),
        # 来源如实分两档：「人放到本地目录」进来的（`source_path` 有值）与
        # 「A 从网上下来」的（没有 `source_path`）。这一栏决定"离线可引用"是否成立，
        # 也决定"这篇文献从哪来"这条链会不会说假话。
        "origin": "local_ingest" if dl.get("source_path") else "downloaded",
        "sha256_12": str(dl.get("sha256") or "")[:12],
    }


#: 一行 literature 上可能记着「这篇的全文去哪拿」的字段。
#: 业主裁定（2026-10-28）：`schema.Literature` 里没有 `pdf_url` / `landing_url`
#: 这两格，真机那趟（projects/paper-rewrite-78）把定位链接记在 `download.url`
#: 里，note 逐字写着「只登记了候选源给出的定位链接（url 这一格），没有下载字节；
#: 要全文请按它重取」—— 那个 URL 就是 landing 定位，必须算作"有地址"。
#: 判据 `tests/test_the_shelf_reports_fulltext_coverage.py` 里有一条负控专门钉它。
_LOCATION_FIELDS: tuple[str, ...] = ("pdf_url", "landing_url")


def _row_has_location(row: Mapping[str, Any]) -> bool:
    """这一行有没有可取全文的定位（离线全文之外的地址）。

    三态纪律：`False` 只说「行上没有地址」——它不是「这篇不存在」。
    它说的是一句关于我们自己的话：没去取（连链接都没留下），处置是去检索，
    而不是把这一篇从证据链里划掉。
    """
    for key in _LOCATION_FIELDS:
        if str(row.get(key) or "").strip():
            return True
    dl = row.get("download")
    if isinstance(dl, Mapping) and str(dl.get("url") or "").strip():
        return True
    return False


def _shelf_coverage(ctx: _Ctx, rows: Iterable[Mapping[str, Any]],
                    judged: list | None = None) -> dict[str, Any]:
    """``search.shelf`` 的 ``coverage`` 块：整张文献表的全文覆盖率。

    为什么它必须自己数一遍（而不是从 `books` 那里拿 `len`）：`query` /
    `lit_id` / `limit` 只筛"这一次要看哪几本"，而覆盖率是库级读数。用 `books`
    数的话，A 一旦带 `lit_id` 查某一篇，覆盖率就变成 1/1 = 100% —— 缺口正好在
    最需要它的时候被抹平（真机：32 篇里只有 5 篇有全文）。

    五个数的口径（`draft/173` 阶段 ③ 第 2A 步）：
      total         文献表行数
      with_fulltext 真正在盘上、可离线引用的（与 `books` 同一判据 `_shelf_row`）
      missing       total - with_fulltext（"没有离线全文"）
      no_location   既没有 `path`、也没有任何定位的条数 —— 没去取 ≠ 不存在
      rate          with_fulltext / total；total=0 时给 `None`（不许折成 0）

    `judged` 是调用方已经逐行做过的 `_shelf_row` 结果（与 `rows` 同序）：给了就直接用它，
    不再把同一行的文件存在性判第二遍 —— 判据仍是 `_shelf_row` 那一份，这里只是复用结论。
    """
    total = 0
    with_fulltext = 0
    no_location = 0
    for i, row in enumerate(rows):
        total += 1
        item = judged[i] if judged is not None else _shelf_row(ctx, row)
        if item is not None:
            with_fulltext += 1
        elif not str(row.get("path") or "").strip() and not _row_has_location(row):
            # 行上有 `path` 但文件不在盘上 ⇒ 它有定位（只是定位坏了），
            # 那是 `missing_files` 那一档，不是"没去取"。
            no_location += 1
    return {
        "total": total,
        "with_fulltext": with_fulltext,
        # total=0 ⇒ None：空表没有分母，"没有文献"与"覆盖率 0 成"是两件事。
        "rate": (with_fulltext / total) if total else None,
        "missing": total - with_fulltext,
        "no_location": no_location,
        # 这一块是查出来的读数（与"猜"分开）：读表失败时整件工具 ok=False，
        # 根本不会给出一个 coverage（判据里有一条负控钉这条不对称）。
        "checked": True,
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
    # 每行的书架判定只做一次：`books` / `missing_files` / `coverage` 三处共用这份结论
    # （`_shelf_coverage` 拿到的是同一份 `judged`，不再逐行重判文件存在性）。
    judged = [_shelf_row(ctx, row) for row in rows]
    filtered_out = 0
    for i, row in enumerate(rows):
        if needle and needle not in f"{row.get('title') or ''} {row.get('path') or ''}".lower():
            filtered_out += 1
        if lit_id and str(row.get("lit_id") or "") != lit_id:
            continue
        item = judged[i]
        if item is None:
            if row.get("path"):
                missing += 1
            continue
        if needle:
            hay = f"{item.get('title') or ''} {item.get('path') or ''}".lower()
            if needle not in hay:
                continue
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
            "filtered_out": filtered_out,
            "rows_total": len(rows),
            "have_path": sum(1 for r in rows if r.get("path")),
            "missing_files": missing,
            "local_ingest": sum(1 for b in books if b["origin"] == "local_ingest"),
            "downloaded": sum(1 for b in books if b["origin"] == "downloaded"),
            "truncated": truncated,
            "books": books,
            # 整张表的覆盖率（2026-10-28，阶段 ③ 第 2A 步）：A 从这一天起看得见
            # "32 篇里只有 5 篇能离线引用"这个缺口，而不是只知道书架上摆着哪几本。
            "coverage": _shelf_coverage(ctx, rows, judged=judged),
            "note": (
                "这是**离线**来源：这些文件的正文就在工作区里，"
                "可以用 search.local 按主题取逐字摘录。"
                "`missing_files` 是「行上写了 path、但按唯一真身 `store.library_path`"
                "读不到那一份」的条数 —— 旧布局（不再支持）、越界、文件不在都算在里面；"
                "它不是 0 时，那些书**取不到正文**，不要当它们存在。"
                "`coverage` 是**整张文献表**的全文覆盖率（与本次的 query/lit_id/limit 无关）："
                "`with_fulltext`/`total` 是「离线能引用几成」，`rate` 在 total=0 时是 null；"
                "`no_location` 是「我们连可取全文的地址都没有 ⇒ **没去取**」——"
                "它**不是**「这篇不存在」，两者必须分开读："
                "有地址但还没取的篇落进 `missing`，不落进 `no_location`。"
            ) + _lit_blocked_note(ctx, rows),
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
            ) + _lit_blocked_note(ctx, rows),
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
    """``search.providers``：列出可用 provider（真实探测可用性）。

    ## 协作式截止的检查点（C1FIX-TOOLS ③，2026-11-23）

    每一个源探测之前问一次截止（`raise_if_timed_out`），到点就在那里停住、抛受控
    超时（`PROVIDERS_TIMEOUT`），由 `agent_loop` 换成 DSH 形状的超时结果 —— 与
    `search.literature` 在"每个源那一次调用之前"设检查点同一条口径。

    为什么必须接（真机 C-1 证据）：`projects/sylow-1` 的 session
    （`sessions/2026-11-22e.jsonl`，13:36:17，role=A）落了一条
    `state=deadline_passed_unobserved` 的读数 —— `PROVIDERS_TIMEOUT after 30000ms`，
    而实际用了 39328ms：表里声明了 30 秒，处理函数却一次都没看那口钟，于是四个源
    依次探测把这一步拖到 39 秒，结果照收。声明了截止而不看，比没有截止更糟：侧信道
    上写着"30 秒"，模型与编排读到的却是"这一件限过时"。

    为什么检查点放在"每个源之前"而不是函数开头：开头那一处只能挡住"整件根本没开始"，
    而这一件的耗时是逐源叠加的（每个源一次网络探测，`_PROBE_TIMEOUT` 8 秒 × 4 个源）。
    放在每个源之前，到点就停在已经探完的那几个之后 —— 不重探、也不假装探完。
    """
    rows = []
    for name in _known_names(ctx):
        # 到点即停（受控超时，不"照收"）：`ToolTimedOut` 会被 `agent_loop` 认成
        # 本工具自己的那口钟响了（`tool_timeout.OBSERVED`），结果被换成超时结果。
        from ..tool_timeout import raise_if_timed_out

        raise_if_timed_out()
        rows.append(_probe_provider(ctx, name))
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
        # 名字（2026-11-03，153-U-09 第二笔）：出口那本 multi 早就叫 `source_refusals`
        # （`_h_literature` 的 data 里那一格）；这里跟着用同一个名字，免得同一个量
        # 在函数内部与出口各叫一个名字（业主 2026-11-02 批准动这一处）。
        "source_refusals": dict(getattr(mp, "last_refusals", None) or {}),
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
                source_refusals=multi["source_refusals"],
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
    # 2026-10-28（阶段 ③ 2C）：broad 的候选在交给 A 之前过一遍主题自检（只标不删）。
    # 为什么还要在工具层再标一次：单源那一支调的是 provider 本身（不经
    # `MultiProvider`），多源那一支才走合并入口。两个入口、同一个口径
    # （`P.mark_topic_selfcheck`），所以这里对两支都跑一遍 —— 它对已标过的候选是幂等的。
    # 三态：related / off_topic / unknown（unknown = 机器判不了，别当 off_topic）。
    candidates = P.mark_topic_selfcheck(candidates, topic, description=description, mode=mode)
    # 逐源读数两条路都给（同一形状）：多源来自 `MultiProvider` 的台账，
    # 单源来自 `_single_source_reading`（同样复用 providers 层那两处判据）。
    source_rows = (multi["sources"] if multi else
                   _single_source_reading(prov, candidates))
    if multi is not None:
        # 多源那一支的逐源读数已经由 `_multi_source_reading` 折过一遍（`failed` / `refused`
        # 就是同一批 `sources` 行按同一判据数出来的），这里直接复用，不再重算两遍。
        source_failures = list(multi["failed"])
        source_refusals = list(multi["refused"])
    else:
        source_failures = sorted(r["name"] for r in source_rows if r["status"] == "failed")
        source_refusals = sorted(r["name"] for r in source_rows if r["refused"])

    candidates = list(candidates or [])
    # C1FIX-URISRC ①：把这次 provider **真的报回来**的地址记账。`lit.stage_add` 判
    # "自报 provider" 与 `search.download` 判 "这地址是不是 provider 给的" 都只认这一份 ——
    # 它是"候选行上的地址有出处"的唯一机器证据（模型自己写的地址永远不在里面）。
    record_provider_urls(ctx, candidates)
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
        raw = cand.raw or {}
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
                "sources": list(raw.get("providers") or []),
                "channel": raw.get("channel"),
                "cited_by_count": raw.get("cited_by_count"),
                # 2026-10-28（阶段 ③ 2C）：broad 模式的主题自检结论（只标不删）。
                # `providers.mark_topic_selfcheck` 已经把它挂进 `raw`；这里原样转出去 ——
                # 它是 A 判断"要不要为这条花一次判官调用"的唯一机器读数。
                # 三态：related / off_topic / unknown（`unknown` = 机器判不了，别当 off_topic）。
                # 非 broad 模式没有这一格（`None`），不是「判过了、相关」。
                "topic_selfcheck": raw.get("topic_selfcheck"),
            }
        )

    # 四个计数一趟数完（`items` 最多 `limit` 条，四遍 sum 只是把同一批行扫四次）。
    new_count = existing_count = unknown_count = batch_duplicate_count = 0
    for item in items:
        flag = item["is_new"]
        new_count += flag is True
        existing_count += item["existing"] is True
        unknown_count += flag is None
        batch_duplicate_count += bool(item["batch_duplicate"])
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
        "batch_duplicate_count": batch_duplicate_count,
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


#: `search.download(cand=…)` 认的候选前缀（与 `text.extract` 的 `lit_id` 同一套写法：
#: `cand:000012` / `slot:000012`，也给裸槽位号）。为什么另开一格参数、不借 `hint`：
#: `hint` 是给人看的下载说明，把它当编号用等于让"这一条候选"靠字符串约定表达 ——
#: 而这里要的是"这次尝试记在哪条候选上"这件结构事实。
_DOWNLOAD_CAND_PREFIXES: tuple[str, ...] = ("cand:", "candidate:", "slot:")


def _download_slot(cand: str) -> str:
    """把 `cand` 归一成裸槽位号（不是候选写法 ⇒ 原样当槽位号）。"""
    text = str(cand or "").strip()
    low = text.lower()
    for prefix in _DOWNLOAD_CAND_PREFIXES:
        if low.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def _download_candidate(ctx: _Ctx, slot: str) -> tuple[dict | None, Any]:
    """按槽位取候选行；取不到 ⇒ `(None, fail(...))`（受控拒，不写回执）。

    不写回执的理由与 `text.extract` 的候选期同一条：回执是"这一条候选试过"的证据，
    写到一条不存在的候选上就是把"随便给个号"记成"试过了一次"。
    """
    if ctx.store is None:
        return None, fail("未配置 store：认不出候选槽位（不是「这一条没试过」）",
                          kind="no_store")
    try:
        rows = list(ctx.store.rows("lit_candidates"))
    except Exception as exc:  # noqa: BLE001 - 表读不出来是"判不了"，不是"没有这一条"
        return None, fail(f"候选表读不出来（{type(exc).__name__}: {exc}）⇒ 这一格判不了",
                          kind="store_error")
    row = next((r for r in rows if str(r.get("slot") or "") == str(slot)), None)
    if row is None:
        known = [str(r.get("slot") or "") for r in rows][:8]
        return None, fail(
            f"待新增列表里没有槽位 {slot!r}（序号不复用；下载尝试要指向一条真的候选）",
            kind="unknown_slot", slot=str(slot), known=known)
    return dict(row), None


# --------------------------------------------------------------------------- 下载地址的来源
#
# C1FIX-DL ②（2026-11-23）：真机 `projects/sylow-1`（sid `2026-11-22e`，role=A）17 次
# `search.download` 里 4 次是猜文件名 —— `kconrad…/sylowthm.pdf`、`…/sylow.pdf`（两次）、
# `fm.mizar.org/…/sylow.pdf`，4 次全 404；而真名是 `sylowpf.pdf`（产品下载器下它
# ok=True / 200 / 279,580 B）。这不是模型"不爱用候选"，而是工具面允许它自拼：
# `url` 是必填项，`cand` 只用来记回执，两者之间没有任何一致性校验。
#
# 于是这里补上"下载地址的来源"这一层：`cand` 给了 ⇒ 唯一合法来源是候选行记录的地址
# （`pdf_url` → `landing_url` → `url`）；自拼的地址受控拒（`url_not_from_candidate`，
# 一个请求都不发、也不写回执 —— 它没"试过"）。`cand` 没给 ⇒ 只能软标"自拼地址"，
# 因为"下一段任意 URL"本身是合法用法（真机那两次 `api.openalex.org` 抓 JSON 正是这一支）。

#: 候选行上"记录过的下载地址"的字段，按优先级从高到低。
#:
#: 为什么有 `url` 这一格：盘上的 `lit_candidates` 只有 `url`（`litstage.stage_entries`
#: 把候选的 `pdf_url` 折进它，见 `litstage._top_up`）；`pdf_url` / `landing_url` 两格是
#: 前向兼容 —— `literature` 行上确有它们（`_LOCATION_FIELDS`），候选行将来若原样留存
#: 也应当被认。
_CANDIDATE_URL_FIELDS: tuple[str, ...] = ("pdf_url", "landing_url", "url")


def _candidate_urls(row: Mapping[str, Any]) -> list[str]:
    """候选行上记录的全部地址（去重、保序、跳过空串）。"""
    out: list[str] = []
    for name in _CANDIDATE_URL_FIELDS:
        url = str(row.get(name) or "").strip()
        if url and url not in out:
            out.append(url)
    return out


def _url_key(url: str) -> tuple[str, str, str, str]:
    """把一个地址折成"同一份文件"的比较键：scheme / host:port / path / query。

    刻意抹平的三件事都不改变"下到的是哪一份"：`http` ↔ `https`（同一台站的两个入口）、
    主机名大小写、路径末尾的斜杠。不抹平 query：`?article=1022&context=ebooks`
    换一个数就是另一份文件。
    """
    parts = urllib.parse.urlsplit(str(url or "").strip())
    scheme = (parts.scheme or "").lower()
    if scheme in ("http", "https"):
        scheme = "http(s)"
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:  # 畸形端口串（`urlsplit` 认了、`port` 抛）
        return (scheme, host, parts.path, parts.query)
    if port in (80, 443, None):
        port = None
    netloc = f"{host}:{port}" if port else host
    path = urllib.parse.unquote(parts.path).rstrip("/")
    return (scheme, netloc, path, parts.query)


def _same_url(left: str, right: str) -> bool:
    """两个地址是不是同一份（口径见 :func:`_url_key`）。空串与任何东西都不相等。"""
    if not str(left or "").strip() or not str(right or "").strip():
        return False
    return _url_key(left) == _url_key(right)


def _url_source_of(row: Mapping[str, Any], url: str) -> str:
    """这个地址在候选行上记在哪一格：`candidate_pdf_url` / `candidate_landing_url` /
    `candidate_url`（都不匹配 ⇒ `candidate_other`，正常不会出现）。"""
    for name in _CANDIDATE_URL_FIELDS:
        if _same_url(url, str(row.get(name) or "")):
            return f"candidate_{name}"
    return "candidate_other"


def _resolve_candidate_download_url(
    row: Mapping[str, Any], submitted: str
) -> tuple[str, str, Any]:
    """`cand` 路径的地址裁决：返回 `(采用的地址, url_source, 受控拒或 None)`。

    三种结局，各自对应现场的一种形状：

    * 候选行有记录地址、调用方给的地址是记录里的一个（或没给）⇒ 用记录里的地址，
      `url_source=candidate_*`。这就是"必须从候选行取 URL"那条口径的落点。
    * 候选行有记录地址、调用方给的是别的地址 ⇒ 受控拒 `url_not_from_candidate`，
      并把记录里的地址原样回给模型（真机 4 次猜文件名全 404，就是因为没有这一道）。
    * 候选行没有记录地址 ⇒ 只能用调用方给的（`url_source=unrecorded`）：
      这时"自拼"不是"与记录矛盾"，而是"记录里没有" —— 拒它会挡掉真机那条
      "暂存只带题录、全文另找"的正路（`projects/sylow-1` 的 slot 000055 就是这样）。
      调用方也没给 ⇒ 受控拒 `url_not_from_candidate`（不知道该下哪一个）。
    """
    recorded = _candidate_urls(row)
    slot = str(row.get("slot") or "")
    submitted = str(submitted or "").strip()
    if not recorded:
        if not submitted:
            return "", "", fail(
                "这一条候选没有记录地址，调用方也没给 url ⇒ 不知道该下哪一个"
                "（不是「这一条试过、拿不到全文」）",
                kind="url_not_from_candidate", cand=slot, candidate_urls=[],
            )
        return submitted, "unrecorded", None
    if submitted:
        for url in recorded:
            if _same_url(submitted, url):
                return url, _url_source_of(row, url), None
        return "", "", fail(
            f"url 不在候选 {slot} 记录的地址里（这是自拼地址）⇒ 拒绝下载："
            f"记录的地址是 {recorded}。请改用记录里的 pdf_url（或干脆只给 "
            f"`cand=\"{slot}\"`，由工具从候选行取）；一次下载试一个「猜出来的文件名」"
            "只会烧掉一次请求（真机 4 次自拼全部 404）。",
            kind="url_not_from_candidate", cand=slot, candidate_urls=recorded,
            url=submitted,
        )
    return recorded[0], _url_source_of(row, recorded[0]), None


def _unbound_url_source(ctx: _Ctx, url: str) -> str:
    """没给 `cand` 时，这个地址是不是某条候选记录过的（三态：不许折成布尔）。

    `candidate_record`：任一条候选行的记录地址就是它 ⇒ 不是自拼；
    `self_constructed`：读到了候选表、里面没有它 ⇒ 自拼地址（软警示，不拒）；
    `unknown`：没配 store / 表读不出来 ⇒ 判不了（既不警示也不背书）。
    """
    if ctx.store is None:
        return "unknown"
    try:
        rows = list(ctx.store.rows("lit_candidates"))
    except Exception:  # noqa: BLE001 - 读不到不等于"里面没有"
        return "unknown"
    for row in rows:
        for recorded in _candidate_urls(row):
            if _same_url(url, recorded):
                return "candidate_record"
    return "self_constructed"


def _self_constructed_url_warning(url: str) -> str:
    """自拼地址的那一句可读警示（`cand` 没给、且不在任何候选记录里）。"""
    return (
        f"url_source=self_constructed：这个 url 不在任何候选行的记录地址里、`cand` 也没给 ⇒ "
        f"它是自拼地址：{url}。"
        "真机 C-1（`projects/sylow-1` / `2026-11-22e`）17 次 `search.download` 里 4 次是"
        "这类猜出来的文件名，4 次全 404（真名是 `sylowpf.pdf`，而候选的 `pdf_url` 里本来"
        "就有它）。要判收请先把候选暂存（`lit.stage_add` 带 pdf_url）再用 "
        "`search.download(cand=\"<槽>\")` 取记录里的地址；确实是外部地址就照常下。"
    )


def _unrecorded_url_warning(slot: str, url: str) -> str:
    """候选行没有记录地址时的那一句（地址不是与记录矛盾，而是记录里没有）。"""
    return (
        f"url_source=unrecorded：候选 {slot} 这一行没有记录地址（暂存时没带 pdf_url），"
        f"这次用的是外部地址 {url} ⇒ 核对不了它是不是候选里的那条直链。"
        "下次暂存时把 pdf_url 一并给上，下载就能按候选记录走。"
    )


# --------------------------------------------------------------------------- 候选行地址的来源
#
# C1FIX-URISRC ①（2026-11-23）：C1FIX-DL 加的「地址来源」层堵的是"同一候选、另给一个
# 自拼地址"；但它认「候选行记录过的地址」为合法来源，而候选行的 `url` 正是模型自己经
# `lit.stage_add` 写进去的 —— 于是"先把自己拼的地址洗进候选行、再用 `cand=` 取它"
# 这条路一道闸都不经过。真机 `projects/sylow-1` 那 4 次猜文件名就是这条路：模型不是
# "绕过了候选"，而是把猜出来的名字写成了一个候选。
#
# 这一层把"候选行上这个地址是从哪来的"记下来，并让 `search.download` 的收据带上它：
#   `provider`          `search.literature` 这次真的报过这个地址（唯一"有出处"的一档）
#   `webpage`           模型自报"从网页正文里读到的"（合法用法，但框架核不了）
#   `self_constructed`  模型自己在 `lit.stage_add` 里写的（没声明时按这一档 —— 事实如此）
#   `unknown`           这一行没有来源记录（自动链路暂存 / 本功能上线前的行 / 通用写口路线）
#
# ## 为什么不能只信模型自报
# 自报的 `provider` 正是洗白通道要的那句话：模型尽可以把自己拼的地址标成 provider 给的。
# 所以 `provider` 这一档以**框架自己记的 provider 返回地址**为准：`search.literature`
# 把每条候选的 `pdf_url` / `landing_url` 追加进 `data/lit_url_origins.jsonl`，
# `lit.stage_add` 拿自报的那一档去对；对不上就受控拒（`url_origin_unverified`）——
# 说谎是这里唯一没有正当用法的形态。
#
# ## 为什么 `self_constructed` / `webpage` 不上硬闸
# 模型从网页正文里读到一条真实 PDF 链接是合法正路（`text.extract` 之后从正文里挑链接），
# 它必然不在 provider 的返回里；硬闸会把它和"自拼"一起挡掉。所以这两档只做透明化
# （收据点名 + 警示）：让模型每次都看到"这地址是你自己写的，不是 provider 给的"。
# 硬闸只落在"谎报 provider"这一档。
#
# ## 台账为什么是 `data/` 下的文件而不是表
# 它不是文献库的事实，而是"这一行的地址从哪来"这一步的痕迹；`schema.LitCandidate` 加
# 一格要动 schema 版本与磁盘契约（FC-27 的 schema-migration），而这张台账只要
# "按地址追加一行、按地址读回来"。`data/` 下的文件对任何角色的 `fs.*` 写口一律拒
# （`fs_tools.RESERVED_ARTIFACT_TABLE` 里 `("*", "prefix:data/")` 那一行），所以模型伪造不了它。

#: 台账落点（与 `litavail` 的 `data/lit_availability.jsonl` 同层同形：追加式 JSONL）。
_URL_ORIGIN_LEDGER_NAME: str = "lit_url_origins.jsonl"
_URL_ORIGIN_DIR: str = "data"

#: 模型可以在 `lit.stage_add` 的 entry 上自报的三档（`entries[].url_origin`）。
URL_ORIGINS: tuple[str, ...] = ("provider", "webpage", "self_constructed")
#: 自报 `provider` 而这次没有任何 provider 返回过它 —— 谎报档（写侧拒、读侧也拒）。
URL_ORIGIN_UNVERIFIED: str = "declared_provider_unverified"
#: 这一行没有来源记录。三态纪律：判不了就是判不了，**不许**折成 `provider`。
URL_ORIGIN_UNKNOWN: str = "unknown"

#: 台账里 `kind` 的两档：provider 报来的地址 / 模型写进候选行的地址。
_ORIGIN_KIND_PROVIDER: str = "provider_url"
_ORIGIN_KIND_STAGED: str = "staged_url"


def url_origin_ledger_path(ctx: _Ctx) -> Path:
    """这张工作区的地址来源台账路径（与 `store.root` 同一层：`register` 的 workspace 缺省就是它）。"""
    return Path(ctx.workspace) / _URL_ORIGIN_DIR / _URL_ORIGIN_LEDGER_NAME


def _origin_records(ctx: _Ctx) -> list[dict]:
    """把台账读成一列记录（坏行跳过，不把"读坏了"折成"有一条记录"）。

    文件不存在 ⇒ 空清单（"还没有任何来源记录"，与"读不到"不同：读不到也不抛 ——
    这一层的读侧本来就是判来源，读坏了只能判 `unknown`，判不了不许冒充 provider）。
    """
    path = url_origin_ledger_path(ctx)
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        # 读不出来 ⇒ 后面按 `unknown` 处理（fail-closed 的方向：不冒充 provider）
        return []
    out: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            got = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(got, dict):
            out.append(got)
    return out


def _origin_index(ctx: _Ctx) -> dict[tuple[str, str, str, str], dict]:
    """`地址键 -> 来源读数` 的视图（后写的覆盖先写的）。

    两遍：先折 staged 记录，再把 provider 记录盖上去 —— provider 是**证据**，
    它压过任何自报（"模型先自报 webpage、之后 provider 真报了这个地址"时，后者才是
    这条地址的真实出处；反之 provider 记过之后又被一次不带声明的重进覆盖，就会把
    一条有出处的地址读成自拼的）。
    """
    records = _origin_records(ctx)
    index: dict[tuple[str, str, str, str], dict] = {}
    for rec in records:
        url = str(rec.get("url") or "").strip()
        if not url or str(rec.get("kind") or "") != _ORIGIN_KIND_STAGED:
            continue
        index[_url_key(url)] = {
            "url_origin": str(rec.get("url_origin") or URL_ORIGIN_UNKNOWN),
            "declared": str(rec.get("declared") or ""),
            "source": f"lit.stage_add（{str(rec.get('at') or '?')}）",
        }
    for rec in records:
        url = str(rec.get("url") or "").strip()
        if not url or str(rec.get("kind") or "") != _ORIGIN_KIND_PROVIDER:
            continue
        index[_url_key(url)] = {
            "url_origin": "provider",
            "provider": str(rec.get("provider") or ""),
            "source": f"search.literature（{str(rec.get('at') or '?')}）",
        }
    return index


def _origin_of(index: Mapping[Any, dict], url: str) -> tuple[str, str]:
    """这个地址的来源：`(档位, 细节)`。没有记录 ⇒ (`unknown`, 空串)。"""
    found = index.get(_url_key(str(url or "").strip()), {})
    return (str(found.get("url_origin") or URL_ORIGIN_UNKNOWN),
            str(found.get("provider") or found.get("declared") or ""))


def record_provider_urls(ctx: _Ctx, candidates: Iterable[Any]) -> int:
    """把 `search.literature` 这一次真的报回来的地址记进台账（返回写了几条）。

    只记 `pdf_url` / `landing_url` 两格：它们是 provider 给的"去哪拿全文"，
    也正是 `_resolve_candidate_download_url` 认的那两格。记不上不抛（检索结果是主产出，
    台账只是来源读数）：抛了会把一次成功的检索变成失败。
    """
    rows: list[dict] = []
    for cand in candidates or ():
        label = str(getattr(cand, "provider", "") or "")
        for name in ("pdf_url", "landing_url"):
            url = str(getattr(cand, name, "") or "").strip()
            if not url:
                continue
            rows.append({"kind": _ORIGIN_KIND_PROVIDER, "url": url,
                         "provider": label, "at": S.now_iso()})
    if not rows:
        return 0
    path = url_origin_ledger_path(ctx)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                    default=str) + "\n")
    except OSError:
        # 台账写不进去只是"这次没有来源读数"（读侧按 unknown 处理），不许让检索失败
        return 0
    return len(rows)


def _stage_origin_plan(ctx: _Ctx, items: Sequence[Mapping[str, Any]]) -> tuple[
        list[dict], list[dict], list[dict]]:
    """逐条算出暂存记录的来源；返回 `(要记的, 谎报 provider 的, 词表外的自报)`。

    `url_origin` 不填 ⇒ 按 `self_constructed` 记（模型把地址写进了候选行，这是事实，
    不是指控）；填了 `provider` 而台账里没有 provider 报过这个地址 ⇒ 进第二张表
    （由调用方受控拒）；填了词表外的值 ⇒ 进第三张表（schema 的 enum 已挡，直调也挡）。
    """
    index = _origin_index(ctx)
    plans: list[dict] = []
    unverified: list[dict] = []
    bad: list[dict] = []
    for raw in items:
        url = str(raw.get("url") or raw.get("pdf_url") or "").strip()
        declared = str(raw.get("url_origin") or "").strip()
        if declared and declared not in URL_ORIGINS:
            bad.append({"title": str(raw.get("title") or ""), "url": url,
                        "url_origin": declared})
            continue
        if not url:
            continue
        origin, _detail = _origin_of(index, url)
        if declared == "provider" and origin != "provider":
            unverified.append({"title": str(raw.get("title") or ""), "url": url})
            continue
        plans.append({
            "url": url,
            "declared": declared,
            "url_origin": "provider" if origin == "provider" else (declared or "self_constructed"),
        })
    return plans, unverified, bad


def _record_staged_origins(ctx: _Ctx, plans: Sequence[Mapping[str, Any]], *,
                           request_id: str) -> int:
    """把这一次暂存的"地址 + 来源"逐条追加进台账（返回写了几条）。"""
    if not plans:
        return 0
    path = url_origin_ledger_path(ctx)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as fh:
            for plan in plans:
                row = {"kind": _ORIGIN_KIND_STAGED, "url": str(plan.get("url") or ""),
                       "url_origin": str(plan.get("url_origin") or URL_ORIGIN_UNKNOWN),
                       "declared": str(plan.get("declared") or ""),
                       "request_id": str(request_id or ""), "actor": ctx.actor,
                       "at": S.now_iso()}
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                    default=str) + "\n")
    except OSError:
        # 台账写不进去：下一次下载会按 `unknown` 读（透明化少一档，但不改变下载行为）
        return 0
    return len(plans)


def _origin_warning(origin: str, url: str, slot: str) -> str:
    """`search.download` 收据里那一句来源说明（`provider` 不产生警示 —— 没消息就是好消息）。

    三档各有各的下一步：`self_constructed` ⇒ 换用 provider 给的地址；
    `webpage` ⇒ 照下，但别把"网页里读到的链接"说成"provider 给的"；
    `unknown` ⇒ 这一行不是经 `lit.stage_add` 记的来源（自动链路 / 老行），下载照下。
    """
    where = f"候选 {slot} 的" if slot else ""
    if origin == "provider":
        # 有出处 ⇒ 没有消息就是好消息（收据不拿一行噪声去换一句"这确实是真的"）
        return ""
    if origin == "webpage":
        return (
            f"url_origin=webpage：{where}地址 {url} 是你在 `lit.stage_add` 里自报「从网页正文里"
            "读到的」。框架核不了它（它不在任何 provider 这次返回的 pdf_url/landing_url 里）——"
            "能下就照下，但**别**把它说成「provider 给的」。"
        )
    if origin == URL_ORIGIN_UNKNOWN:
        return (
            f"url_origin=unknown：{where}地址 {url} 没有来源记录（这不是经 `lit.stage_add` 记的 "
            "provider 地址 —— 自动链路暂存的行、本功能上线前的行、或通用写口写的行都会落到这一档）。"
            "下载照下；要一条可复核的来源，请重新 `search.literature` 拿 pdf_url 再暂存一次。"
        )
    return (
        f"url_origin=self_constructed：{where}地址 {url} 是你在 `lit.stage_add` 里自己写的"
        "（这次没有任何 provider 返回过它）—— 它不是「候选记录的地址」担保的那一份。"
        "能下就照下，但别把它当「provider 确认过的直链」；真机 4 次猜文件名全 404 就是这个形状。"
    )


def _record_download_attempt(ctx: _Ctx, slot: str, row: Mapping[str, Any], *,
                             url: str, fetch_kind: str) -> dict | None:
    """把一次失败的下载记成一条"试过、拿不到可读文本"的回执（`extract_failed`）。

    ## 档位为什么复用 `extract_failed`，不新造"下载失败"一档

    回执回答的是"这一条到底试没试过"。下载失败与抽取失败对下游是同一件事：试过、
    拿不到可读文本（差别只在"有没有字节"，那是 `note` / `fetch_kind` 的读数）。
    新造一档要同时改 `litread` 的受控词表、`litavail` 的收执两档、`check_read` 与
    入库闸四处 —— 而闸的口径一个字都不该变（仍要"有尝试回执"才准 `metadata_only`）。
    所以档位不动，来源记在 `source` / `note` 里：审计读得出这次是下载死的还是抽死的。

    只在「拿不到可读全文」时写：干净的成功下载意味着盘上有可读字节，`metadata_only`
    那时是假话（`_read_evidence_gate` 会按"盘上有字节却报仅题录"拒），所以干净成功
    不写回执。落地页例外（`ok=True` + `content_type_mismatch`）：字节落盘了，但那
    是一张 HTML 落地页、不是全文 —— 它同样回答"试过一次、拿不到可读文本"，所以也写。
    """
    if ctx.store is None:
        return None
    return LAV.record_read(
        ctx.store.root, str(row.get("request_id") or ""), str(slot),
        LR.FULLTEXT_EXTRACT_FAILED, source=str(url or ""),
        note=f"search.download.{fetch_kind or 'failed'}",
        candidate=row, actor=ctx.actor)


def _h_download(ctx: _Ctx, url: str, hint: str = "paper", max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
                cand: str = "") -> Any:
    """``search.download``：把 URL 下到工作区 downloads/ 下的临时位置。

    `cand`（2026-11-17 AL2·#5）：候选绑定。给了它，这一趟下载就绑在那条候选上 ——
    拿不到可读全文时写一条 `extract_failed` 回执（档位与理由见
    :func:`_record_download_attempt`），于是"下载就失败、连文件都没有"或"下到的是
    10MB 落地页 HTML"的候选也能按仅题录入库（业主口径：`metadata_only` 是"试过一次、
    拿不到可读文本"，下载尝试也算一次尝试）。不给 `cand` ⇒ 除下面那条软警示外行为不变。

    ## 地址从哪来（C1FIX-DL ②，2026-11-23）

    给了 `cand` ⇒ 地址的唯一合法来源是候选行记录的那个（`:func:`_resolve_candidate_download_url``：
    `pdf_url` → `landing_url` → `url`）；`url` 给了一个记录里没有的地址 ⇒ 受控拒
    `url_not_from_candidate`（不发出任何请求、也不写回执：猜出来的地址不算"试过"）。
    `url` 空着也合法（这时就用记录里的那一个）—— 但那条路要等工具面把 `url` 从
    `required` 里放开（p326 patch，见 `temp/c1fixdl/patch-p326-search-download.diff`）。

    没给 `cand` ⇒ 扫一遍候选表，地址不在任何记录里就打一条 `url_source=self_constructed`
    的软警示（真机 4 次自拼文件名全 404 的那个形状），但不拒：
    "下一段外部 URL"本身是合法用法（真机那两次 `api.openalex.org` 抓 JSON 就是它）。

    来源读数落在哪：成功的 `data` 里不新开字段（`returns=` 是 p325 冻住的那一面，
    新键会让"实跑返回了、声明里没提"的判据变红）—— 除干净成功外，来源写在已声明的
    `warnings` 里，前缀是 `url_source=…`；失败时另在 `meta` 的 `url_source` 上给一份
    （失败 meta 本来就不进 `returns=`，与 `fetch_kind` / `cand` 同档）。

    ## 候选行上的地址是从哪来的（C1FIX-URISRC ①，2026-11-23）

    给了 `cand`、且用的是候选行记录的地址 ⇒ 再读一层来源台账（`:func:`_origin_index``）：
    `provider`（`search.literature` 真报过这个地址）⇒ 不加任何警示；
    `self_constructed`（模型自己在 `lit.stage_add` 里写的）/ `webpage`（模型自报从网页里
    读到的）/ `unknown`（这一行没有来源记录）⇒ 在 `warnings` 里点名，前缀 `url_origin=`，
    **照下**（前两档都有正当用法）；`declared_provider_unverified` ⇒ 受控拒。
    不给 `cand` 的那条路不查这一层：地址是本次调用给的，与候选行无关（C1FIX-DL 的
    `url_source` 已经覆盖它），所以那时 `url_origin` 留空串 = "这条路径不查来源"。
    """
    slot = _download_slot(cand)
    row: dict | None = None
    url_source = ""
    url_origin = ""
    url_warnings: list[str] = []
    if slot:
        row, bad = _download_candidate(ctx, slot)
        if bad is not None:
            return bad
        url, url_source, bad = _resolve_candidate_download_url(row, url)
        if bad is not None:
            return bad
        if url_source == "unrecorded":
            # 候选没有记录地址 ⇒ 地址是外部给的，核对不了（不是"与记录矛盾"）。
            url_warnings.append(_unrecorded_url_warning(slot, url))
        else:
            # 地址取自候选行 ⇒ 查这个地址本身是从哪来的（洗白通道的落点）。
            url_origin, _detail = _origin_of(_origin_index(ctx), url)
            if url_origin == URL_ORIGIN_UNVERIFIED:
                return fail(
                    f"候选 {slot} 的地址 {url} 自报「provider 给的」，但这次没有任何 provider "
                    "返回过它 ⇒ 不能拿候选行当出处（候选行不是地址的来源）。请把 "
                    "`lit.stage_add` 的 `url_origin` 改成 `self_constructed` / `webpage`"
                    "（照实说 —— 照实就照下），或先 `search.literature` 拿到 provider 的 "
                    "pdf_url 再暂存。",
                    kind="url_origin_unverified", cand=slot, url=url,
                    url_origin=url_origin, candidate_urls=_candidate_urls(row),
                )
            warning = _origin_warning(url_origin, url, slot)
            if warning:
                url_warnings.append(warning)
    else:
        url_source = _unbound_url_source(ctx, url)
        if url_source == "self_constructed":
            url_warnings.append(_self_constructed_url_warning(url))
    dest = ctx.downloads_dir
    downloader, effective = _downloader_for(ctx, int(max_bytes))
    try:
        res, elapsed = _timed(downloader.download, url, dest, hint or "paper")
    except Exception as exc:  # noqa: BLE001 - 下载器理论上不抛，但注入的实现可能抛
        receipt = (_record_download_attempt(ctx, slot, row, url=url, fetch_kind="download_error")
                   if slot and row is not None else None)
        return fail(f"下载异常：{type(exc).__name__}: {exc}", kind="download_error", url=url,
                    cand=slot, url_source=url_source, url_origin=url_origin,
                    read_receipt=receipt, warnings=list(url_warnings))

    if not res.ok:
        # 「2026-10-16（把 A 做成会应变的智能体）」：这里要把「下载层那一档」
        # 原样带出去（`fetch_kind`）。改前只给一个笼统的 `download_failed`，
        # 细分类（`tls_cert` / `tls_timeout` / `http_403` / `network_error` …）只剩在
        # 自由文本里 ⇒ 「A 读不到"为什么没下到"，也就没法决定"换源还是重试"」。
        # 现场读数（我亲自下的那一轮）：`tls_cert` 类同一个 URL 每次要 122 秒才判死
        # （本机证书/吊销检查），而 `http_403` 是明确不给脚本 ⇒ 两者的正确处置相反
        # （前者换源/改客户端开关，后者直接换源），不看类别就只能在原地耗时间。
        receipt = (_record_download_attempt(ctx, slot, row, url=url, fetch_kind=str(res.kind or ""))
                   if slot and row is not None else None)
        return fail(
            f"下载失败：{res.error}"
            + ("；这一条候选已记下一条'试过、拿不到可读文本'的回执（档位 extract_failed）"
               "⇒ 可以按仅题录（metadata_only）判收" if receipt else ""),
            kind="download_failed",
            fetch_kind=res.kind,
            url=url,
            url_source=url_source,
            url_origin=url_origin,
            http_status=res.http_status,
            bytes=res.bytes,
            elapsed_s=elapsed,
            cand=slot,
            read_receipt=receipt,
            warnings=list(url_warnings),
        )

    path = Path(res.path) if res.path else None
    # 软警告（`ok=True`）里的 `content_type_mismatch` 也是「一次尝试」：拿到的是一张
    # 落地页 HTML，不是可读全文 —— 候选行上要留一条 `extract_failed` 回执，否则
    # A 只能判拒（真机 `projects/lp-ball-4` 的 Ball 1986 就是这个形状：10,149,864 字节
    # 落地页，`ok=True`、`content_warning=content_type_mismatch`，而候选行上没有任何
    # 「试过」的证据 ⇒ 105 条一条都不敢按仅题录判）。与 `res.ok=False` 那一支共用
    # 同一个写点（`_record_download_attempt`），档位与理由见它的 docstring。
    receipt = None
    if slot and row is not None and str(res.kind or "") == "content_type_mismatch":
        receipt = _record_download_attempt(ctx, slot, row, url=url,
                                           fetch_kind=str(res.kind or ""))
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
        "cand": slot,
        "read_receipt": receipt,
        "warnings": list(url_warnings),
    }
    if res.error:
        data["warnings"].append(
            f"内容类型可疑：{res.error}。文件已完整落盘（可作证据），"
            "但**不要**直接当作论文交给 B 抽取；登记时应在 summary/download 里保留这个警告。"
        )
    if receipt:
        data["warnings"].append(
            "这一条候选已记下一条「试过、拿不到可读文本」的回执（档位 extract_failed）"
            "⇒ 可以按仅题录（metadata_only）判收；落地页 HTML 不要当全文抽取。"
        )
    if effective != int(max_bytes):
        data["warnings"].append(
            f"max_bytes 未生效：请求 {int(max_bytes)}，实际生效 {effective}"
            "（调用方注入的 downloader 自带上限，工具不擅自改别人的对象）。"
        )
    return ok(data)


# --------------------------------------------------------------------------- 批量重取

#: `search.retry_pending` 一次最多碰几行（默认 10）。这一件真出网，而且每一行都可能
#: 慢（本机实测 `tls_cert` 那类要 122 秒才判死），所以缺省取小、调用方自己抬。
RETRY_PENDING_DEFAULT_LIMIT: int = 10


def _row_location_url(row: Mapping[str, Any]) -> str:
    """这一行「按哪个地址再去取一次」：行上的 pdf_url / landing_url，或下载台账里的 url。

    顺序是有理由的：前两个是我们挑过的定位（provider 给的直链优先），
    `download.url` 是"上一次试过的那个地址"（真机上它常是 DOI 落地页，
    note 逐字写着「要全文请按它重取」）。三者都没有 ⇒ 这一行没有可重取的地址。
    """
    for key in _LOCATION_FIELDS:
        url = str(row.get(key) or "").strip()
        if url:
            return url
    dl = row.get("download")
    if isinstance(dl, Mapping):
        return str(dl.get("url") or "").strip()
    return ""


def _location_scope(row: Mapping[str, Any], url: str) -> str:
    """这次重取打的「源」—— 冷却表的键（与 `providers` 的冷却表是同一张）。

    取值顺序：
    1) 行上记着来源（`download.url_source` 的 `name:…` 前缀）⇒ 用它，这就是
       "按 provider 冷却退避"那一档；
    2) 否则按主机归一到末两段（`onlinelibrary.wiley.com` → `wiley.com`）：
       限流是对方服务器给的，同一出版商的不同子域共享配额。

    为什么下载也要冷却：真机 `search.download` 10 次里 404/429/400 各两次。
    429 之后继续打同一个站，只会把剩下几行一起拖成失败 —— 而它们本来是能取到的。
    """
    dl = row.get("download")
    if isinstance(dl, Mapping):
        src = str(dl.get("url_source") or "").strip()
        if src:
            name = src.split(":", 1)[0].strip().lower()
            if name:
                return name
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    parts = [p for p in host.split(".") if p]
    if not parts:
        return ""
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _save_retried_row(ctx: _Ctx, row: Mapping[str, Any], *,
                      path: str | None, download: dict[str, Any]) -> None:
    """把一次重取的结果写回 literature 行（`path` + `download` 两格）。

    整行写回（`tx.upsert` 是整行替换）：只 patch 两格也要写整行，否则同一事务里
    其它字段会被丢。行对象来自 `_literature_rows` 的快照，先 `dict(...)` 复制 ——
    就地改会把 store 的进程内缓存也改掉（读快照的人会看到一份没落盘的新数据）。
    """
    payload = dict(row)
    payload["path"] = path
    payload["download"] = dict(download)
    with ctx.store.tx("literature", actor=ctx.actor, note="search.retry_pending") as tx:
        tx.upsert("literature", payload)


def _h_retry_pending(ctx: _Ctx, limit: int = RETRY_PENDING_DEFAULT_LIMIT, lit_id: str = "") -> Any:
    """``search.retry_pending``：把「有元数据、没全文」的行逐条再取一次（每行最多一次）。

    四种结局（每一种都是一种处置，不许互相折叠）：

    ``got``          字节进了 ``library/`` 且 ``literature.path`` 已写回 ⇒ 现在可离线引用
    ``failed``       请求发出去了，没拿到可用字节（``kind`` 是受控档：http_404 / tls_cert …）
    ``no_location``  行上没有可重取的地址 ⇒ 我们没去取（不是「这篇不存在」）
    ``cooled_down``  这个源正在冷却 ⇒ 跳过，不是失败（这一行下次还能再取）

    为什么 `failed` 必须单独一档：把 404 折进 `no_location`，下游会读成"我们连地址都
    没有"（进而"这大概不存在"），而事实是我们知道地址、对方不给 —— 两者的下一步
    动作相反（前者去换源找地址，后者等冷却/换路由）。

    写盘纪律：每次尝试都回写 ``download``（``last_kind`` / ``retry_attempts`` /
    ``retried_at``），成功才写 ``path``。一次失败绝不把行从表里抹掉，也绝不给一个
    指向不存在文件的 ``path``。
    """
    if ctx.store is None:
        return fail(
            "未配置 store：读不到文献表，也就说不出哪些行还缺全文"
            "（「没有要重取的行」与「读不到表」是两件事，不许折叠成一个空清单）。",
            kind="no_store",
            checked=False,
            counted=False,
        )
    rows, read_error = _literature_rows(ctx)
    if read_error is not None:
        return fail(
            f"{read_error} ⇒ 重取**没做成**（不是「没有要重取的行」）。",
            kind="table_unreadable",
            checked=False,
            counted=False,
            read_error=read_error,
        )

    # 重取前的覆盖率与「还有哪些行缺全文」共用一趟 `_shelf_row`：两处判的是同一件事
    # （文件在不在盘上），再扫一遍整表只是把同一份文件检查做两次。
    judged = [_shelf_row(ctx, row) for row in rows]
    coverage_before = _shelf_coverage(ctx, rows, judged=judged)
    pending: list[Mapping[str, Any]] = []
    for i, row in enumerate(rows):
        if lit_id and str(row.get("lit_id") or "") != lit_id:
            continue
        # 「已经有了可离线引用的全文」不在这一件的职责里（那一行不需要再取）。
        if judged[i] is None:
            pending.append(row)
    pending.sort(key=lambda r: str(r.get("lit_id") or ""))
    scanned = len(pending)
    todo = pending[: max(0, int(limit))]

    downloader, _effective = _downloader_for(ctx, DEFAULT_MAX_DOWNLOAD_BYTES)
    counts: dict[str, int] = {"got": 0, "failed": 0, "no_location": 0, "cooled_down": 0}
    results: list[dict[str, Any]] = []
    attempted = 0
    # S-E 协作式截止的检查点（`tool_timeout.TIMEOUT_TABLE` 里 `search.retry_pending`
    # 声明的是 `checkpoint="handler"`）：放在每一行开始之前。到点就抛，已落盘的
    # 那些行不受影响（各自的事务已提交）；与 `search.literature` 在"每个源那一次
    # 调用之前"设检查点是同一条口径。
    from ..tool_timeout import raise_if_timed_out

    for row in todo:
        raise_if_timed_out()
        lid = str(row.get("lit_id") or "")
        url = _row_location_url(row)
        scope = _location_scope(row, url) if url else ""
        item: dict[str, Any] = {
            "lit_id": lid, "outcome": "", "source": scope or None, "url": url or None,
            "kind": None, "http_status": None, "path": None, "bytes": None, "sha256": None,
            "error": None, "cooldown_left_sec": None, "note": "",
        }

        if not url:
            item["outcome"] = "no_location"
            item["note"] = (
                "行上没有可重取的地址 ⇒ 我们没去取。这不是「这篇不存在」："
                "要全文得先换一个检索源，把这一篇的定位补齐。"
            )
            counts["no_location"] += 1
            results.append(item)
            continue

        left = P._provider_cooling(scope) if scope else 0.0
        if left > 0:
            item["outcome"] = "cooled_down"
            item["cooldown_left_sec"] = round(left, 1)
            item["note"] = (
                "这个源正在冷却（上一次 429 之后）⇒ 跳过，不是失败："
                "这一行下次还能再取，不必换地址。"
            )
            counts["cooled_down"] += 1
            results.append(item)
            continue

        # ---- 真发一次请求（每行只试一次：重试策略是"跳过冷却中的源"，不是原地重打）
        attempted += 1
        try:
            res, elapsed = _timed(downloader.download, url, ctx.downloads_dir, lid or "retry")
        except Exception as exc:  # noqa: BLE001 - 注入的下载器可能抛
            res, elapsed = None, 0.0
            item.update(
                outcome="failed", kind="download_error",
                error=f"{type(exc).__name__}: {exc}",
                note="下载器抛了异常 ⇒ 这一行没取到（不是「这篇不存在」）。",
            )
        if res is not None:
            item["kind"] = res.kind
            item["http_status"] = res.http_status
            item["bytes"] = res.bytes
            item["sha256"] = res.sha256
            item["error"] = res.error
            landing_page = bool(res.ok and res.kind == "content_type_mismatch")
            if res.ok and not landing_page:
                rel_path, size, sha = _adopt_file(ctx, str(res.path or ""), [], lit_id=lid)
                if rel_path:
                    item.update(outcome="got", path=rel_path, bytes=size, sha256=sha,
                                note="字节已进 library/、path 已写回 ⇒ 现在可离线引用。")
                    dl_old = dict(row.get("download") or {})
                    # M3（2026-11-05）：`dl_old` 会把旧的 `fulltext` 标签原样带下去 ——
                    # 这一处只知道"现在有字节了"，有没有可抽文本要等 B 抽取时现算。
                    # 所以按三档口径算出来的是 `None`（有字节、这一处没抽过）⇒ 交给
                    # `with_fulltext` 把旧标签清掉，而不是让 `status=ok` 的行继续写着
                    # "没有全文"（真机 6 条自相矛盾的来源之一）。
                    _save_retried_row(ctx, row, path=rel_path, download=LR.with_fulltext({
                        **dl_old, "status": "ok", "http_status": res.http_status,
                        "bytes": size, "sha256": sha, "error": None, "url": url,
                        "retry_attempts": int(dl_old.get("retry_attempts") or 0) + 1,
                        "retried_at": S.now_iso(),
                    }, LR.fulltext_tier(bytes_on_disk=size, pages=None)))
                else:
                    item.update(
                        outcome="failed", kind="adopt_failed",
                        note="字节下来了、但搬不进 library/ ⇒ 这一行仍不可离线引用（不是「这篇不存在」）。",
                    )
            else:
                item["outcome"] = "failed"
                item["note"] = (
                    "请求发出去了、没拿到可当全文的字节 ⇒ 这一行是没取到，不是「这篇不存在」。"
                    "kind 是受控档：429 等冷却、404 换 landing、400 换 PDF 路由；"
                    "content_type_mismatch 是拿到落地页，换 PDF 直链。"
                )
        if item["outcome"] != "got":
            counts["failed"] += 1
            dl_old = dict(row.get("download") or {})
            # 失败那一支同样按盘上事实重算：这一行如果本来就有字节，`fulltext` 不该
            # 因为"这次重取失败"被写成没有全文（两件事：有没有字节 / 这次取没取到）。
            kept = row.get("path")
            _save_retried_row(ctx, row, path=kept, download=LR.with_fulltext({
                **dl_old, "status": "failed", "error": str(item.get("error") or ""),
                "kind": item.get("kind"), "last_kind": item.get("kind"),
                "http_status": item.get("http_status"), "url": url,
                "retry_attempts": int(dl_old.get("retry_attempts") or 0) + 1,
                "retried_at": S.now_iso(),
            }, LR.fulltext_tier(
                bytes_on_disk=LR.bytes_on_disk(_lit_file(ctx, str(kept or ""))),
                pages=None)))
            if item.get("kind") == "http_429" and scope:
                # 429 ⇒ 给这个源记一段冷却，后面的行不再打它（跳过，不是失败）。
                P.start_provider_cooldown(scope)
        else:
            counts["got"] += 1
        results.append(item)

    # 重取之后重新数一遍覆盖率：这一件买到的是"缺口缩小了多少"，不是一个 got 计数。
    rows_after, after_error = _literature_rows(ctx)
    coverage_after = (_shelf_coverage(ctx, rows_after) if after_error is None
                      else coverage_before)
    return ok(
        {
            "checked": True,
            "scanned": scanned,
            "attempted": attempted,
            "counts": counts,
            "rows": results,
            "stopped": "limit" if len(todo) < scanned else "done",
            "coverage_before": coverage_before,
            "coverage_after": coverage_after,
            "note": (
                "四种结局各是一种处置：got=现在可离线引用；failed=试过没拿到（kind 记原因，"
                "**不等于这篇不存在**）；no_location=行上没地址 ⇒ 我们**没去取**（不是「不存在」）；"
                "cooled_down=源在冷却 ⇒ **跳过**，下次还能取。"
                "一次调用每行只试一次：重试策略是跳过冷却中的源，不是原地重打。"
            ),
        }
    )


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


def _adopt_file(ctx: _Ctx, raw_path: str | None, warnings: list[str], *,
                lit_id: str,
                relocation: dict | None = None) -> tuple[str | None, int, str | None]:
    """把本地文件收编进 ``library/``，返回 ``(相对路径, 字节数, sha256)``。

    三种情形分别处理：
    1. 已在 ``library/`` 内 ⇒ **目录名必须是文献号**（见下面 2026-11-26 的裁定）；
    2. 在 library 之外（如 ``reference/`` / ``downloads/``）⇒ 收编进唯一落点；
    3. 文件不存在 ⇒ ``path`` 置 ``None`` 并记 warning，不编造路径。

    ## 情形 1 的裁定（2026-11-26 MSRELOC：不再把槽位目录当文献目录）

    改前这一支是"已在库里 ⇒ 原样返回那个相对名"。真机 `sunflower-digest-3` 上它把
    `library/000006/…pdf`（`000006` 是**候选槽位号**）原样写成了
    `literature.path`，四行四条，于是书架上是四个槽位号目录、行上 `path` 首段全是
    槽位号 —— 而 `text_rel()` 又把抽读件落进同一条槽位目录，`wellformed` 与
    `fs.read` 从此都在槽位目录里找字节。成因在会话里读得到：候选期模型为了让
    `text.extract` 能按 `<6位号>/<名>` 抽读，先 `fs.move` 进了 `library/<槽位号>/`
    （2026-11-26T06:13:27 / 08:14:59 / 08:16:05 / 08:49:46 四笔）。

    所以这一支改成**交给搬迁**：`locallib.relocate_into_entry`（与结算点
    `litstage.relocate_settled_originals` 同一个实现）。它按内容 sha 优先给出
    `library/<lit_id>/<名>`，同名不同内容追加内容短哈希、绝不覆盖；搬过之后把
    `reading` 里的 `from`/`to`/`sha256` 交给调用方落回执/事件（`relocation` 出参）。

    搬不动时**不编造**成功：保留原相对名并记一条 warning（行上的 path 仍是坏的，
    但它是盘上真实的那一份），结算点会再搬一次；两次都搬不动由收工门兜底。

    ## 收编是"复制"还是"搬"（2026-11-24 SEED-LANDING-FIX ① 裁定）

    判据只有一处：`locallib.keeps_original`。**投放处（`reference/` / `source/`）里的
    字节、以及被用户声明覆盖的字节，只复制、原件留在原处**；其余（框架自己的下载暂存
    `downloads/` 等）仍按"收编即搬"处理。

    为什么不能搬走投放处的那一份（sylow-3 现场）：候选链的 `lit.admit_all` 会把抽读
    回执的源文件（=`reference/<sha12>-<名>`）交给登记路收编，`shutil.move` 一搬，
    `reference/` 就空了；而用户的声明 `RELIABLE-REFERENCES.json` 里写的是
    `paths: ["reference/…"]`（M 逐字抄的用户原话，A 不许改）⇒
    `scripts/check_declaration.py` 的 `declared_empty` 报"声明点了但盘上没有"、
    `reference_count` 报"空投放处"。复制让"声明的 paths 还在盘上"这件事由实现保证，
    而不是靠把 gate 改宽成"看不到也算过"。兄弟路径 `ingest_directory` 本来就是
    `shutil.copy2`，两条收编路由此同一个语义。

    落点（2026-11-25 业主裁定：`<6位号>/<名>` 回归正确形态，推翻 B2a 的扁平落点）：
    第 2 种的相对名不由本函数决定，走 `locallib.library_landing`（与
    `locallib.ingest_directory` / `agent_a.core._attach_staged` 共用的同一个函数）⇒
    新写一律 `<文献号>/<清洗过的原名>`。`lit_id` 是**已经分配好的**号（调用方在同一事务里
    先 `tx.alloc_id("lit")`），本函数不再自己取号、也不落临时名。
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
    except ValueError:
        rel = None  # 不在 library 内 → 需要收编
    if rel is not None:
        # 已在 library/ 内：**不再原样返回**（2026-11-26 MSRELOC 收口）。
        # 目录名不是文献号 ⇒ 交给搬迁（唯一实现 `locallib.relocate_into_entry`，
        # 与结算点共用）；目录名本来就是文献号 ⇒ 它原样返回（一个字节都不动）。
        from ..locallib import relocate_into_entry
        try:
            moved, where = relocate_into_entry(
                lib, lit_id, literature_path=rel, reading=relocation)
        except (OSError, ValueError) as exc:
            warnings.append(
                f"`{rel}` 已在 library/ 内但目录名不是文献号，搬迁失败"
                f"（{type(exc).__name__}: {exc}）⇒ path 暂按盘上原样记，结算点会再搬一次")
            return rel, p.stat().st_size, _sha256_of(p)
        if moved and where is not None and where.is_file():
            return moved, where.stat().st_size, _sha256_of(where)
        if moved != rel:
            warnings.append(
                f"`{rel}` 搬迁到 `{moved}` 之后盘上读不到那一份 ⇒ path 暂按原样记")
        elif (relocation or {}).get("status") not in (None, ""):
            # 没搬成（file_missing / bad_path / conflict / write_failed）：
            # 如实说"这一行落在哪、为什么搬不动"，别让模型以为 path 已经规范了。
            warnings.append(
                f"`{rel}` 在 library/ 内，但目录名不是文献号，且这一次没搬成"
                f"（{relocation.get('status')}: {relocation.get('why') or '无理由'}）")
        return rel, p.stat().st_size, _sha256_of(p)

    # 落点只有一处实现（`locallib.library_landing`，三个写者共用）：
    # `<文献号>/<清洗名>`（2026-11-25 业主裁定）；同名不同内容会追加内容短哈希，绝不覆盖。
    from ..locallib import keeps_original, library_landing
    sha = _sha256_of(p)
    try:
        landing, target = library_landing(lib, p, sha, lit_id=lit_id)
        target.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as exc:
        warnings.append(f"无法确定 library/ 落点（{type(exc).__name__}: {exc}），path 置空")
        return None, 0, None
    if target.exists() and _sha256_of(target) == sha:
        # 这份字节已在库里（内容相同）⇒ 不搬第二份、也不覆盖；原文件留在原处
        # （不在 library 里的那份不是我们的，删不删由它的主人定）。
        return landing, target.stat().st_size, sha
    # 复制还是搬走：唯一判据是 `locallib.keeps_original`（投放处/被声明的字节只复制）。
    keep = keeps_original(ctx.store.root, p)
    try:
        if keep:
            shutil.copy2(str(p), str(target))
        else:
            shutil.move(str(p), str(target))
    except Exception as exc:  # noqa: BLE001 - 跨盘/权限/占用都可能失败
        if keep:
            # 复制失败可能留下半份目标：当场清掉，别让它占住落点名（下一次会被判成
            # "同名不同内容"而被迫加长前缀）。
            try:
                target.unlink()
            except OSError:  # 清不掉也不能盖住真正的失败原因（下面那条 warning 才是）
                pass
        warnings.append(f"收编文件失败（{type(exc).__name__}: {exc}），path 置空；原文件仍在 {p}")
        return None, 0, None
    return landing, target.stat().st_size, sha


def _download_receipt(rel_path: str | None, size: int, sha: str | None) -> dict[str, Any]:
    """登记行上的 `download` 那几格（`_h_register` 里搬出来的，判据一个字没改）。

    有字节 ⇒ `ok`（内容确实在本地、哈希是我们刚算的；http 元数据未知就留 `None`，
    不编造状态码）；没有字节 ⇒ `skipped` + `no_local_path`（不是「下载失败」，是
    「这一笔没要文件」—— 两档处置不同）。
    """
    if rel_path:
        return {"status": "ok", "http_status": None, "bytes": size, "sha256": sha,
                "error": None}
    return {"status": "skipped", "http_status": None, "bytes": 0, "sha256": None,
            "error": "no_local_path"}


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
    from ..locallib import (DECLARATION_NAME, ingest_directory,
                            undeclared_workspace_books)

    base = Path(books_dir)
    target = base if base.is_absolute() else (ctx.workspace / base)
    if not target.is_dir():
        return fail(f"目录不在盘上：{target}", kind="io_error", recorded=False,
                    books_dir=str(target))
    # 用户声明闸（2026-11-21 业主裁定，fail-closed）：只有用户提示词里点名的文件/目录
    # 才可入库；没点名的一律只能当研究参考。`dry_run` 是发现档（零写入）⇒ 不拦；
    # 非 dry 档是"直接写 literature 行"的那条路 ⇒ 一份未声明就整笔拒、零写入。
    # 真身：`locallib.DECLARATION_NAME` / `locallib.is_declared`（M 落盘的那份清单）。
    if not dry_run:
        undeclared, decl_problem = undeclared_workspace_books(
            ctx.store.root, target, pattern=pattern or "*.pdf")
        if undeclared:
            names = "、".join(undeclared[:5]) + ("…" if len(undeclared) > 5 else "")
            # 工作区外的目录：声明（工作区相对 `paths`）表达不了它 ⇒ 与
            # `search.register` 对工作区外 `path` 同口径 fail-closed（DGWIDE ④）。
            try:
                Path(target).resolve().relative_to(Path(ctx.workspace).resolve())
                outside = False
            except (OSError, ValueError):
                outside = True
            if outside:
                why = ("这个目录在工作区外，用户声明（工作区相对 paths）表达不了它"
                       "（不是「目录里没有书」）")
            else:
                why = f"声明读不出来（{decl_problem}）" if decl_problem else "这些文件未被用户点名"
            return fail(
                f"这不是一次可以入库的登记：{why}（{names}）。默认 fail-closed："
                "没有声明 ⇒ 不许入库 —— 未点名的文件只能当研究参考（可读），不进 "
                f"`literature`。处置：让 M 先把用户声明记下来（把用户提示词里点名的"
                f"文件/目录逐字记进工作区根的 `{DECLARATION_NAME}`，形如 "
                "{\"paths\": [\"a.pdf\", \"b/\"], \"verbatim\": \"<用户原话>\"}）；"
                "清单为空就说明用户这一次没有点名，那这一批一份都不许收编。本次零写入。"
                "要收工作区外的书架，先把那些文件放进工作区并由用户点名；"
                "或者走候选链（`lit.stage_add` → `lit.admit`）。",
                kind="not_declared_reference", recorded=False,
                books_dir=str(target), undeclared=undeclared,
                declaration=str(ctx.store.root / DECLARATION_NAME),
                declaration_state=("outside_workspace" if outside else "read"),
                declaration_checked=False if outside else True,
                dry_run=False)
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


def _content_claim_refusal(summary: str, *, read_ok: bool,
                           port: str = "search.register") -> Any:
    """正文闸：`content_read=false` 时 `summary` 里有内容性断言 ⇒ 受控拒（否则 `None`）。

    判据不在这里另写一份：哪些话算"内容性断言"是 `litavail.content_assertion`
    （与 `litstage._content_assertion_gate` 同一函数），受控码也共用
    `litstage.CONTENT_CLAIM_WITHOUT_READ`。"读没读到正文"由调用方按
    `litavail.content_read` 现算后经 `read_ok` 交进来（两条入口：候选链现算真值、
    直写路恒 `False`）。

    `port` 只决定拒信开头那句话写哪个写口（`signal` 用的名字），不改判据：
    接这道闸的有三处 —— `search.register`（直写）、`table.create` / `table.update`
    （落到 `literature` 时）、`locallib.ingest_directory`（机器题录）。三处判的是
    同一条：`LAV.content_assertion` 命中且没有"读过正文"的机器读数。
    """
    claim = LAV.content_assertion(summary)
    if not claim or read_ok:
        return None
    return fail(
        f"{port} 不收内容性断言：`content_read=false`（这一条直写路"
        f"没有可复核的'读过正文'证据）而 summary 里写了 {claim!r} ⇒ 那一句不是"
        "读出来的。改法二选一：① summary 只写题录性说明（题名 / 作者 / 这是一篇"
        "什么文献，以及'为什么与本次检索相关'）；② 要写正文里的东西，走候选链："
        "`lit.add` → `text.extract` → `fs.read` → `lit.admit`"
        "（那里 `content_read` 由机器现算，同一道闸会替你算）。本行未写入。",
        kind=CONTENT_CLAIM_WITHOUT_READ,
        field="summary", claim=claim, content_read=False,
    )


def _workspace_relative_target(ctx: _Ctx, raw_path: str) -> str | None:
    """这一笔要收编的那份文件，在工作区里的相对 POSIX 路径；解析不到 ⇒ `None`。

    解析的两基准与 `_adopt_file` 逐字同源：相对路径先按 `library/` 解释，不存在
    再按 workspace 解释 —— 声明闸与写口必须对"这一笔指的是哪一份文件"给出同一个
    答案，否则闸核的是 A、搬进库的是 B（那种错不会有任何地方报错）。

    `None` 有两种来路（调用方都要按 fail-closed 拒）：路径解析失败，或解析到了
    工作区之外 —— 声明里的 `paths` 是工作区相对路径，表达不了工作区外的文件。
    """
    if ctx.store is None:
        return None
    try:
        p = Path(raw_path)
        if not p.is_absolute():
            candidate = ctx.store.library / p
            p = candidate if candidate.exists() else (ctx.workspace / p)
        rel = p.resolve().relative_to(Path(ctx.workspace).resolve())
    except (OSError, ValueError):
        return None
    return rel.as_posix()


def _no_target_refusal(ctx: _Ctx, *, port: str) -> Any:
    """`path` 为空的题录直登：没有文件可核 ⇒ 同样按声明判据 fail-closed 拒。

    ## 为什么这一档不再是"不适用"

    DECLAREGATE 把 `path=None` 划在声明判据的适用面之外（"没有文件可核"），而业主
    2026-11-21 的裁定把入库判据钉在用户点名上、不是"有没有文件可核"：没有文件
    ⇒ 用户声明表达不了这一篇（声明里只有工作区相对的 `paths`）⇒ 答不出"用户点名了吗"
    ⇒ fail-closed。真机 `lp-ball-12/14` 的 15 次直登里有 14 次正是这一档
    （`temp/dgwide/recompute-15.txt`）。

    ## 三态照旧

    先只问声明本身的状态（`declaration_verdict(root)` 不传路径）：
    声明在盘上但读不出来 ⇒ `declaration_unreadable` + `declaration_checked=False`
    （这一笔没查成，不折成"你没声明"）；其余 ⇒ `not_declared_reference`。
    放行只有一条路：带 `path=` 指向一份用户点名的工作区文件（或走候选链，
    `lit.stage_add` → `lit.admit`）。
    """
    from ..locallib import (DECLARATION_NAME, DECLARATION_UNREADABLE,
                            declaration_verdict)

    how_to_fix = (
        "要让这一篇入库，二选一：① 把用户点名的文件放进工作区，并在工作区根的 "
        f"`{DECLARATION_NAME}` 里点名它，再带 `path=` 重试；② 走候选链 "
        "（`lit.stage_add` → `lit.admit`；那条路的准入依据是候选行 + 读过正文）。"
        "只登记题录、没有文件的那一篇只能当研究参考（可读），不入库。"
    )
    if ctx.store is None:
        return fail(
            f"{port} 不收没有文件的题录直登：没有配置 store ⇒ 用户声明也读不到 "
            "⇒ 按 fail-closed 拒（没查成不是「用户点名了」）。本次零写入。",
            kind="not_declared_reference", recorded=False, path=None,
            declaration="", declaration_state="no_store",
            declaration_checked=False, why="no_file_to_check",
            how_to_fix=how_to_fix,
        )
    verdict = declaration_verdict(ctx.store.root)
    declaration = str(verdict["declaration"])
    state = str(verdict["state"])
    if state == DECLARATION_UNREADABLE:
        return fail(
            f"{port} 这一笔没查成：工作区根的 `{DECLARATION_NAME}` 在盘上但读不出来"
            f"（{verdict['problem']}）⇒ 声明状态是 unchecked（既不是「用户点名了」"
            "也不是「用户没点名」）。这一笔又没有文件可核（题录直登）⇒ 在声明修好"
            "之前不入库；修好声明再重试同一笔。本次零写入（还没进事务、文件没动）。",
            kind="declaration_unreadable", recorded=False, path=None,
            declaration=declaration, declaration_state=state,
            declaration_checked=False, why="no_file_to_check",
            problem=str(verdict["problem"] or ""),
            how_to_fix=(f"把工作区根的 `{DECLARATION_NAME}` 改回合法形状"
                        "（{\"paths\": [...], \"verbatim\": \"<用户原话>\"}），"
                        "再重试同一笔。"),
        )
    return fail(
        f"{port} 不收没有文件的题录直登：这一笔没有 `path` ⇒ 没有要收编的工作区"
        "文件，用户声明表达不了它（声明里的 `paths` 是工作区相对路径）⇒ 默认 "
        "fail-closed：只有用户点名的文件才可入库，这一篇只能当研究参考（可读），"
        "不进 `literature`。本次零写入（这一笔还没进事务、没有文件被搬动）。"
        f"处置：{how_to_fix}",
        kind="not_declared_reference", recorded=False, path=None,
        declaration=declaration, declaration_state=state,
        declaration_checked=bool(verdict["checked"]),
        undeclared=[], why="no_file_to_check", how_to_fix=how_to_fix,
    )


def _declaration_refusal(ctx: _Ctx, raw_path: str | None, *,
                         port: str = "search.register") -> Any:
    """声明闸（`search.register` / `table.create` 的写入口）：用户点名了这一笔吗。

    ## 判据只有一份

    真身是 `locallib.declaration_verdict`（`read_declaration` + `is_declared`）；
    本函数只做三件事：把 `raw_path` 解成工作区相对路径、把结论翻成受控拒信、
    在拒绝时保证"还没进事务、文件没动、零落盘"。`port` 只决定拒信开头写哪个写口，
    不改判据（`table.create` 复用它时传 `port="table.create"`）。

    ## 三态（与 `locallib` 同一套词表）

    * 声明读得到、这份文件被点名 ⇒ 放行（返回 `None`）；
    * 声明读得到、这份没被点名（含 `paths=[]`）⇒ 受控拒 `not_declared_reference`；
    * 声明文件不在盘上 ⇒ 同一码、拒信说"用户没声明"（fail-closed）；
    * 声明文件在盘上但读不出来 / 形状不对 ⇒ `declaration_unreadable`、
      `declaration_checked=False`：这一笔没查成，不是"你没声明"（三态不许折叠）。

    ## 适用面（2026-11-21 DGWIDE ① 收紧）：`path` 为空也拒

    改前 `path` 为空（只登记题录、没有文件要收编）⇒ 本闸不适用、返回 `None`。
    业主裁定「入库的判据是用户点名，不是有没有文件可核」之后，这条边界成了第 ① 条
    绕行口：真机 15 次直登里 14 次是 `path=None`（DECLAREGATE §④）。现在：
    没有文件 ⇒ 用户声明表达不了这一篇（声明的 `paths` 是工作区相对路径）⇒
    `not_declared_reference` 受控拒，落"研究参考"档（可读、不入库）。
    声明在盘上却读不出来 ⇒ 仍落第三态 `declaration_unreadable`（unchecked），
    不折成"你没声明"。工作区外的 `path` 同样拒（声明表达不了它）。

    ## 为什么拒绝必须发生在 `tx` 之前

    `search.register` 的写有两处副作用：`tx.alloc_id("lit")` 与 `_adopt_file`
    （把文件收编进 `library/` 的唯一落点 `<内容 hash 前缀-名>`；投放处/被声明的字节
    只复制，其余搬走 —— 见 `locallib.keeps_original`）。
    闸放在 `tx` 之前 ⇒ 拒信说的
    "本行未写入 / 文件没动"就是盘上事实，而不是一句承诺。
    """
    text = str(raw_path or "").strip()
    if not text:
        return _no_target_refusal(ctx, port=port)
    from ..locallib import (DECLARATION_ABSENT, DECLARATION_NAME,
                            DECLARATION_UNREADABLE, declaration_verdict)

    rel = _workspace_relative_target(ctx, text)
    if rel is None:
        return fail(
            f"{port} 不收工作区外的文件：这一笔的 path 解析不到工作区里"
            f"（{text!r}）⇒ 用户声明表达不了它（声明里的 `paths` 是工作区相对路径），"
            "默认 fail-closed。处置：把用户点名的文件放在工作区里（`source/` / "
            "`library/` 一类投放处）再登记，或走候选链（`lit.stage_add` → "
            "`lit.admit`）。本次零写入（这一笔还没进事务、文件没动）。",
            kind="not_declared_reference", recorded=False,
            path=text, declaration_state="outside_workspace",
            declaration_checked=False,
            how_to_fix=("把要登记的那份文件放进工作区，并在工作区根的 "
                        f"`{DECLARATION_NAME}` 里由用户点名它之后重试。"),
        )

    verdict = declaration_verdict(ctx.store.root, [rel]) if ctx.store is not None else None
    if verdict is None:  # 调用方已挡掉 store=None；这一支只为静态完备
        return None
    declaration = str(verdict["declaration"])
    state = str(verdict["state"])
    how_to_fix = (
        "让 M 先把用户声明记下来：把用户提示词里点名的文件/目录逐字记进工作区根的 "
        f"`{DECLARATION_NAME}`（形如 {{\"paths\": [\"a.pdf\", \"b/\"], "
        "\"verbatim\": \"<用户原话>\"}），再重试同一笔；用户没点名 ⇒ 这一份只能当"
        "研究参考（可读），不入库。"
    )
    if state == DECLARATION_UNREADABLE:
        return fail(
            f"{port} 这一笔没查成：工作区根的 `{DECLARATION_NAME}` 在盘上但"
            f"读不出来（{verdict['problem']}）⇒ 声明状态是 unchecked（既不是"
            "「用户点名了」也不是「用户没点名」）。在它修好之前这一笔不入库："
            "修好声明再重试同一笔。本次零写入（这一笔还没进事务、文件没动）。",
            kind="declaration_unreadable", recorded=False,
            path=rel, declaration=declaration,
            declaration_state=state, declaration_checked=False,
            problem=str(verdict["problem"] or ""),
            how_to_fix=(f"把工作区根的 `{DECLARATION_NAME}` 改回合法形状"
                        "（{\"paths\": [...], \"verbatim\": \"<用户原话>\"}），"
                        "再重试同一笔。"),
        )
    undeclared = list(verdict["undeclared"])
    if state == DECLARATION_ABSENT:
        return fail(
            f"{port} 不收这份文件：工作区根没有用户声明（`{DECLARATION_NAME}` "
            f"不在盘上）⇒ {rel} 没有被用户点名。默认 fail-closed：没点名的不许入库 —— "
            "它只能当研究参考（可读），不进 `literature`。本次零写入（这一笔还没进"
            f"事务、文件没动）。处置：{how_to_fix}",
            kind="not_declared_reference", recorded=False,
            path=rel, declaration=declaration,
            declaration_state=state, declaration_checked=bool(verdict["checked"]),
            undeclared=undeclared, how_to_fix=how_to_fix,
        )
    if undeclared:
        return fail(
            f"{port} 不收这份文件：用户声明里没有它（{rel}）。默认 fail-closed："
            "没点名的不许入库 —— 它只能当研究参考（可读），不进 `literature`。"
            f"本次零写入（这一笔还没进事务、文件没动）。处置：{how_to_fix}",
            kind="not_declared_reference", recorded=False,
            path=rel, declaration=declaration,
            declaration_state=state, declaration_checked=bool(verdict["checked"]),
            undeclared=undeclared, how_to_fix=how_to_fix,
        )
    return None


def _h_register(
    ctx: _Ctx,
    title: str,
    type_code: str,
    summary: str,
    path: str | None = None,
    doi: str | None = None,
    year: int | None = None,
    request_id: str | None = None,
    *,
    read_ok: bool = False,
    _from_candidate: bool = False,
) -> Any:
    """``search.register``：走 ``tx`` + ``alloc_id("lit")`` 建一条 literature 行。

    先判重再建行：命中已有行时复用它的代号，只追加 ``source_request_ids`` ——
    同一篇文献两个代号会污染全部下游溯源（``lit_id`` 是关系表、引文校验、报告引用的共同锚点）。

    ``read_ok`` 是这一条"读没读到正文"的机器读数（调用方按 ``litavail.content_read``
    现算；不传 ⇒ ``False``）。它只喂正文闸：``content_read=false`` 时 ``summary`` 里
    不许出现内容性断言（``litstage`` 的 ALITCONTENT 同一实现）。

    ``_from_candidate`` 是"这一笔来自候选链"的结构事实（`lit.admit` / `lit.admit_all`
    的 `_registrar_from_candidate` 传 `True`）：候选链的准入依据是候选行 + 读过正文，
    不是"用户点名了哪个工作区文件" ⇒ 声明闸不适用。它是下划线参数、不在工具 schema
    里，模型看不见也传不进来（工具入口是 `_search_register` 的固定签名）。

    直登（`_from_candidate=False`）在进事务之前过与 `search.ingest_local` 同一道声明判据
    （`_declaration_refusal` → `locallib.declaration_verdict`）：未声明 ⇒ `not_declared_reference`
    受控拒、零写入；声明读不出来 ⇒ `declaration_unreadable`（`declaration_checked=false`）。
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
    # ---- SYSRESIDUE ④：两个去重格由 `sysresidue.literature_dedup_cells` 一处算
    # （改前这一支自己拼 `title:<norm>|*`，`locallib` 那一支写空串 —— 同一主键两个
    # 口径，而读侧 `dedup._row_keys` 两处都收，于是漂了也不报错）。
    keys, dedup_key = _SR.literature_dedup_cells(title, year, doi)
    cell_problems = _SR.dedup_cells_problems(
        {"title": title, "year": year, "doi": doi,
         "dedup_key": dedup_key, "_keys": keys}, keys=keys)
    if cell_problems:
        _SR.note_dedup_refusal(ctx.store.root, where="search.register",
                               problems=cell_problems)
        return fail(
            "search.register 不收没有去重主键的文献："
            + "；".join(cell_problems)
            + "。本行未写入。改法：给一个能归一化的 title（或 doi）；"
            "`dedup_key` 由 `sysresidue.literature_dedup_cells` 一处算，"
            "工具层不许自己拼一个形态。",
            kind=_SR.CODE_DEDUP_KEY_MISSING, field="title",
            keys=list(keys), dedup_key=dedup_key,
        )

    # ---- 声明闸（业主裁定 2026-11-21；与 `search.ingest_local` 同一道判据）--------
    # 放在 `tx` 之前：这一笔一旦进事务就会 `alloc_id` 并 `_adopt_file`（收编进
    # `library/<hash 前缀-名>`；投放处/被声明的字节只复制，原件留原处）—— 不可撤。
    # 候选链（`_from_candidate`）不走这道闸：它的准入依据是候选行 + 读过正文，
    # 不是"用户点名了哪个文件"。
    if not _from_candidate:
        refused = _declaration_refusal(ctx, path)
        if refused is not None:
            return refused

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
                    # 2026-11-26 MSRELOC：判重命中支没有"我收编了一份字节"这件事，
                    # 所以搬迁回执必然是空的 —— 用 `{}` 说"没发生"，与新建支同键。
                    "relocation": {},
                    "warnings": warnings + [
                        "判重命中：复用既有 lit_id，未新建行（同一篇文献两个代号会污染下游溯源）。"
                    ],
                }
            )

        # ---- 正文闸（与 `litstage` 的 ALITCONTENT 同一条判据、同一个受控码）------
        # 业主 2026-11-20 裁定 ③：`content_read=false` 时 relevance / new_content 里
        # 不许出现内容性断言。`search.register` 是直写 literature 的那条路，
        # 它此前只校验 type_code / title / 判重 ⇒ 5 条 metadata_only 就是这样带着
        # "该文用…给出 log Γ 的精确值"进了库（真机 lp-ball-14）。
        clipped = T.clip(summary or "", 1200)
        refused = _content_claim_refusal(clipped, read_ok=read_ok)
        if refused is not None:
            return refused

        lit_id = tx.alloc_id("lit")
        # 搬迁回执（MSRELOC）：把 library/<槽位号>/ 的字节搬进 library/<文献号>/ 这一笔留痕。
        relocation: dict = {}
        rel_path, size, sha = _adopt_file(ctx, path, warnings, lit_id=lit_id,
                                         relocation=relocation)
        if relocation:
            tx.info("lit.relocate", **{**relocation, "lit_id": lit_id,
                                       "where": "search.register"})
        dl = _download_receipt(rel_path, size, sha)

        row = S.Literature(
            lit_id=lit_id,
            title=title.strip(),
            type=code,
            summary=clipped,
            path=rel_path,
            processed=False,  # B 负责置 true
            source_request_ids=[request_id] if request_id else [],
            dedup_key=dedup_key,
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
            # 搬迁回执（2026-11-26 MSRELOC）：`status`/`from`/`to`/`sha256`/`bytes`。
            # 目录名本来就是文献号时它是 `already_in_entry`（零写入），空 dict 表示
            # 这一趟根本没走到"已在 library 内"那一支（字节从库外收编进来）。
            "relocation": relocation,
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


def _keeps_failure_history(req: Mapping[str, Any]) -> bool:
    """这一行上已有的 `last_error` 是不是一份失败读数（是 ⇒ 成功登记不许清掉它）。

    为什么不猜文本、只看 `outcome` / `done`：`last_error` 在这一格上是两种东西 ——
    失败原文（`run_once` 的退避支 / 放弃支写）与"命中 N 条、入库 0 条（待裁）"的
    命中读数（`outcome=no_results` 那一支写）。用关键词去分辨它们，等于给
    "这句话算不算失败"再造一份口径；而上面两档各自由写者决定，`outcome`
    已经把答案写在行上了：

    * `search_failed` / `gave_up`：schema 的校验要求这两档必须带 `last_error`，
      所以那一格一定是失败原文；
    * `outcome is None` 且 `done` 不为真：退避中的请求，写的是这一轮失败的原文；
    * `ok`：已经成功过的行 —— 这次成功不负责清历史（重复登记时读数保持不变）；
    * `no_results`：那一格是命中读数，不是失败，它随 `outcome=ok` 一起作废。

    真机读数（lp-ball-13）：r-000002 seq162 的 429 与 r-000004 seq1724 的 429
    都是被后面的 `search.register` 擦成 None 的；r-000003 的 429 史能活下来，
    是因为 seq807 有一次人手 `table.update` 补写。
    """
    outcome = req.get("outcome")
    if outcome in ("search_failed", "gave_up"):
        return True
    if outcome is None:
        return req.get("done") is not True
    return outcome == "ok"


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
    # 有文献挂在请求上 ⇒ 这一问的终局是「取回了东西」（`outcome=ok`），不是
    # 「零命中」。这一格与 demo 路径（`demo.py` 第 366–380 行；该模块已于 2026-11-22 退役）同一条口径：
    # 回填 `result_lit_ids` 与写终局必须同时发生 —— 改前这里只写 ids，而
    # `run_once` 在判收之前已经把 `outcome=no_results` + 过期 `last_error`
    # （「入库 0 条、待裁 N 条」）留在盘上，于是真机上 `lit.admit_all` 收完
    # 4 条之后 R2（检索真的取回）仍只数到 1 条（`r-000001/2/5/7` 全是
    # `result_lit_ids` 非空 + `outcome=no_results`）。schema 的校验也要求
    # `outcome=ok` 时 `result_lit_ids` 非空 —— 这里刚刚 add 过，恒成立。
    #
    # 同一次写入的第二格是 `last_error`，改前无条件写 None —— 那是把
    # "这一问从没失败过"与"这一问现在成功了"折成同一读数：真机上 r-000002
    # seq162 的 429 就是这样被 seq960/966 的一次登记擦掉的（r-000004 同形）。
    # 现在 `last_error` 的语义是"最近一次失败"：一次成功只写 `outcome`，
    # 不替历史作证。保留与否的判据只有一处（`_keeps_failure_history`）。
    keep_failure_history = _keeps_failure_history(req)
    req["outcome"] = "ok"
    if not keep_failure_history:
        req["last_error"] = None
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
    scenario="开检索前先确认今天哪个源能用；连续失败时先看这里。",
    example="无参数探测：回每源的 available/status/reason 与可用、未探测计数。",
    example_code="search.providers()",
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
    "**不联网**：列出**全文在盘上**的文献（**本地书架**）—— 离线能引用哪些只看得到它。可按题名/路径筛。",
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
            "'truncated','books','note','query','filtered_out','coverage'}；"
            "coverage 是**整张文献表**的全文覆盖率 {'total','with_fulltext','rate','missing',"
            "'no_location','checked'}（rate=with_fulltext/total，total=0 时给 null 而不是 0；"
            "**no_location 是「我们连可取全文的地址都没有 ⇒ 没去取」，不是「这篇不存在」**——"
            "有地址但还没取的篇落进 missing，不落进 no_location）；"
            "books[] 每项是 {'lit_id','title','path','abs_path','bytes','pages',"
            "'has_text_layer','origin','sha256_12'}（origin ∈ local_ingest/downloaded）；"
            "失败：ok=False + kind(no_store/table_unreadable) + counted=False"
            "（**没数成**，不是「书架是空的」）"
            ),
    scenario="写引文前先看书架：只有在架上的文献能离线逐字引用。",
    example="列全架：回 books[]（lit_id/path/sha 前 12 位）与整表覆盖率 coverage。",
    example_code='search.shelf(query="cube")',
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
    "**不联网**：在本地书架全文里按主题取最相关的一页与**逐字摘录**（带 lit_id 与页码，引文回验用得上）。",
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
    scenario="要一条能回验的逐字引文（带页码），而不是书目条目。",
    example="按主题查：回 hits[] 的 lit_id/page/excerpt/score；读不了的书另计数。",
    example_code='search.local(query="cube slicing", limit=3)',
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

# TOOLFACE-SHARD3（片 3）：旧 summary 里两段细则搬到这里（模型面只留用法）。
# - 失败档处置：「换源 > 重试，`all_sources_failed` 走完」写进 A 手册 §六；
# - 候选绑定的内部接线：给了 `cand` ⇒ 失败与拿到落地页（`ok=True` +
#   `content_type_mismatch`）都落一条 `extract_failed` 回执（`_record_download_attempt`
#   → 候选行的 read_receipt），于是 `lit.admit` 能按仅题录判收；不给 `cand` 不变。
# 判据：`tests/test_tool_face_three_segments.py`（模型面不含实现名 / 注释里仍在）。
@tool(
    "search.download",
    "把候选的 `pdf_url` 下到 downloads/（回 sha256）。失败给 source 与 `fetch_kind`；"
    "`content_type_mismatch` 是落地页。",
    {
           "type": "object",
           "properties": {
            "url": {"type": "string", "minLength": 8, "maxLength": 2000},
            "hint": {"type": "string", "maxLength": 200},
            "max_bytes": {"type": "integer", "minimum": 1024, "maximum": 2_000_000_000},
            "cand": {"type": "string", "maxLength": 40,
                     "description": "候选槽位（`cand:<槽>` / `<槽>`）：给了它，这一趟的尝试绑在这条候选上"},
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
            "'content_warning','cand','read_receipt','warnings'}；"
            "失败：ok=False + kind(download_failed/download_error/unknown_slot/no_store/store_error) + "
            "fetch_kind（下载层那一档：tls_cert/tls_timeout/http_403/http_401/"
            "network_error/timeout/all_sources_failed …，见 fetch.ERROR_KINDS）"
            "+ cand（给了 cand 才有：归一后的槽位）+ read_receipt（这次失败落下的那条 "
            "extract_failed 回执；没给 cand ⇒ null）"
            "成功但 `content_warning=content_type_mismatch`（落地页 HTML）：ok=True 照旧给路径/字节，"
            "同时 read_receipt 非空（note=search.download.content_type_mismatch）"
            ),
    scenario="候选有 pdf_url、要拿全文；下成功后它回的 path 才能交给登记。",
    example="下一份：回 path/bytes/sha256；失败按 fetch_kind 处置（见 A 手册 §六），给了 cand 还留一条回执。",
    example_code='search.download(url="https://arxiv.org/pdf/2401.00001", hint="cube slicing", cand="c004")',
    tags=("search", "download"),
    external="egress",
)
def _search_download(ctx, url, hint="paper", max_bytes=DEFAULT_MAX_DOWNLOAD_BYTES, cand=""):
    """search.download 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（ctx）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _h_download(
               ctx, url, hint, max_bytes, cand
               )
    )

# TOOLFACE-SHARD3（业主 2026-11-22 三段格式，片 3）：从模型面搬下来的实现细节。
# 原文（旧 summary）：「不联网：按三级硬键（DOI → 标题+年 → 仅标题带年容差）说明
# 『会不会被判成已有的某篇』，并给出会命中的键。」
# 判重口径的真身在 `dedup.find_existing_literature`：三级硬键（① DOI 精确 →
# ② 标题+年份精确 → ③ 仅标题，年份容差 ±2，兜预印本/正式版漂移），没有模糊档；
# 相似标题只进 `near_misses` 供人复核，不是判重依据。
# 判据：`tests/test_tool_face_three_segments.py`（模型面不含实现名 / 注释里仍在）。
@tool(
    "search.dedup_check",
    "**不联网**：按 DOI / 题名+年判断会不会被判成已有的某篇；命中时给出会命中的键与既有那一行。",
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
    scenario="登记或入库前问一句：库里是不是已经有这一篇。",
    example="同 DOI 再问一次：回 would_be_duplicate=true、matched_key 与 existing。",
    example_code='search.dedup_check(title="Cube slicing in R^n", year=1986, doi="10.1007/BF02764936")',
    tags=("search", "dedup"),
)
def _search_dedup_check(ctx, title, year=None, doi=None):
    """search.dedup_check 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（ctx）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return _h_dedup_check(ctx, title, year, doi)


@tool(
    "search.retry_pending",
    "把「有元数据、没全文」的行逐条再取一次（每行一次、冷却中的源跳过）："
    "四结局 got / failed / no_location / cooled_down。",
    {
           "type": "object",
           "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "lit_id": {"type": "string", "maxLength": 40},
           },
           "required": [],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=("A",),
    returns=(
            "{'checked','scanned','attempted','counts','rows','stopped','coverage_before',"
            "'coverage_after','note'}；"
            "counts 是 {'got','failed','no_location','cooled_down'} 四个计数"
            "（sum(counts) == len(rows)）；"
            "rows[] 每项是 {'lit_id','outcome','source','url','kind','http_status','path',"
            "'bytes','sha256','error','cooldown_left_sec','note'}"
            "（outcome ∈ got/failed/no_location/cooled_down；"
            "**no_location 是「行上没地址 ⇒ 没去取」，不是「这篇不存在」**；"
            "cooled_down 是**跳过**、不是失败）；"
            "coverage_before / coverage_after 与 search.shelf 的 coverage 同形"
            "（{'total','with_fulltext','rate','missing','no_location','checked'}）；"
            "失败：ok=False + kind(no_store/table_unreadable) + counted=False"
            "（**没数成**，不是「没有要重取的行」）"
            ),
    scenario="书架有大片空缺，或上一轮下载失败后要补全文。",
    example="补一轮：counts 给四档计数；没地址的行记 no_location，不等于这篇不存在。",
    example_code="search.retry_pending(limit=20)",
    tags=("search", "download", "retry"),
    external="egress",
)
def _search_retry_pending(ctx, limit=RETRY_PENDING_DEFAULT_LIMIT, lit_id=""):
    """search.retry_pending 的工具体（注入的 ctx 由装配期用 `partial` 绑定）。"""
    return _h_retry_pending(ctx, limit, lit_id)

# TOOLFACE-CLEAN（业主 2026-11-22：实现只留在代码注释里）
# 原文（旧 param dry_run）：「只算 hash 与清单，不写盘、不进事务」。「不进事务」是内部写入口的性质；模型要知道的是「不写盘」。
# 判据：`tests/test_tool_face_three_segments.py` 钉住这条 needle（'不进事务'）
# 仍在注释里、且不在模型可见面上。
# TOOLFACE-SHARD3（片 3）：旧 summary 尾巴「provenance 如实写「由 A 登记」，不借
# 「人直接提供」」压缩成面上那一句「不借「人直接提供」」（`tests/fixtures/
# tool_declaration_baseline.json` 的 needle 要求它留在面上），provenance 的内部形状搬到这里。
# provenance 三件事的真身（`locallib.ingest_directory`）：
# 事务 `actor="agent-A"`、请求行 `submitted_by="unknown"`、正文写「由 agent-A 从一个
# 本地目录登记」—— 借 `human` 会把"这篇文献从哪来"说成假话。另有用户声明闸：
# 非 dry_run 只收工作区里被用户点名的文件（声明落 `RELIABLE-REFERENCES.json`），
# 未声明整笔拒、零写入。
@tool(
    "search.ingest_local",
    "**不联网**：把本地 PDF 登记进书架（按内容 sha256 幂等；dry_run 只算不写）。"
    "只收用户点名的文件，不借「人直接提供」。",
    {
           "type": "object",
           "properties": {
            "books_dir": {"type": "string", "minLength": 1, "maxLength": 1000,
                          "description": "本地目录（绝对路径或相对工作区）"},
            "pattern": {"type": "string", "maxLength": 40},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            "max_bytes": {"type": "integer", "minimum": 1024, "maximum": 2_000_000_000},
            "dry_run": {"type": "boolean",
                        "description": "只算 hash 与清单，不写盘"},
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
    scenario="用户把 PDF 放进 reference/ 并点名后，把它们收进书架。",
    example="先 dry_run 看清单：回 books[] 的 library_name/status 与 ingested 等计数。",
    example_code='search.ingest_local(books_dir="reference", pattern="*.pdf", dry_run=True)',
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

# TOOLFACE-SHARD3（业主 2026-11-22 三段格式，片 3）：从模型面搬下来的实现细节。
# 原文（旧 summary）：「登记文献（literature 行，processed=false）：先判重，命中复用
# lit_id；未命中则 alloc_id('lit') 并收编进 library/<lit_id>/。」
# 落点与内部形状（模型面只说「library/ 扁平 `<sha 前 12 位>-<名>`」这一句用法）：
# - 行落在 `literature` 表，`processed=False` 由本工具置、之后由 B 置 true；
# - 未命中时 `tx.alloc_id("lit")` 发号（同一事务内构造行、`validate()` 不过则整笔回滚）；
# - 文件收编走 `_adopt_file` → `locallib.library_landing`：新写一律 `library/<文献号>/<名>`
#   （同名不同内容追加内容短哈希、绝不覆盖；2026-11-25 起扁平 `<sha12>-<名>` 已退役）；
#   "文件已在 library/ 内"那一支**不再原样返回**：目录名不是文献号 ⇒ 交给
#   `locallib.relocate_into_entry` 搬进号目录（2026-11-26 MSRELOC）；
# - 判重命中支与新建支返回同一套 14 键（`G-23`），调用方不必先判 `created`；
# - 两道闸：直写路过声明闸（未声明的路径 ⇒ `not_declared_reference`、零写入）、
#   正文闸（`content_read=false` 时 summary 不许有内容性断言）。
# 判据：`tests/test_tool_face_three_segments.py`（模型面不含实现名 / 注释里仍在）。
@tool(
    "search.register",
    "登记一篇文献：先判重，命中就复用既有 lit_id；文件收编进 library/（扁平 "
    "`<sha 前 12 位>-<名>`），登记行交给 B 处理。",
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
            "'path','dedup_key','type_code','processed','download','warnings','relocation'}"
            "（created=false 表示判重命中，复用了既有 lit_id；两支键集合相同；"
            "relocation 是原件搬迁回执，判重支为空对象）"
            ),
    scenario="用户点名的工作区文件入库时用它；检索来的候选走 lit.stage_add → lit.admit。",
    example="带本地文件登记（summary 只写题录）：回 created/lit_id/path 与 download。",
    example_code=(
        'search.register(title="Cube slicing in R^n", type_code="J", '
        'summary="题录：立方体截面综述", path="downloads/cube.pdf", '
        'doi="10.1007/BF02764936", year=1986)'
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
# 业主 2026-10-20 口径（逐条落在这几件工具上）：① 一次委托正式入库至多 10 篇（`lit.admit` /
# `lit.admit_all` 挡住；广搜本身可以超过 10 条）；② 入库前要审内容，即使只拿到 3 篇也要逐篇
# 过（`lit.stage_list` 看得到每一条）；③ 内容不好可以撤掉换一篇：撤 = 槽位置空 + 写理由
# （`lit.stage_withdraw`），序号不复用、记录不物理删除；拒收走 `lit.stage_reject`；④ 与本地
# 库重叠度高的只有给了 `new_content` 才许入库（`lit.overlap_check` 的读数）；⑤ 待新增列表
# 支持增/删/查、可多次追加；⑥ 列表按「委托」重置（默认视图只看当前委托）+ 提交整批
# `lit.admit_all`（判定完收口、结算不物理删、写委托报告）。判据真身全在 `agentflow/litstage.py`
# （上限、阈值、状态机、报告结构只有那一处）；工具层只做参数校验与把结论翻成 `ToolResult`。


def _stage_fail(exc: Exception) -> Any:
    """把 `litstage` 的受控错翻成工具层的 `fail`（模型据此能改）。

    `LitStageError` / `StoreError` 的绑定在模块顶部：四个 handler 的 `except` 元组
    与这里读的是同一个名字（2026-10-24 修复的缺陷 A：它们此前只在
    `_stage_fail` / `lit.admit` / `lit.admit_all` 里局部 import，于是底层一抛错，
    `except (LitStageError, ...)` 自己先 `NameError`，三态被折成 `unexpected`）。
    """
    if isinstance(exc, LitStageError):
        return fail(str(exc), kind=exc.kind, **dict(exc.detail or {}))
    if isinstance(exc, StoreError):
        return fail(f"待新增列表这次没读成/没写成：{type(exc).__name__}: {exc}",
                    kind="store_error")
    return fail(f"{type(exc).__name__}: {exc}", kind="unexpected")


#: `download.fulltext` 的三档口径只有一份实现（`litread.fulltext_tier`）。
#:
#: 为什么这里不再留一个"本次没有全文"的私有标记值：改前全仓只有这一个写点
#: （`_mark_candidate_locator`）、清除点为零，于是 `status=ok` 的行也一直挂着它
#: （真机 19 条 `no_fulltext` 里 6 条自相矛盾）。现在写点与清除点都调
#: `litread.with_fulltext`：没有字节 ⇒ `no_fulltext`；有字节但这一处没抽过文本
#: ⇒ 不算档（`None`）并清掉旧标签 —— 猜一个档位就是让读数重新说谎。


def _mark_candidate_locator(ctx: _Ctx, lit_id: str, row: Mapping[str, Any]) -> bool:
    """把候选行的 url 写进 literature 行的 download 栏，并标明"本次无全文"。

    为什么必须做（审计读数）：一键迁移原来这样登记 —— `_h_register(..., path=None)`，
    于是 literature 行上 `path=null`、`download={"status":"skipped",
    "error":"no_local_path"}`。B 领取到这样一行只能写 `no_local_file`：这一篇
    从哪来、还能去哪取，盘上一个字都没有。候选行上本来就有 `url`（provider
    给的检索/落地链接），它是"这篇在哪"的唯一证据，不落下来就等于丢掉了。

    为什么写 download 栏而不是新加一列：`download` 是既有字段（`schema` 是禁改区，
    列不许加），它本来就是"这一篇的字节从哪来、到了没有"的落点。写入的键：
    `url`（定位符）、`fulltext`（三档现算的结果）、`error`、`note`。

    2026-11-05（M3）：这一处原来只管"path 为空 ⇒ 写标记"，path 非空时直接返回
    —— 那是半条：一行后来有了字节（下载/重取/收编），旧的"没有全文"标签没有任何
    人清。现在两条分支成对：有字节就只清旧标签（这一处没抽过文本，不猜档位；
    url 与 note 也不动，那属于"真的有全文"的行）；没字节才写 `no_fulltext`。
    返回是否真的改了盘上的行（幂等：同一个 url 且档位已是 no_fulltext 就不写）。
    """
    url = str(row.get("url") or "").strip()
    if not url or not lit_id or ctx.store is None:
        return False
    with ctx.store.tx("literature", actor=ctx.actor, note="search.register.locate") as tx:
        got = tx.find("literature", lit_id=lit_id)
        if got is None:
            return False
        dl = dict(got.get("download") or {})
        # 字节数按 `_lit_file` 的唯一真身（`store.library_path`）现算
        #（与 `search.shelf` 同一个读法；旧布局 ⇒ 0 字节，不按工作区基准另读一份）。
        on_disk = LR.bytes_on_disk(_lit_file(ctx, str(got.get("path") or "")))
        tier = LR.fulltext_tier(bytes_on_disk=on_disk, pages=None)
        if tier is None:
            # 有字节：这一处没有抽过文本，所以不猜档位；但旧标签必须清掉，
            # 否则"status=ok 却写着没有全文"会一直留着。
            if "fulltext" not in dl:
                return False
            got["download"] = LR.with_fulltext(dl, None)
            S.Literature(**{k: got[k] for k in got
                            if k in S.Literature.__dataclass_fields__}).validate()
            tx.upsert("literature", got, note="search.register.locate.clear")
            return True
        if dl.get("url") == url and dl.get("fulltext") == tier:
            return False
        dl.setdefault("status", "skipped")
        have = str(dl.get("url") or "").strip()
        if have and have != url:
            # 行上已经有一个不同的定位符（同一篇由另一个源登记过）：不丢它 ——
            # 两个 url 都是真的，覆盖等于让"上一次登记的是哪个"不可查。
            dl["url_previous"] = have
        dl["url"] = url
        dl["error"] = dl.get("error") or tier
        dl["note"] = ("本次无全文：只登记了候选源给出的定位链接（url 这一格），"
                      "没有下载字节；要全文请按它重取")
        got["download"] = LR.with_fulltext(dl, tier)
        S.Literature(**{k: got[k] for k in got
                        if k in S.Literature.__dataclass_fields__}).validate()
        tx.upsert("literature", got, note="search.register.locate")
    return True


def _registrar_from_candidate(ctx: _Ctx, row: Mapping[str, Any]) -> dict:
    """把一条待新增候选走现有的 `search.register` 登记路径落成 literature 行。

    两条入口（`lit.admit` 逐条入库与 `lit.admit_all` 提交整批）共用这一份。
    它们原来各有一段逐字相同的闭包：改一处漏一处，"收进库的行没有
    定位栏、B 一用就是 unreadable"就会在原地复发。

    登记之后补写定位栏（`_mark_candidate_locator`）：登记路径自己只认
    `path`（library 下的相对路径），而候选行手上只有 url —— 两件事分开写，
    谁也不冒充谁。

    2026-10-27（B1，Q16 暴露的读数回退）：`request_id` 必须从候选行带过来。
    改前这里写死 `request_id=None`，于是判收造出的 literature 行
    `source_request_ids == []`、请求行的 `result_lit_ids` 也永不回填 ——
    `closing.py` 用前者判"这一篇是不是检索来的"，两份报告直接打印后者，
    两处读数因此都缺一格。候选行上本来就有这个号（`litstage` 造行时写死的），
    所以这不是"多要一个参数"，是把它手上已有的那份事实传下去。

    ## 2026-11-16（裁定 3）：把"读过"的字节带进库

    候选期抽读（`text.extract(lit_id="cand:<槽位>")`）的源文件在 `downloads/`，
    而登记路径原来一律 `path=None` ⇒ 一条判成 `readable` 的候选进库之后仍然
    `path=null`，B 只能写 `no_local_file`，"读过"这件事在库里一个字都不剩。
    所以：这一条真的读过（`litavail.check_read == "ok"`）时，把抽读回执里的
    源文件交给登记路径收编（`_adopt_file` 收编进 `library/<内容 hash 前缀-名>`；
    源文件在投放处/被声明覆盖时**只复制**，原件留在原处 —— 2026-11-24 裁定，
    见 `locallib.keeps_original`），
    回执的档位写进 `download.fulltext=ok`。没读过的照旧 `path=None`：行上不会凭空
    多出一份没人读过的文件。
    """
    slot = str(row.get("slot") or "")
    receipt = None
    state = "no_extract"
    read_ok = False
    if ctx.store is not None:
        receipt = LAV.receipts_by_slot(ctx.store.root).get(slot)
        state, _why = LAV.check_read(ctx.store.root, slot, receipt,
                                     expected=LAV.candidate_digest(row))
        # "读没读到正文"只有一处实现（`litavail.content_read`：抽读成功 + 非空 +
        # 不只摘要 + `fs.read` 读过同一版）。正文闸要的正是这个读数 —— 这里现算，
        # 而不是把"抽过"（`state == "ok"`）当成"读过"。
        read_ok, _body_why = LAV.content_read(ctx.store.root, slot, row,
                                              tier=str(LAV.tiers_by_slot(
                                                  ctx.store.root).get(slot) or ""),
                                              receipt=receipt)
    source = str((receipt or {}).get("source") or "") if state == "ok" else ""
    res = _h_register(
        ctx,
        title=str(row.get("title") or ""),
        type_code=str(row.get("type_code") or "Z"),
        summary=str(row.get("summary") or ""),
        path=(source or None),
        doi=row.get("doi"),
        year=row.get("year"),
        request_id=str(row.get("request_id") or "") or None,
        read_ok=read_ok,
        # 候选链的准入依据是候选行 + 读过正文，不是"用户点名了哪个工作区文件" ⇒
        # 声明闸不适用。这个参数是下划线参数、不在工具 schema 里，模型传不进来。
        _from_candidate=True,
    )
    if not res.ok:
        return {"lit_id": None, "reason": res.error}
    data = dict(res.data or {})
    lit_id = str(data.get("lit_id") or "")
    _mark_candidate_locator(ctx, lit_id, row)
    if receipt is not None and state == "ok" and data.get("created"):
        _mark_read_fulltext(ctx, lit_id, receipt)
    return data


def _mark_read_fulltext(ctx: _Ctx, lit_id: str, receipt: Mapping[str, Any]) -> bool:
    """把"候选期已抽读"这一档写进 `download.fulltext`（与 `litread.with_fulltext` 同一处）。

    为什么这一格值得单独写：`_mark_candidate_locator` 在"有字节、但这一处没抽过"
    时只清旧标签（它不猜档位）。候选期确实抽过、也读过了，那份事实在抽读回执里；
    不落进 literature 行，B 与后续审计看到的仍是"有字节但没抽过"（`unknown`）。
    """
    if ctx.store is None or not lit_id:
        return False
    try:
        with ctx.store.tx("literature", actor=ctx.actor,
                          note="search.register.read") as tx:
            row = tx.find("literature", lit_id=lit_id)
            if row is None:
                return False
            payload = dict(row)
            dl = dict(payload.get("download") or {})
            dl = LR.with_fulltext(dl, LR.FULLTEXT_OK)
            dl["note"] = (f"候选期已抽读：{int(receipt.get('chars') or 0)} 字"
                          f"（指纹 {str(receipt.get('sha256') or '')[:12]}）")
            payload["download"] = dl
            S.Literature(**{k: payload[k] for k in payload
                            if k in S.Literature.__dataclass_fields__}).validate()
            tx.upsert("literature", payload, note="search.register.read")
        return True
    except Exception:  # noqa: BLE001 - 落点失败不许把登记本身带坏（读数仍在回执里）
        return False


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
    # 键集合必须静态可见，所以这里逐键搬，不用 `got`。
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

    ## `entries[].url` 的来源（C1FIX-URISRC ①，2026-11-23）

    这一件是「模型把地址写进候选行」的那个入口，所以它也是唯一能记下"这个地址从哪来"
    的地方（`schema.LitCandidate` 没有这一格，且那张表是 FC-27 的 schema-migration）：
    每个带 `url` 的 entry 都按 `url_origin` 逐条记进 `data/lit_url_origins.jsonl`，
    `search.download(cand=…)` 再用它给收据点名。

    三档自报（`provider` / `webpage` / `self_constructed`，词表外当场拒）：

    * `provider`：`search.literature` 这次真的报过这个地址（框架自己记的台账为准）。
      **自报 `provider` 而台账里没有 ⇒ 整笔受控拒 `url_origin_unverified`** ——
      这是本层唯一的硬闸：谎报出处是这里唯一没有正当用法的形态。拒之前一行都不写
      （先把"出处"洗进候选行、再让下载认它，这条路必须在写侧断掉）。
    * `webpage` / `self_constructed`：照实说就照收（从网页正文里读到真实 PDF 链接是
      合法用法，框架核不了，所以只做透明化、不做硬闸）；不填按 `self_constructed` 记。
    """
    from ..litstage import stage_entries

    try:
        # 复制一次再判：`entries` 可能是生成器，而下面要判来源、`stage_entries` 还要再读一遍。
        items = [dict(entry) for entry in entries]
    except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
        return _stage_fail(exc)
    plans, unverified, bad_origins = _stage_origin_plan(ctx, items)
    if bad_origins:
        return fail(
            "entries[].url_origin 只能是 "
            f"{list(URL_ORIGINS)} 之一：{bad_origins}（自造一档读不出「这地址从哪来」，"
            "与「没填」同形）",
            kind="bad_url_origin", entries=bad_origins[:8],
        )
    if unverified:
        return fail(
            f"这 {len(unverified)} 条自报 `url_origin=provider`，但这一次没有任何 provider "
            f"返回过它们的 url：{unverified[:8]}。候选行不是地址的出处 —— 先把地址标成 "
            "provider 再让 `search.download` 认它，正是「自拼地址洗进候选行」那条路，"
            "所以整笔拒（一行都没写）。照实填 `self_constructed` / `webpage`，"
            "或先 `search.literature` 拿到 provider 的 pdf_url 再暂存。",
            kind="url_origin_unverified", entries=unverified[:8],
            count=len(unverified),
        )
    try:
        got = stage_entries(ctx.store, items, request_id=request_id, batch=batch,
                            actor=ctx.actor)
    except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
        return _stage_fail(exc)
    _record_staged_origins(ctx, plans, request_id=str(got["request_id"]))
    return ok({
        "request_id": got["request_id"],
        "batch": got["batch"],
        "count": got["count"],
        "staged": got["staged"],
        "updated": got["updated"],
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

    `status` 按三态查：`pending` 待裁 / `admitted` 入库 / `rejected` 拒收
    （2026-10-26 Q16 起状态只有这三档；盘上的历史档 `cleared` / `withdrawn`
    由 `litstage.fold_legacy` 在读侧折成 `rejected` + 受控理由码，按老名字查
    仍然查得到那几条）。所以列表里"撤掉的空槽位"显示为 `rejected` +
    `reason_code=withdrawn_by_reviewer`：序号不复用、题名与理由都留着 ——
    于是"第 3 号被撤了哪一篇、为什么"查得出来（"撤掉 ≠ 删掉"）。
    """
    from ..litstage import list_candidates, note_readback

    try:
        got = list_candidates(ctx.store, request_id=request_id, batch=batch, status=status)
    except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
        return _stage_fail(exc)
    # 回读回执（业主裁定 ①）：这一次「A 回读了自己刚写的清单」由工具面记账，
    # 提交闸（`lit.admit` / `lit.admit_all`）验它覆盖了要提交的每一个槽位。
    # 只认具体委托（`request_id="*"` 的全查不记账：它不回答"这一批回读过没有"）。
    note_readback(ctx.store, got["request_id"], got["rows"])
    return ok({
        "request_id": got["request_id"],
        "current_request_id": got["current_request_id"],
        "batch": got["batch"],
        "status": got["status"],
        "count": got["count"],
        "counts": got["counts"],
        "duplicate_rows": got["duplicate_rows"],
        "duplicate_groups": got["duplicate_groups"],
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


def _h_lit_stage_reject(ctx: _Ctx, slot: str | None = None, reason_code: str = "",
                        note: str = "", slots: Iterable[str] | None = None) -> Any:
    """``lit.stage_reject``：审内容后拒收 —— 写 `reject_reason` + 受控 `reason_code`，保留行。

    `reason_code` 用 `rejected_off_topic` / `rejected_low_quality` /
    `overlap_without_new_content` / `duplicate_doi` 这几档（见 `schema.CANDIDATE_REASON_CODES`）。

    可读性判定不在这里收（这一件是拒收，不是入库）：判拒时若已经有判定（例如先试过
    `lit.admit` 带 `availability=extract_failed` 被闸挡下），台账里那一条会原样留着，
    报告照常逐条列；没有就显示 `未查`。要补可读性判定走 `lit.stage_list` 看回读后的那一格。

    ## 两种目标形（2026-11-19 FIXBATCH ①）

    - `slot=<一个槽位>`：老的单槽形，返回那七格（逐字不动）；
    - `slots=[…]`：批量形 —— 一次调用判拒多个槽位，内部对每一条仍然调
      `litstage.reject`（受控理由码 + 逐行写 `reject_reason`，写口一个字没动）。
      存在的理由（真机 lp-ball-11）：60 条待裁跨 6 个委托，A 的 final 逐字写
      「逐槽判拒需 60 次调用，超出剩余预算」而按委托分批只要 6 次。批量只省调用
      次数，不省逐条判定：混进无效槽位时，有效的照样落盘、无效的受控拒并
      点名（`refused[]`），不许一条坏的全笔作废；一条都没落成时回 `kind=all_refused`
      （"都没落"不许读成"都落了"）。
    """
    if slots is not None:
        return _h_lit_stage_reject_many(ctx, slots, reason_code, note)
    if not str(slot or "").strip():
        # `slot` 不再是 schema 的必填格（批量形不给它）⇒ 两个都没给时在这里受控拒，
        # 而不是拿 None 去查表（那样报的是 `unknown_slot`，会把人指向错误的下一步）。
        return fail("判拒要给一个槽位（`slot`）或一组槽位（`slots`）",
                    kind="no_target")
    return _h_lit_stage_reject_one(ctx, slot, reason_code, note)


def _h_lit_stage_reject_one(ctx: _Ctx, slot: str, reason_code: str, note: str = "") -> Any:
    """单槽形（老路）：落一行、回那七格。判拒的写口与口径都在 `litstage.reject` 里。"""
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


def _h_lit_stage_reject_many(ctx: _Ctx, slots: Iterable[str], reason_code: str,
                             note: str = "") -> Any:
    """批量形：逐条判拒，有效的落盘、无效的受控拒并点名（正文见 `_h_lit_stage_reject`）。

    逐条各自成一个 `litstage.reject` 事务（不合成一个事务）：行级写口只此一处
    （`litstage._terminal`），批量这一层只负责"跑完这一列并如实分别记账"。合进一个
    事务会让一条坏槽位把整批回滚 —— 那正是这条判据要防的"整体失败"。
    """
    from ..litstage import reject

    wanted = [str(s).strip() for s in (slots or []) if str(s or "").strip()]
    if not wanted:
        return fail("批量判拒要至少给一个槽位（空列表不许当成「都判过了」）",
                    kind="no_target")
    rejected: list[dict] = []
    refused: list[dict] = []
    for slot in wanted:
        try:
            got = reject(ctx.store, slot, reason_code, note, actor=ctx.actor)
        except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
            # 逐槽受控拒：`kind` 从 `litstage` 的受控错里取（`unknown_slot` /
            # `not_pending` / `bad_reason_code` …），不自己另造一套分类。
            refused.append({
                "slot": slot,
                "why": str(exc) or type(exc).__name__,
                "code": str(getattr(exc, "kind", "") or "unexpected"),
            })
            continue
        rejected.append(got)
    if not rejected:
        return fail(
            f"这一批 {len(wanted)} 个槽位一条都没判成（全表状态没有任何一行被改成 rejected）",
            kind="all_refused", count=0, slots=wanted, refused=refused)
    return ok({
        "slots": wanted,
        "count": len(rejected),
        "rejected": rejected,
        "refused": refused,
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
    ## 2026-10-26（Q16）新加的一条硬判据：没有 relevance 的槽位不许入库
    判过的证据就是那一句"为什么与本次检索相关"（`lit.stage_add` 时写进候选行）。
    缺它就拒（`missing_relevance`，行保持原样）：`lit.admit` 是逐条判决的入口，
    不是"批量搬库"的入口 —— 批量搬库那条路（`lit.admit_all`）已经被"还有待裁就整批拒"
    挡住了。
    ## 两个上限（业主口径 ①，超了「整笔拒绝」）
    - 本次调用 ≤ ``MAX_ADMIT_PER_CALL = 10`` 条；- 该委托累计已入库 + 本次 ≤ ``MAX_ADMIT_PER_DELEGATION = 10`` 条。
    ## 逐条拒收（业主口径 ②④）
    - 这一条已经判过（`litstage.judged_state != "pending"`）⇒ 拒；- DOI 与本地库某一行「完全相同」 ⇒ 视为重复，拒（这一档 `new_content` 救不了）；- 标题词集
    Jaccard ≥ 0.60 且「没有」 `new_content` ⇒ 拒（行上写的 `new_content` 优先，`items[].new_content` / 调用级 `new_content` 兜底）。
    `overlap_ok=True` 「不替代」 `new_content`：它只如实记下"调用方表过态"，真正的放行仍要有那句新内容。`overlap_ok=False` 则直接拒这一条。
    ## 入库走的是现有路径
    registrar 就是 `search.register` 的 handler（`_h_register`：判重 → `alloc_id("lit")`→ 落 `literature` 行 → 收编文件）。本工具里没有
    一处直接写 `literature` ——"绕开登记路径"在结构上做不到（判据见 `tests/test_search_tools_stage_admit.py`）。
    「它不清空列表」：清空是一次委托的收尾动作，属于 `lit.admit_all`。
    """
    from ..litstage import admit as _admit

    if ctx.store is None:
        return fail("未配置 store：入不了库（不是「都重复了」）", kind="no_store")

    wanted: list[str] | None
    payload: dict[str, dict] = {}
    #: 这一次调用带的可读性判定（`slot -> tier`）：逐条自审的第二个问题（业主裁定 ②）。
    #: 落进旁路台账 `data/lit_availability.jsonl`（零 schema），闸从那里取证据。
    avail: dict[str, str] = {}
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
            tier = str((raw or {}).get("availability") or "").strip()
            if tier:
                if tier not in LAV.AVAILABILITY_TIERS:
                    return fail(
                        f"可读性判定必须是 {list(LAV.AVAILABILITY_TIERS)} 之一，收到 {tier!r}"
                        "（自己拼一档，例如 pdf_no_text，不算审过）",
                        kind="bad_availability", slot=slot)
                avail[slot] = tier
    else:
        wanted = [str(s).strip() for s in (slots or []) if str(s or "").strip()] or None
        if wanted:
            for slot in wanted:
                payload[slot] = {"new_content": str(new_content or "").strip(),
                                 "overlap_ok": overlap_ok}
    if wanted is None and batch is None:
        return fail("admit 要么给 slots / items，要么给 batch", kind="no_target")

    # 判定先落台账（闸从台账取证据，所以必须在 `_admit` 之前写）：写在后面的话，
    # 这一次提交读到的仍是旧判定 —— "刚判的这条"与"闸看到的这条"会差一拍。
    if avail:
        from ..litstage import current_request_id as _current_rid

        rid_for_ledger = str(request_id or "").strip() or _current_rid(ctx.store)
        # 逐条判断的读数（业主裁定 3）：把这一条候选的 relevance 与它的抽读指纹
        # 一并写进判定行 —— 报告/闸不必再回表拼，人查时一行就能看出
        # "它凭什么被放行、读过多少字"。读不到表就不抄（档位照旧写，fail-closed）。
        rel_by_slot: dict[str, str] = {}
        row_by_slot: dict[str, dict[str, Any]] = {}
        try:
            for row in ctx.store.rows("lit_candidates"):
                slot = str(row.get("slot") or "")
                if slot in avail:
                    rel_by_slot[slot] = str(row.get("relevance") or "")
                    row_by_slot[slot] = dict(row)
        except Exception:  # noqa: BLE001 - 读者格失败不许把判定本身带坏
            rel_by_slot = {}
        read_by_slot = LAV.receipts_by_slot(ctx.store.root)
        try:
            for slot, tier in avail.items():
                # `content_read` 是机器现算的读数（抽读成功 + 非空 + 不只摘要 + fs.read），
                # 不是 A 自报：没算过就按 False 记 —— "没算"不许冒充"读过"。
                read_ok, _read_why = LAV.content_read(
                    ctx.store.root, slot, row_by_slot.get(slot) or {},
                    tier=tier, receipt=read_by_slot.get(slot))
                LAV.record_availability(ctx.store.root, rid_for_ledger, slot, tier,
                                        note="lit.admit", actor=ctx.actor,
                                        relevance=rel_by_slot.get(slot, ""),
                                        read=read_by_slot.get(slot),
                                        content_read=read_ok)
        except (ValueError, OSError) as exc:
            return fail(f"可读性判定没写进台账：{exc}", kind="availability_ledger")

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
        # （那里也补写定位栏，于是"逐条入库"与"提交整批"落出来的行同形）。
        return _registrar_from_candidate(ctx, row)

    try:
        got = _admit(ctx.store, registrar=_registrar, request_id=request_id, slots=wanted,
                     batch=batch, new_content=new_content, actor=ctx.actor)
    except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
        return _stage_fail(exc)
    if got.get("whole_call_refused"):
        # 整笔拒绝也要让模型读到读数（`fail` 的 meta 就是给这个用的）。
        # `undecided` 是 2026-10-26（Q16）那一档的机器读数：逐条点名的槽位 + 题名，
        # 与拒信正文同一个来源（`litstage.undecided`），所以模型照 meta 也能一条条去判。
        return fail(got.get("reason") or "入库被拒", kind=got.get("kind") or "over_cap",
                    request_id=got.get("request_id"), batch=got.get("batch"),
                    call_size=got.get("call_size"), call_limit=got.get("call_limit"),
                    delegation_admitted=got.get("delegation_admitted"),
                    delegation_limit=got.get("delegation_limit"),
                    refused=got.get("refused"), undecided=got.get("undecided"),
                    missing_readback=got.get("missing_readback"),
                    missing_availability=got.get("missing_availability"),
                    availability_bad=got.get("availability_bad"),
                    unjudged_no_content=got.get("unjudged_no_content"),
                    content_assertions=got.get("content_assertions"),
                    read_problems=got.get("read_problems"))
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
    slots: Sequence[str] | None = None,
) -> Any:
    """``lit.admit_all``：「提交一批」 —— 判完的这一批入库 + 报告，然后清这一批的行。

    2026-10-26（Q16）起它前面有一道提交闸：这一批只要还有一条没判，整批一条都不许
    入库，拒信逐条点名（`槽位 + 题名前 40 字`）并给做法。所以"一键把没读过的都塞进去"
    这条路没有了 —— 逐条判（`lit.admit` 的条目带 relevance / `lit.stage_reject` 判拒）
    是唯一的入库方式，本工具是"判完收口"。

    2026-11-17（FX3·甲）起提交粒度是批次不是整委托：`slots` 点名这一次覆盖哪些槽
    （默认 = 本委托已判定的全部）。15 槽判完 5 槽 ⇒ 可以只交这 5 槽，其余 10 槽保持
    `pending` 进下一批；批外未判的槽不拦这一笔（收工闸仍看全表）。批内全判是硬要求：
    点名点到没判的槽 ⇒ `undecided_items` 整批拒，一格没放宽。

    业主 2026-10-20 第 2 条那四件事仍在，顺序固定（实现见 `litstage.admit_all`）：
    1. 取这一批判收未注册的行，逐条过「重叠检查」；2. 通过的走「现有登记路径」；
    3. 「结算这一批」：成功落 `admitted`、被拒落 `rejected(理由码)`；4. 写报告
    （无号原件 + 带号定稿）并清这一批的行。「不物理删」。

    它仍守"一次委托至多入库 10 篇"与"重叠高需 `new_content`"两条。
    """
    from ..litstage import admit_all as _admit_all

    if ctx.store is None:
        return fail("未配置 store：入不了库（不是「都重复了」）", kind="no_store")

    def _registrar(row: Mapping[str, Any]) -> dict:
        # 判据只有一份：与 `lit.admit_all` 共用 `_registrar_from_candidate`
        # （那里也补写定位栏，于是"逐条入库"与"提交一批"落出来的行同形）。
        return _registrar_from_candidate(ctx, row)

    try:
        got = _admit_all(ctx.store, registrar=_registrar, request_id=request_id,
                         slots=slots, new_content=new_content, actor=ctx.actor)
    except (LitStageError, StoreError, ValueError, TypeError) as exc:  # noqa: BLE001
        return _stage_fail(exc)
    if not got.get("ok"):
        return fail(got.get("reason") or "这一批提交被拒", kind=got.get("kind") or "over_cap",
                    request_id=got.get("request_id"), submitted=got.get("submitted"),
                    refused=got.get("refused"), undecided=got.get("undecided"),
                    missing_readback=got.get("missing_readback"),
                    missing_availability=got.get("missing_availability"),
                    availability_bad=got.get("availability_bad"),
                    unjudged_no_content=got.get("unjudged_no_content"),
                    content_assertions=got.get("content_assertions"))
    return ok({
        "ok": got["ok"],
        "kind": got["kind"],
        "whole_call_refused": got["whole_call_refused"],
        "reason": got["reason"],
        "request_id": got["request_id"],
        "submitted": got["submitted"],
        "call_size": got["call_size"],
        "call_limit": got["call_limit"],
        "delegation_admitted": got["delegation_admitted"],
        "delegation_limit": got["delegation_limit"],
        "pending_total": got["pending_total"],
        "pending_by_delegation": got["pending_by_delegation"],
        "pending_scope_note": got["pending_scope_note"],
        "admitted": got["admitted"],
        "refused": got["refused"],
        "cleared": got["cleared"],
        "registered": got["registered"],
        # 2026-11-26 MSRELOC：原件搬迁回执（`litstage.relocate_settled_originals` 的逐条读数）。
        # 与 `lit.relocate` 事件同源：`status` 是 `locallib.RELOCATE_*` 之一，
        # `from`/`to` 是 `library/` 相对名，`slot`/`lit_id`/`sha256` 五格齐。
        "relocations": got["relocations"],
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
        "availability": {"type": "string", "enum": list(LAV.AVAILABILITY_TIERS),
                         "description": "这一条的可读性判定（逐条自审的第二个问题）："
                                        "readable 可读全文 / metadata_only 仅题录 / "
                                        "extract_failed 抽过但失败 / unknown 未查。"
                                        "不给 ⇒ 这一条不许入库"},
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
        "url_origin": {"type": "string", "enum": list(URL_ORIGINS),
                       "description": "这个 url 是从哪来的（照实填）："
                                      "provider = 从 search.literature 这次返回的 "
                                      "pdf_url/landing_url 原样抄来；webpage = 从网页正文里读到"
                                      "的链接；self_constructed = 自己拼的。不填按 "
                                      "self_constructed 记；填 provider 而这次没有 provider "
                                      "返回过它 ⇒ 整笔受控拒（url_origin_unverified）"},
        "relevance": {"type": "string", "maxLength": 400,
                      "description": "一句「它为什么与本次检索相关」，委托报告要用"},
    },
    "required": ["title"],
    "additionalProperties": False,
}


# TOOLFACE-SHARD3（业主 2026-11-22 三段格式，片 3）：从模型面搬下来的实现细节。
# 原文（旧 summary）：「……否则标题词集 Jaccard（阈值 0.60）≥ 阈值 ⇒ 必须给
# new_content 才许入库。」
# 重叠口径的真身：`litstage` 的 overlap 判据 —— DOI 归一后完全相同 ⇒ 重复；
# 否则标题词集 Jaccard ≥ 0.60 判"重叠度高"，此时必须给 new_content（或 overlap_ok）。
# 阈值只有一处实现，工具层只把结论翻成读数；模型面只需要「重叠高就要说清新的内容」。
# 判据：`tests/test_tool_face_three_segments.py`（模型面不含实现名 / 注释里仍在）。
@tool(
    "lit.overlap_check",
    "**不联网**：这一条与本地库重叠多少？DOI 相同算重复；题名高度相近时要给 "
    "new_content 才许入库。",
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
    scenario="候选入库前查重：重叠高的那条必须说清「要的新内容」。",
    example="问一条：回 duplicate / overlap_score / requires_new_content / overlap_with。",
    example_code='lit.overlap_check(title="Cube slicing in R^n", doi="10.1007/BF02764936")',
    tags=("lit", "stage", "overlap"),
)
def _lit_overlap_check(ctx, title, doi=None):
    """lit.overlap_check 的工具体。"""
    return _h_lit_overlap_check(ctx, title, doi)


@tool(
    "lit.stage_add",
    "把广搜结果追加进本次委托的待新增列表（单次最多 500 条；同一委托内同一篇只占一个槽，"
    "补 relevance 就更新原槽）。",
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
        "{'request_id','batch','count','staged','updated'}；"
        "staged[] 每项是 {'slot','batch','title'}；"
        "updated[] 每项是 {'slot','batch','title'} 再加一格补进去的字段名列表"
        "（那格空 = 这一条没有新内容可补，它已经在列表里）；"
        "失败：ok=False + kind(no_store/no_delegation/bad_delegation/empty_batch/bad_batch/"
        "bad_entry/store_error) 之一 + 明细"
    ),
    scenario="刚检索完，先把候选放进待审列表，再逐条判。",
    example="追加一条：回 staged[] 新槽；同一篇已在列表就回 updated[] 原槽。",
    example_code=(
        'lit.stage_add(request_id="r-NNNNNN", entries=[{"title": "Cube slicing in R^n", '
        '"year": 1986, "relevance": "截面体积上界"}])'
    ),
    tags=("lit", "stage", "add"),
)
def _lit_stage_add(ctx, request_id, entries, batch=None):
    """lit.stage_add 的工具体。"""
    return _h_lit_stage_add(ctx, request_id, entries, batch)


# TOOLFACE-CLEAN（业主 2026-11-22：实现只留在代码注释里）
# 原文（旧 summary）：「（词表真身在 litstage.CANDIDATE_DECISIONS）」。三态词表的落点属实现；模型面已经把三档逐条写出来了，不需要知道常量住哪。
# 判据：`tests/test_tool_face_three_segments.py` 钉住这条 needle（'CANDIDATE_DECISIONS'）
# 仍在注释里、且不在模型可见面上。
@tool(
    "lit.stage_list",
    "查待新增列表（默认当前委托）：`pending` 待裁 / `admitted` 入库 / "
    "`rejected` 拒收；`cleared`/`withdrawn` 读成 `rejected`。",
    {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "maxLength": 40,
                           "description": "哪一次委托（不给 = 当前委托；*= 全部委托）"},
            "batch": {"type": "integer", "minimum": 1, "maximum": 100000},
            "status": {"type": "string", "enum": list(S.CANDIDATE_STATUSES),
                       "description": "`cleared` / `withdrawn` 是历史档（读成 `rejected`），"
                                      "留着只为查历史"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("A",),
    returns=(
        "{'request_id','current_request_id','batch','status','count','counts','duplicate_rows',"
        "'duplicate_groups','gaps','rows','total_all_delegations','note'}；"
        "duplicate_rows = 落在「同一身份多个槽位」里的行数（只报数，counts 不折算）；"
        "duplicate_groups[] 每项给身份与槽位表两格（键名 key / slots；没有重复时是空数组）；"
        "counts 的键是三态那三档，另有两个历史档键"
        "（恒为 0 —— 它们已读成 rejected）；"
        "rows[] 每项是 {'slot','batch','status','title','request_id','doi','provider','year',"
        "'type_code','summary','url','added_at','relevance','lit_id','admitted_at',"
        "'reason_code','withdrawn_reason','reject_reason','cleared_at','clear_reason',"
        "'new_content','overlap_score','overlap_kind','overlap_with','overlap_ok',"
        "'availability'}（最后一格是四档可读性判定；空串 = 还没审）；"
        "失败：ok=False + kind(no_store/bad_status/no_delegation/store_error)"
    ),
    scenario="看还剩哪些没判、哪些已入库或拒收；撤掉的空槽也在列表里。",
    example="筛待裁：回 rows[] 逐槽与 counts 三档；历史档按老名字也查得到。",
    example_code='lit.stage_list(request_id="r-NNNNNN", status="pending")',
    tags=("lit", "stage", "list"),
)
def _lit_stage_list(ctx, request_id=None, batch=None, status=None):
    """lit.stage_list 的工具体。"""
    return _h_lit_stage_list(ctx, request_id, batch, status)


@tool(
    "lit.stage_withdraw",
    "撤掉某一槽：落 `rejected` + 理由码 `withdrawn_by_reviewer`，序号不变、不物理删。"
    "只是缺 relevance 时别撤，补进原槽即可。",
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
    scenario="这条不该收、又不能留待裁时用它收口（终态判断）。",
    example="撤一槽并写一句理由：回 slot/status/reason_code 与那一行 title。",
    example_code='lit.stage_withdraw(slot="s-0007", reason_code="withdrawn_by_reviewer", note="与本次主题无关")',
    tags=("lit", "stage", "withdraw"),
)
def _lit_stage_withdraw(ctx, slot, reason_code, note=""):
    """lit.stage_withdraw 的工具体。"""
    return _h_lit_stage_withdraw(ctx, slot, reason_code, note)


@tool(
    "lit.stage_reject",
    "审内容后拒收：落 `rejected` + 受控理由码 + 一句说明；行保留不物理删。"
    "一次可判拒多个槽位，无效的逐条点名。",
    {
        "type": "object",
        "properties": {
            "slot": {"type": "string", "minLength": 1, "maxLength": 40,
                     "description": "单槽形：判拒这一个槽位（与 slots 二选一）"},
            "slots": {"type": "array", "items": {"type": "string", "minLength": 1,
                                                 "maxLength": 40},
                      "minItems": 1, "maxItems": 200,
                      "description": "批量形：一次判拒这几个槽位（同一个理由码与说明）；"
                                     "逐条落盘，无效的进 refused[] 点名"},
            "reason_code": {"type": "string", "enum": list(S.CANDIDATE_REASON_CODES)},
            "note": {"type": "string", "maxLength": 400},
        },
        "required": ["reason_code"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("A",),
    # 2026-11-19（FIXBATCH ①）：批量形。单槽形那七格逐字不动（老读者照读）；
    # 批量形另给 slots / count / rejected[] / refused[]。为什么必须分开写：
    # 单槽形是"一次判决一份回执"，批量形是"逐条判决 + 逐条点名"，两者的键不能混。
    returns=(
        "单槽形（给 slot）：{'slot','status','reason_code','reason','title','request_id','batch'}；"
        "批量形（给 slots）：{'slots','count','rejected','refused'}；"
        "slots[] 是这一次点名要判拒的槽位号；"
        "rejected[] 每项是 {'slot','status','reason_code','reason','title','request_id','batch'}"
        "（与单槽形同形）；"
        "refused[] 每项是 {'slot','why','code'}（无效 / 已判过的槽位在这里逐条点名，"
        "有效的那些照常落盘）；"
        "失败：ok=False + kind(no_store/bad_reason_code/unknown_slot/not_pending/no_target/"
        "all_refused/store_error) 之一 + 明细"
    ),
    scenario="读过正文、判定这篇不该收（跑题 / 低质 / 重叠）时。",
    example="批量判拒：rejected[] 逐条落盘，refused[] 点名无效槽。",
    example_code='lit.stage_reject(slots=["s-0003", "s-0004"], reason_code="rejected_off_topic", note="与立方体截面无关")',
    tags=("lit", "stage", "reject"),
)
def _lit_stage_reject(ctx, slot=None, reason_code="", note="", slots=None):
    """lit.stage_reject 的工具体。"""
    return _h_lit_stage_reject(ctx, slot, reason_code, note, slots)


@tool(
    "lit.admit",
    "正式入库（逐条）：每条要给 availability；候选行必须有 relevance"
    "（在 lit.stage_add 写，items 不收它）；单次 ≤10、单委托累计 ≤10，超限整笔拒。",
    {
        "type": "object",
        "properties": {
            "slots": {"type": "array", "items": {"type": "string", "maxLength": 40},
                      "minItems": 1, "maxItems": 200},
            "items": {"type": "array", "minItems": 1, "maxItems": 200,
                      "items": _LIT_PARAMS_ADMIT_ITEM,
                      "description": "逐条带 availability（可读性判定，必给）与 "
                                     "new_content / overlap_ok（优先于调用级参数）"},
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
        "refused[] / cleared[] 每项是 {'slot','title','why','code','overlap'}"
        "（`cleared[]` 是「没进去的那几条」这个读数格，不是状态名）；"
        "report 是 {'path','rel_path','chars','admitted','not_admitted','request_id'}；"
        "失败：ok=False + kind(no_store/over_cap_call/over_cap_delegation/unknown_slot/"
        "no_target/no_readback/missing_availability/availability_not_admissible/"
        "bad_availability/availability_ledger) + 读数"
    ),
    scenario="待审列表里的一条已判收，逐条放行用它；整批走 lit.admit_all。",
    example="放行一槽（带 availability）：回 admitted[] 的 lit_id 与 refused[]。",
    example_code=(
        'lit.admit(slots=["s-0007"], items=[{"slot": "s-0007", "availability": "readable", '
        '"new_content": "截面体积的新上界"}])'
    ),
    tags=("lit", "admit"),
)
def _lit_admit(ctx, slots=None, items=None, request_id=None, batch=None, new_content="",
               overlap_ok=None):
    """lit.admit 的工具体。"""
    return _h_lit_admit(ctx, slots, items, request_id, batch, new_content, overlap_ok)


@tool(
    "lit.admit_all",
    "提交一批：批内有一条没判完就整批不入库（逐条点名做法）；通过的批量登记、"
    "写报告并清掉本批，未点名的槽保持待裁进下一批。",
    {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "maxLength": 40,
                           "description": "哪一次委托（不给 = 当前委托）"},
            "slots": {"type": "array", "items": {"type": "string", "maxLength": 40},
                      "minItems": 1, "maxItems": 200,
                      "description": "这一次提交覆盖哪些槽（默认=本委托已判定的全部）；"
                                     "批内必须每一条都判过"},
            "new_content": {"type": "string", "maxLength": 2000,
                            "description": "本委托统一的「要的新内容」（逐条优先）"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("A",),
    # 2026-11-17（FX3·甲）：提交粒度从整委托改成批次 ⇒ `admitted[]` 不再恒空，元素形状
    # 要在这里说清（与 `lit.admit` 同形）；新增 `submitted` / `pending_total` /
    # `pending_by_delegation` / `pending_scope_note` 四格，供 A 读"这一批交了哪些、还剩
    # 哪些 pending 要进下一批"。
    returns=(
        "{'ok','kind','whole_call_refused','reason','request_id','submitted','call_size',"
        "'call_limit','delegation_admitted','delegation_limit','pending_total',"
        "'pending_by_delegation','pending_scope_note','admitted','refused','cleared',"
        "'registered','relocations','report','report_path'}；"
        "submitted[] 是这一次提交覆盖的槽位号；"
        "relocations[] 是原件搬迁的逐条回执（status 取自 `locallib.RELOCATE_*`；"
        "from/to 是 library/ 相对名；另有 slot、lit_id、sha256、bytes）；"
        "admitted[] 每项是槽位、题名、lit_id、created、overlap_score、overlap_kind、"
        "overlap_with、new_content 八格（与 lit.admit 同形）；"
        "refused[] 与 cleared[] 每项是槽位、题名、why、code、overlap 五格"
        "（`cleared[]` 是「没进去的那几条」这个读数格，不是状态名）；"
        "pending_total / pending_by_delegation / pending_scope_note 是这一批之后的全表"
        "待裁读数（没点名的未判槽仍在里面，A 照它进下一批）；"
        "report 是 {'path','rel_path','chars','admitted','not_admitted','request_id'}；"
        "失败：ok=False + kind(no_store/no_delegation/bad_delegation/store_error/"
        "unknown_slot/undecided_items/nothing_to_submit/no_readback/"
        "missing_availability/availability_not_admissible/report_violations)"
    ),
    scenario="一批判完就整体提交入库并出报告；剩下的 pending 进下一批。",
    example="提交本批：回 admitted[]/pending_total 与报告 work/A/lit-<r>.md（reports/ 已退役）。",
    example_code='lit.admit_all(request_id="r-NNNNNN", slots=["s-0001", "s-0002"])',
    tags=("lit", "admit", "report"),
)
def _lit_admit_all(ctx, request_id=None, new_content="", slots=None):
    """lit.admit_all 的工具体。"""
    return _h_lit_admit_all(ctx, request_id, new_content, slots)


#: 装配清单（`T-8`）：`(工具体函数, 需要从装配期注入的名字)`。
_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (_search_providers, ('ctx',)),
    (_search_shelf, ('ctx',)),
    (_search_local, ('ctx',)),
    (_search_download, ('ctx',)),
    (_search_dedup_check, ('ctx',)),
    # 阶段 ③ 第 2B 步：批量重取「有元数据、没全文」的行（写盘 + 出网，只有 A 拿得到）。
    (_search_retry_pending, ('ctx',)),
    (_search_ingest_local, ('ctx',)),
    (_search_register, ('ctx',)),
    # ---- 待新增文献列表（业主 2026-10-20 口径）：按委托暂存 → 审 → 提交整批 → 报告 ----
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
    actor: str = "",
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
        bound_actor=actor,
    )
    for prov in providers or []:
        name = (getattr(prov, "name", None) or type(prov).__name__).lower()
        ctx.providers[name] = prov

    provider_enum = _known_names(ctx)

    specs= [
        ToolSpec(
            name="search.literature",
            # TOOLFACE-SHARD3（片 3）：`dedup_key` / `is_new` 是返回键（模型要读），不是实现；
            # 判重真身 `dedup.find_existing_literature` 只在 handler 注释里出现。
            summary="按 topic/mode 检索文献候选，每条已带判重结论（is_new），不必再跑判重；"
            "mode=precise 必须给 description。",
            scenario="扩库的起点：还没有这篇文献的任何线索时，用它广搜或按描述精检。",
            example="广搜一个主题：回 candidates[] 与 new/existing/unknown 三个计数。",
            example_code='search.literature(topic="cube slicing", mode="topical", limit=10)',
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
                "'cited_by_count','topic_selfcheck'}；"
                "topic_selfcheck 是 broad 的主题自检 {'state','note'}"
                "（state ∈ related/off_topic/unknown；**unknown 是机器判不了、不是跑题**；"
                "非 broad 模式为 null）；"
                "sources[] 每项是 {'name','status','count','error_kind','error','delivered','refused'}；"
                "cost 是 {'provider_calls','elapsed_s'}"
            ),
            tags=("search", "literature"),
        ),
        ToolSpec(
            name="search.walk_citations",
            summary="由一篇**已登记**的文献走一步引文图：backward 是它引了谁、forward 是谁引了它；"
            "候选不带判重标注，登记前先 search.dedup_check。",
            scenario="手上已有一篇、想顺藤摸瓜找它引的或被引的文献。",
            example="走一步回溯：回 candidates[]（只含书目）与 count；lit_id 不在表里会明说。",
            example_code='search.walk_citations(lit_id="0007", direction="backward", limit=20)',
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

    全部落在 ``tempfile`` 临时工作区里，不碰 test/test1/data 或仓库里的任何工作区。
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
    src.write_text("An abelian group is a group in which the commutative law holds.", encoding="utf-8", newline="\n")
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

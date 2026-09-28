"""下载层：流式下载、原子落盘、限速重试、镜像回退与安全检查。

设计约束（见 ``DESIGN.md`` §4.1）：

* 顶层不 import 兄弟模块，保证本模块可单独导入测试。
* 只依赖标准库 ``urllib``：下载是"一进一出"的大字节流，引入第三方 HTTP 库
  并不能带来收益，却让离线可运行性变差。
* 安全底线（FilePolicy 之外的内容安全）：
  - 只允许 ``http``/``https``，显式拒绝 ``file://`` 与其它 scheme；
  - 文件名 slug 化 + 扩展名推断，杜绝路径穿越（最终路径 resolve 后必须仍在 dest_dir 内）；
  - 单文件大小上限，避免被一个超大响应打爆磁盘。

关于"下到非 PDF 内容"：本机 hosts 把 ``github.com`` 系域名劫持到 127.0.0.1，
被劫持的请求可能返回一个看似 200 的 HTML 页面。这类情况不当作失败——
沙箱/代理还可能返回合法的 HTML 快照——而是写进 ``FetchResult.error`` 作为
``content_type_mismatch`` 交给上层（§5.2 的下载失败处理）决定。
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import logging
import mimetypes
import os
import random
import re
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

__all__ = [
    "FetchResult",
    "Downloader",
    "DownloadError",
    "HttpDownloader",
    "default_downloader",
    "slugify",
    "infer_extension",
    "DEFAULT_MIRRORS",
    "DEFAULT_USER_AGENT",
    "ERROR_KINDS",
    "is_controlled_error_kind",
    "RETRYABLE_STATUS",
]

logger = logging.getLogger(__name__)

#: 默认礼貌标识；调用方可通过配置覆盖（如加入真实联系邮箱）。
DEFAULT_USER_AGENT = "agentflow/0.1 (research prototype; contact: local)"

#: 默认单文件上限 200 MB。学术 PDF 极少超过这个量级，超过多半是被劫持/扫到了别的东西。
DEFAULT_MAX_BYTES = 200 * 1024 * 1024

#: 分块大小：兼顾内存占用与系统调用次数。
DEFAULT_CHUNK_SIZE = 256 * 1024

#: 连接/读取超时分开设置：连接慢通常意味着网络问题，读取慢可能只是文件大。
DEFAULT_CONNECT_TIMEOUT = 20.0
DEFAULT_READ_TIMEOUT = 120.0

#: 默认最小请求间隔（秒），与 providers 层一致。
DEFAULT_MIN_INTERVAL = 1.0

#: 默认重试次数（不含首次尝试）。
DEFAULT_RETRIES = 3

#: 需要重试的 HTTP 状态码。
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

#: `FetchResult.kind` 的受控词表（`F-6`）。
#:
#: 为什么需要它：改前失败原因是自由字符串（`dir(F)` 里只有 `DownloadError` /
#: `RETRYABLE_STATUS`），实测形态含 `dest_dir_unusable` / `too_large_declared` /
#: `write_failed` / `read_failed` / `all_sources_failed` / `http_<code>` /
#: `network_error: …` / `timeout: …` / `io_error: …` / `content_type_mismatch`。
#: 下游只有四值词表 `schema.DOWNLOAD_STATUSES = (ok, content_mismatch, failed,
#: skipped)`，于是"限流/被墙/解析失败/网络失败"全部折成同一个 `failed` ——
#: 按那条轴统计答不出来。
#:
#: 这些都是一次下载尝试为什么没成的原因档（`ok=False` 侧）；
#: 唯一的 `ok=True` 软警告是 `content_type_mismatch`（文件已完整落盘）。
#: `http_<code>` 是参数化形态：码在名字里，档仍是受控的（`http_` 前缀 + 三位数）。
ERROR_KINDS = (
    "empty_url",
    "unsupported_scheme",
    "missing_host",
    "blocked_host",
    "dest_dir_unusable",
    "too_large_declared",
    "too_large_stream",
    "write_failed",
    "read_failed",
    "empty_body",
    "network_error",
    "timeout",
    "io_error",
    "all_sources_failed",
    "not_attempted",
    "fixture_missing",
    "non_fixture_url",
    "content_type_mismatch",
    "unknown_error",
)

#: 受控档的判定：`ERROR_KINDS` 之一，或 `http_<三位数>`。
_ERROR_KIND_RE = re.compile(r"^http_\d{3}$")


def is_controlled_error_kind(kind: str | None) -> bool:
    """`kind` 是不是受控档（`ERROR_KINDS` 之一或 `http_NNN`）。

    `None` 也算合法：成功且无警告时它就该是空的。
    """
    if kind is None:
        return True
    return kind in ERROR_KINDS or bool(_ERROR_KIND_RE.match(kind))

#: 认定为"是文档"的扩展名，用于 Content-Type 与 URL 后缀的一致性检查。
DOCUMENT_EXTENSIONS = frozenset(
    {".pdf", ".txt", ".md", ".markdown", ".html", ".htm", ".xml", ".json", ".csv", ".tex", ".rtf", ".epub"}
)

#: 本机 hosts 把 github 系域名劫持到 127.0.0.1；默认用 gh-proxy 前缀绕行（可配置关闭）。
GITHUB_HOST_PATTERN = "*.github.com,github.com,*.githubusercontent.com,raw.githubusercontent.com,*.github.io"
GH_PROXY_PREFIX = "https://gh-proxy.com/"

#: 默认镜像规则。每条规则要么是纯前缀替换，要么是"prepend"式代理；
#: 带 ``hosts`` 时只对匹配的 URL 生效，避免对非 GitHub 链接做无谓的失败尝试。
DEFAULT_MIRRORS: tuple[dict[str, Any], ...] = (
    {"hosts": GITHUB_HOST_PATTERN, "prepend": GH_PROXY_PREFIX, "name": "gh-proxy"},
)


class DownloadError(RuntimeError):
    """下载层统一异常类型。"""


# --------------------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class FetchResult:
    """一次下载的结果。字段与 ``DESIGN.md`` §4.1 一致。

    ``error`` 有两种语义，调用方必须都理解：
    * 真失败（``ok=False``）：``error`` 是失败原因，``path`` 为 None；
    * 软警告（``ok=True``）：文件已完整落盘，``error`` 是如 ``content_type_mismatch``
      的提示，交由上层判断是否可用（§5.2 允许"登记行但内容可疑"）。

    ## ``kind`` 是受控的那一半（`F-6`）

    ``error`` 保留自由文本（给人读的细节，含异常消息），``kind`` 是
    :data:`ERROR_KINDS` 里的受控档（给统计读的）。为什么两列都要：
    只留自由文本则"按失败原因统计"不成立（`http_429` 与 `network_error: ...`
    是同一列里两种形态）；只留受控档则丢掉了排障需要的原文。
    分列之后，"限流 / 被墙 / 解析失败 / 网络失败"这条轴可以直接数出来。

    ``kind`` 与 ``ok`` 的关系是单向的：`ok=True` 时 ``kind`` 要么是 `None`
    （干净成功），要么是 `content_type_mismatch`（落盘成功、内容可疑）；
    `ok=False` 时 ``kind`` 一定不是 `None`。这条由 :func:`is_controlled_error_kind`
    与 ``tests`` 守住 —— 一个失败的下载没有受控原因，就等于没说为什么失败。
    """

    ok: bool = False
    path: str | None = None
    http_status: int | None = None
    bytes: int = 0
    sha256: str | None = None
    error: str | None = None
    #: 受控的失败/警告档（`ERROR_KINDS` 或 `http_NNN`）。见类 docstring。
    kind: str | None = None

    def __post_init__(self) -> None:
        """把"失败的下载必须带上受控原因"变成构造期的硬约束（`F-6`）。

        为什么不能只在 `HttpDownloader` 里记得填：`FetchResult` 是下载层的
        公共返回类型，任何下载器实现（`demo.FixtureDownloader`、测试里的假下载器）
        都能造它。判据落在类型自己身上，才不依赖"每个实现都记得"。
        这条约束没有例外：第一版把 `http_status is None` 当例外，于是
        `demo.FixtureDownloader` 的两条失败路径合法地不带档 —— 那正是
        "合约改了、调用方没跟"的口子。`F-6` 的判据是"失败的下载必须答得出
        为什么"，没有"连 HTTP 层都没到就不算失败"的道理。
        """
        if not is_controlled_error_kind(self.kind):
            raise ValueError(
                f"FetchResult.kind={self.kind!r} 不是受控档（ERROR_KINDS 之一或 http_NNN）"
            )
        if not self.ok and self.kind is None:
            raise ValueError(
                "失败的下载必须给出受控的 kind（F-6）：只有自由文本的 error 时，"
                "『限流/被墙/解析失败/网络失败』这条轴统计不出来 —— "
                "上游只有 schema.DOWNLOAD_STATUSES 四值，六种原因会全折成 failed"
            )
        if self.ok and self.kind not in (None, "content_type_mismatch"):
            raise ValueError(
                f"ok=True 时 kind 只能是 None 或 content_type_mismatch，收到 {self.kind!r} —— "
                "成功的下载不该带失败档"
            )


class Downloader(Protocol):
    """下载器协议。"""

    def download(
        self, url: str, dest_dir: Path, filename_hint: str
    ) -> FetchResult:  # pragma: no cover - 协议声明
        ...


# --------------------------------------------------------------------------------------
# 文件名与扩展名
# --------------------------------------------------------------------------------------


def _url_suffix(url: str) -> str:
    """取 URL 路径后缀（如 ``.pdf``），用于与 Content-Type 做一致性检查。"""
    path = urllib.parse.urlparse(url).path
    suffix = Path(urllib.parse.unquote(path)).suffix.lower()
    return suffix if len(suffix) <= 6 else ""


def slugify(text: str, max_length: int = 80) -> str:
    """文件名片段的 slug 化 —— 转发到唯一实现 :func:`agentflow.textutil.slugify`。

    ## 为什么这里是转发而不是第二份实现（``INVENTORY.md`` §4.7②）

    本函数曾经自带一套规则：``[^a-z0-9]+`` ⇒ 把 CJK 一并当分隔符剥掉，
    空结果回退 ``"download"``。而 ``textutil.slugify`` 保留 CJK、回退
    ``"untitled"``。同名不同契约的直接后果是同一个标题在两条生产路径上
    得到不同文件名：``agent_a.py:279`` 用 ``T.slugify`` 造下载提示名，
    本模块（``fetch.py:676/680``）又用自己的规则重新削一遍 ——
    ``'On the Structure of Groups 群论'`` 在提示名里带 ``-群论``，
    落盘时却变成 ``on-the-structure-of-groups``，中文标题整块消失。
    两份判据必然漂移，而漂移在这里是静默的（只是文件名不同，没有任何报错）。

    ## 合并后唯一的规则（理由写在 ``textutil.slugify`` 的 docstring 里）

    保留 CJK 基本区、白名单过滤、空结果回退 ``"untitled"``。这里只保留
    一个调用点特有的默认值：``max_length=80``（下载文件名比内部 slug
    可以长一点）。它由参数表达，不再是第二套逻辑。

    ## 为什么用惰性 import

    本模块的模块 docstring 第 5 行立了一条约束："顶层不 import 兄弟模块，
    保证本模块可单独导入测试"。``textutil`` 反过来 import 本模块，顶层 import
    会构成模块级循环。惰性 import 同时满足两边：约束不被打破，判据也不重复。
    """
    from . import textutil as _textutil  # 惰性 import：见上面 docstring 第 3 节
    return _textutil.slugify(text, limit=max_length)


def infer_extension(url: str, content_type: str | None = None) -> str:
    """按 Content-Type 优先、URL 后缀兜底推断扩展名，全部小写且带点。

    优先 Content-Type 是因为 URL 后缀常撒谎（``/download?id=1``）；
    但 ``application/octet-stream`` 这类没有信息量的类型必须让位给 URL 后缀。
    """
    ctype = (content_type or "").split(";")[0].strip().lower()
    generic = {"", "application/octet-stream", "binary/octet-stream", "application/force-download"}

    mapping = {
        "application/pdf": ".pdf",
        "application/x-pdf": ".pdf",
        "text/plain": ".txt",
        "text/markdown": ".md",
        "text/html": ".html",
        "application/xhtml+xml": ".html",
        "text/xml": ".xml",
        "application/xml": ".xml",
        "application/json": ".json",
        "text/csv": ".csv",
        "application/epub+zip": ".epub",
        "application/rtf": ".rtf",
        "application/x-tex": ".tex",
    }
    if ctype in mapping:
        return mapping[ctype]
    if ctype.startswith("image/"):
        ext = mimetypes.guess_extension(ctype) or ".img"
        return ".jpg" if ext == ".jpe" else ext

    path = urllib.parse.urlparse(url).path
    suffix = Path(urllib.parse.unquote(path)).suffix.lower()
    # 只接受"看起来像文档"的后缀：`/article/2024.12` 的 ".12" 不是扩展名。
    if suffix in DOCUMENT_EXTENSIONS:
        return suffix
    if suffix and len(suffix) <= 5 and re.fullmatch(r"\.[a-z0-9]{1,4}", suffix):
        return suffix
    if ctype in generic or not ctype:
        return ".bin"
    guess = mimetypes.guess_extension(ctype) or ".bin"
    return ".jpg" if guess == ".jpe" else guess


def _url_host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def _strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


# --------------------------------------------------------------------------------------
# 限速与重试
# --------------------------------------------------------------------------------------


class _RateLimiter:
    """按主机串行化的最小间隔限速器（睡眠与时间戳更新在同一把锁内）。"""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def acquire(self, bucket: str) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            last = self._last.get(bucket)
            if last is not None:
                wait = self.min_interval - (now - last)
                if wait > 0:
                    time.sleep(wait)
                    now = time.monotonic()
            self._last[bucket] = now


#: 单个请求最多被上游 ``Retry-After`` 拖住的秒数。上游偶尔会给出很大的值
#: （几分钟），跟着它等会把整轮流水线挂死；宁可提前放弃让上层重试，也不占着线程睡。
MAX_RETRY_AFTER = 30.0


def _retry_after_seconds(headers: Any) -> float | None:
    try:
        raw = headers.get("Retry-After") if headers is not None else None
    except Exception:  # pragma: no cover
        return None
    if not raw:
        return None
    try:
        return min(float(str(raw).strip()), MAX_RETRY_AFTER)
    except ValueError:
        return None


def _backoff_delay(attempt: int) -> float:
    """指数退避 + 抖动。抖动是为了让并发下载在限流恢复后不要同时猛冲。"""
    return min(2.0 ** attempt, 30.0) * (0.8 + 0.4 * random.random())


class _ConnectThenReadHTTPConnection(http.client.HTTPConnection):
    """用 ``connect_timeout`` 建连、建连后把 socket 超时切到 ``read_timeout``。"""

    def __init__(self, host: str, connect_timeout: float, read_timeout: float, **kwargs: Any) -> None:
        super().__init__(host, timeout=read_timeout, **kwargs)
        self._agentflow_connect_timeout = connect_timeout

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self.host, self.port), self._agentflow_connect_timeout, self.source_address
        )
        self.sock.settimeout(self.timeout)


class _ConnectThenReadHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS 版本；``context`` 由 urlopen 传入，必须原样透传给 ``http.client``。"""

    def __init__(self, host: str, connect_timeout: float, read_timeout: float, **kwargs: Any) -> None:
        super().__init__(host, timeout=read_timeout, **kwargs)
        self._agentflow_connect_timeout = connect_timeout

    def connect(self) -> None:
        sock = socket.create_connection(
            (self.host, self.port), self._agentflow_connect_timeout, self.source_address
        )
        if self._tunnel_host:  # 代理隧道场景，沿用标准库的处理
            server_hostname = self._tunnel_host
        else:
            server_hostname = self.host
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)
        self.sock.settimeout(self.timeout)


def _split_timeout_opener(connect_timeout: float, read_timeout: float) -> urllib.request.OpenerDirector:
    """构造一个把连接/读取超时拆开的 opener。

    为什么必须自定义：``urlopen`` 只接受单个 timeout，而本机实测
    ``urlopen(..., timeout=(20, 120))`` 会在 ``socket.settimeout()`` 处抛
    ``TypeError: 'tuple' object cannot be interpreted as an integer``。
    连接慢往往意味着网络不可达（应快速失败），读取慢可能只是文件大，
    两者用同一个数字无法兼顾，所以在连接类层面把两者拆开。

    实现方式刻意"贴近标准库"：不重写 ``do_open`` 的请求构造逻辑（转发头、
    重定向、代理隧道都有历史细节），而是把它内部用的连接工厂换成自定义子类。
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler())

    def make_conn(http_class: type) -> Callable[..., Any]:
        def factory(host: str, **kwargs: Any) -> Any:
            kwargs.pop("timeout", None)   # 超时由自定义连接类接管
            return http_class(host, connect_timeout, read_timeout, **kwargs)

        return factory

    for handler in opener.handlers:
        if isinstance(handler, urllib.request.HTTPSHandler):
            handler.do_open = _bind_do_open(  # type: ignore[method-assign]
                handler, make_conn(_ConnectThenReadHTTPSConnection)
            )
        elif isinstance(handler, urllib.request.HTTPHandler):
            handler.do_open = _bind_do_open(  # type: ignore[method-assign]
                handler, make_conn(_ConnectThenReadHTTPConnection)
            )
    return opener


def _bind_do_open(handler: Any, factory: Callable[..., Any]) -> Callable[..., Any]:
    """把 ``AbstractHTTPHandler.do_open`` 绑到一个"用 factory 造连接"的版本上。

    这里必须复用标准库的 ``do_open``：它负责生成 ``Host``/转发头/处理重定向与
    代理隧道，这些细节手写极易漏（例如 HTTPS 的 ``context`` 必须原样透传）。
    """
    from urllib.request import AbstractHTTPHandler

    return lambda http_class, req, **_: AbstractHTTPHandler.do_open(handler, factory, req)


# --------------------------------------------------------------------------------------
# 镜像规则
# --------------------------------------------------------------------------------------


def _host_matches(host: str, patterns: Sequence[str]) -> bool:
    """极简 glob：只支持 ``*.example.com`` 与精确匹配，够用且无隐藏语义。"""
    host = _strip_www(host)
    for pattern in patterns:
        pat = _strip_www(pattern.strip().lower())
        if not pat:
            continue
        if pat.startswith("*."):
            suffix = pat[1:]                      # ".github.com"
            if host.endswith(suffix) or host == pat[2:]:
                return True
        elif host == pat:
            return True
    return False


def _normalize_mirrors(raw: Any) -> list[dict[str, Any]]:
    """把配置里的镜像规则统一成 dict 列表，容忍字符串简写。"""
    if raw is None:
        return [dict(m) for m in DEFAULT_MIRRORS]
    rules: list[dict[str, Any]] = []
    if isinstance(raw, (str, Mapping)):
        raw = [raw]
    for item in raw:
        if isinstance(item, str):
            item = {"prefix": item}
        if not isinstance(item, Mapping):
            logger.warning("忽略非法镜像规则：%r", item)
            continue
        rule = {k: v for k, v in item.items()}
        if not rule.get("prefix") and not rule.get("prepend") and not rule.get("template"):
            # 例如 {"hosts": "...", "name": "gh-proxy"} 这种只带名字的规则，按预设展开。
            if rule.get("name") == "gh-proxy":
                rule = {"hosts": GITHUB_HOST_PATTERN, "prepend": GH_PROXY_PREFIX, "name": "gh-proxy"}
            else:
                logger.warning("镜像规则缺少 prefix/prepend/template：%r", rule)
                continue
        rules.append(rule)
    return rules


def _apply_mirror(url: str, rule: Mapping[str, Any]) -> str | None:
    """按规则改写 URL；规则不适用则返回 None（调用方跳过该镜像）。"""
    hosts = rule.get("hosts")
    if hosts:
        patterns = hosts.split(",") if isinstance(hosts, str) else list(hosts)
        if not _host_matches(_url_host(url), patterns):
            return None

    template = rule.get("template")
    if template:
        # 模板式：允许把原始 URL 塞进任意位置（某些镜像要求 URL 编码后作查询参数）。
        encoded = urllib.parse.quote(url, safe="")
        return str(template).replace("{url}", url).replace("{url_encoded}", encoded)

    prepend = rule.get("prepend")
    if prepend:
        # prepend 式（如 gh-proxy）：代理把原 URL 直接接在域名后面。
        return f"{str(prepend).rstrip('/')}/{url}"

    prefix = rule.get("prefix")
    if prefix:
        # 前缀替换式：命中 ``match``（默认 http(s)://）的部分换成镜像前缀。
        match = str(rule.get("match") or "")
        if match:
            if not url.startswith(match):
                return None
            return f"{str(prefix)}{url[len(match):]}"
        return f"{str(prefix)}{url}"
    return None


# --------------------------------------------------------------------------------------
# HttpDownloader
# --------------------------------------------------------------------------------------


class HttpDownloader:
    """基于 ``urllib`` 的流式下载器。

    关键行为：

    1. 原子落盘：先写同目录临时文件，成功后 ``os.replace``。中途崩溃/超限时
       目标路径上不会留下半个文件——上层据 ``path`` 是否存在即可判断完整性。
    2. 流式：边读边写边算 sha256，内存占用与文件大小无关。
    3. 镜像回退：直连失败后依次尝试镜像；每个 URL 各自享有完整重试预算。
    4. 不覆盖已有文件：同名时追加短哈希后缀，避免两次下载互相踩踏。
       （改前这里写的是"``sha256`` 已在 `literature.download` 里承担『重复文件』
       判定的职责"—— 那句话与实现不符：全仓没有任何判重路径读
       `literature.download.sha256`，它只是"这份字节长这样"的证据。
       同族的两处声明修正见 `dedup` 模块 docstring 与登记册 `F-9`。）
    """

    def __init__(
        self,
        *,
        mirrors: Any = None,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        retries: int = DEFAULT_RETRIES,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        user_agent: str = DEFAULT_USER_AGENT,
        extra_headers: Mapping[str, str] | None = None,
        allow_private_hosts: bool = False,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.mirrors = _normalize_mirrors(mirrors)
        self.min_interval = max(0.0, float(min_interval))
        self.retries = max(0, int(retries))
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_bytes = max(1, int(max_bytes))
        self.chunk_size = max(1024, int(chunk_size))
        self.user_agent = user_agent
        self.extra_headers = dict(extra_headers or {})
        self.allow_private_hosts = bool(allow_private_hosts)
        self._opener = opener or _split_timeout_opener(self.connect_timeout, self.read_timeout)
        self._sleep = sleep
        self._limiter = _RateLimiter(self.min_interval)
        #: 观测计数，自检与排障用。
        self.stats: dict[str, int] = {"attempts": 0, "mirror_used": 0, "failures": 0}

    # -- 对外接口 -----------------------------------------------------------------

    def download(self, url: str, dest_dir: Path, filename_hint: str = "") -> FetchResult:
        dest = Path(dest_dir)
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return FetchResult(
                ok=False, kind="dest_dir_unusable",
                error=f"dest_dir_unusable: {exc}",
            )

        rejected = self._validate_url(url)
        if rejected is not None:
            kind, detail = rejected
            return FetchResult(ok=False, kind=kind, error=detail)

        candidates = [url]
        for rule in self.mirrors:
            try:
                rewritten = _apply_mirror(url, rule)
            except Exception as exc:  # 配置错误不应让下载整体失败
                logger.warning("镜像规则应用失败：%r（%s）", rule, exc)
                continue
            if rewritten and rewritten not in candidates:
                candidates.append(rewritten)

        last_error: str | None = None
        last_kind: str | None = None
        last_status: int | None = None
        for index, candidate_url in enumerate(candidates):
            if index > 0:
                self.stats["mirror_used"] = self.stats.get("mirror_used", 0) + 1
                logger.info("直连失败，改用镜像：%s", candidate_url)
            result = self._download_via(candidate_url, dest, filename_hint)
            if result.ok or result.bytes > 0:
                return result
            last_error = result.error
            last_kind = result.kind
            last_status = result.http_status

        self.stats["failures"] = self.stats.get("failures", 0) + 1
        detail = f"all_sources_failed: {last_error}" if last_error else "all_sources_failed"
        if len(candidates) > 1:
            detail += f" (tried {len(candidates)} urls)"
        # `all_sources_failed` 是受控档，但"为什么全失败了"必须留在 `kind` 旁边的
        # `error` 里 —— 上游只看 `kind` 会以为所有失败同因，原档在 `last_kind`。
        return FetchResult(
            ok=False, kind="all_sources_failed", http_status=last_status,
            error=detail if last_kind is None else f"{detail} [last_kind={last_kind}]",
        )

    # -- 内部实现 -----------------------------------------------------------------

    def _validate_url(self, url: str) -> tuple[str, str] | None:
        """返回 `(受控档, 细节文本)` 表示不可下载；`None` 表示通过。

        为什么返回二元组而不是一个字符串、再由调用方去切前缀：改前调用方拿的是
        `"blocked_host: 127.0.0.1"` 这样一个串，要拿到受控档只能 `split(":")[0]`
        —— 那是"同一件事两个落位"的又一例（详情文本一改，档就静默变了）。
        """
        if not isinstance(url, str) or not url.strip():
            return "empty_url", "empty_url"
        parts = urllib.parse.urlsplit(url.strip())
        scheme = (parts.scheme or "").lower()
        if scheme not in ("http", "https"):
            # 显式挡掉 file:// 等本地读取途径：下载器只应接触网络。
            return "unsupported_scheme", f"unsupported_scheme: {scheme or 'none'}"
        host = (parts.hostname or "").lower()
        if not host:
            return "missing_host", "missing_host"
        if self.allow_private_hosts:
            return None
        if host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
            return "blocked_host", f"blocked_host: {host}"
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return None
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "blocked_host", f"blocked_host: {host}"
        return None

    def _open(self, request: urllib.request.Request, timeout: Any) -> Any:
        """统一调用入口：既接受 ``urlopen`` 风格（可调用），也接受 ``OpenerDirector``。

        ``_opener`` 是可注入点（测试常传假 opener），因此这里必须同时兼容两种
        调用协议；``OpenerDirector`` 提供了 ``.open``，而函数对象没有。
        """
        opener = self._opener
        open_method = getattr(opener, "open", None)
        if callable(open_method):
            return open_method(request, timeout=timeout)
        return opener(request, timeout=timeout)

    def _download_via(self, url: str, dest: Path, filename_hint: str) -> FetchResult:
        """对单个 URL 做"限速 + 重试"的完整下载。"""
        host = _url_host(url) or "unknown"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/pdf,text/html,application/xhtml+xml,text/plain,*/*;q=0.8",
            "Accept-Language": "en,zh-CN;q=0.8",
        }
        headers.update(self.extra_headers)

        timeout = (self.connect_timeout, self.read_timeout)
        last_status: int | None = None
        last_error: str | None = None
        last_kind: str = "unknown_error"

        for attempt in range(self.retries + 1):
            self._limiter.acquire(host)
            self.stats["attempts"] = self.stats.get("attempts", 0) + 1
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with self._open(request, timeout) as response:
                    status = getattr(response, "status", None) or response.getcode()
                    if status and status >= 400:
                        raise urllib.error.HTTPError(
                            url, status, f"HTTP {status}", response.headers, None
                        )
                    return self._consume(response, status, url, dest, filename_hint)
            except urllib.error.HTTPError as exc:
                last_status = int(getattr(exc, "code", 0) or 0)
                last_kind = f"http_{last_status}"
                last_error = last_kind
                if last_status not in RETRYABLE_STATUS or attempt >= self.retries:
                    break
                delay = _retry_after_seconds(getattr(exc, "headers", None)) or _backoff_delay(attempt)
                logger.warning("下载 %s 得到 HTTP %s，%.1fs 后重试（%d/%d）", url, last_status, delay, attempt + 1, self.retries)
                self._sleep(delay)
            except urllib.error.URLError as exc:
                last_kind = "network_error"
                last_error = f"network_error: {exc.reason}"
                if attempt >= self.retries:
                    break
                delay = _backoff_delay(attempt)
                logger.warning("下载 %s 网络异常（%s），%.1fs 后重试（%d/%d）", url, exc.reason, delay, attempt + 1, self.retries)
                self._sleep(delay)
            except OSError as exc:
                # TimeoutError 是 OSError 的子类（socket.timeout 自 3.10 起即其别名）。
                # 断流/超时是瞬时故障——实测 AMS 的大 PDF 会在传到几百 KB 时读超时，
                # 重试一次往往就能读完，所以必须重试；而 ENOSPC/EACCES 这类本地 I/O
                # 错误重试无用，立即失败更快把问题暴露给上层。
                #
                # `F-6` 的归因修正：`ConnectionResetError` 也是 `OSError` 的子类，
                # 而改前它落在"非 TimeoutError ⇒ io_error"那一支里 ——
                # 于是一次网络中途断流被记成 `io_error`（读账的人会去查磁盘）。
                is_transient = isinstance(exc, TimeoutError)
                if is_transient:
                    last_kind, last_error = "timeout", f"timeout: {exc}"
                elif isinstance(exc, ConnectionError):
                    # 被墙/被重置/连接断开：这是网络轴上的事，不是本地 I/O。
                    # 与 `timeout` 同样重试（下一跳或镜像往往能过）。
                    is_transient = True
                    last_kind, last_error = "network_error", f"network_error: {exc}"
                else:
                    last_kind, last_error = "io_error", f"io_error: {exc}"
                if not is_transient or attempt >= self.retries:
                    break
                delay = _backoff_delay(attempt)
                logger.warning(
                    "%s %s（%s），%.1fs 后重试（%d/%d）",
                    {"timeout": "下载超时", "network_error": "下载连接中断"}.get(
                        last_kind, "下载 I/O 失败"
                    ),
                    url,
                    exc,
                    delay,
                    attempt + 1,
                    self.retries,
                )
                self._sleep(delay)

        return FetchResult(
            ok=False, kind=last_kind, http_status=last_status,
            error=last_error or "unknown_error",
        )

    def _consume(
        self,
        response: Any,
        status: int | None,
        url: str,
        dest: Path,
        filename_hint: str,
    ) -> FetchResult:
        """流式落盘。任何异常都转成 ``FetchResult(ok=False)``，绝不向上抛。

        0 字节也是"没拿到内容"（`F-5`，见下面 `written == 0` 那一段）：
        "下载成功"必须同时意味着"内容确实存在"，否则 `ok` 会同时表示两件事。

        ## 落盘的 `kind` 归因（`F-6`）

        改前这里只有一个 `except OSError` 兜住写文件与读响应两件事，
        于是一次"读到一半连接被重置"（`ConnectionResetError`，`OSError` 子类）
        被归成 `write_failed` —— 读账的人会去查磁盘，而问题在网络。
        现在的结构是：`response.read()` 在内层 try 里单独兜，
        `read_failed` 只可能来自读；外层 `except OSError` 只可能是落盘失败。
        """
        headers = getattr(response, "headers", None)
        content_type = ""
        if headers is not None and headers.get("Content-Type"):
            content_type = str(headers.get("Content-Type"))
        declared = None
        if headers is not None and headers.get("Content-Length"):
            try:
                declared = int(str(headers.get("Content-Length")).strip())
            except ValueError:
                declared = None
        if declared is not None and declared > self.max_bytes:
            return FetchResult(
                ok=False,
                kind="too_large_declared",
                http_status=status,
                bytes=0,
                error=f"too_large_declared: {declared} > {self.max_bytes}",
            )

        extension = infer_extension(url, content_type)
        target = self._target_path(dest, filename_hint, url, extension)

        temp_path: str | None = None
        written = 0
        digest = hashlib.sha256()
        try:
            fd, temp_path = tempfile.mkstemp(prefix=".agentflow-", suffix=".part", dir=str(dest))
            with os.fdopen(fd, "wb") as handle:
                while True:
                    # 读响应单独兜：这里的异常是网络的事，不是磁盘的事。
                    try:
                        chunk = response.read(self.chunk_size)
                    except Exception as exc:
                        self._cleanup(temp_path)
                        return FetchResult(
                            ok=False, kind="read_failed", http_status=status, bytes=written,
                            error=f"read_failed: {type(exc).__name__}: {exc}",
                        )
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > self.max_bytes:
                        raise DownloadError(f"too_large_stream: > {self.max_bytes} bytes")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
            temp_path = None
        except DownloadError as exc:
            # 只有 `too_large_stream` 会走到这里：上限是本地判据，不是写失败。
            self._cleanup(temp_path)
            return FetchResult(
                ok=False, kind="too_large_stream", http_status=status,
                bytes=written, error=str(exc),
            )
        except OSError as exc:
            # 走到这里只剩下"落盘"这一类（读已经在上面单独兜住了）。
            self._cleanup(temp_path)
            return FetchResult(
                ok=False, kind="write_failed", http_status=status, bytes=written,
                error=f"write_failed: {type(exc).__name__}: {exc}",
            )

        if written == 0:
            # `F-5`：0 字节的 200 响应不是"下载成功"。
            #
            # 缺陷（2026-09-26 全面体检 · 子代理 F 实测，`temp/auditF-probe3.txt` [L] 段）：
            # 改前 `written` 不参与成功判定，于是"这个 URL 什么都没给"落成一个空文件 +
            # 空串的 sha256 + `ok=True`；`agent_a._stage_download` 按 `res.ok` 记
            # `download.status='ok'`，B 随后把它抽成 `pages=[]`，结论链变成
            # "下载成功 + 扫描件需要 OCR"。`schema.DOWNLOAD_STATUSES` 的 `ok` 从此
            # 不再等于"内容确实拿到了"。
            #
            # 处置：把刚落下去的那个空文件删掉（`_target_path` 保证 `target` 此前不存在，
            # 所以这里删掉的必然是本次刚写的那个），并按"没拿到内容"返回。
            # 刻意不复用 `ok`：一个"合法的 0 字节文件"如果真需要，应当另设受控取值，
            # 而不是让 `ok` 同时表示两件事。
            try:
                target.unlink()
            except OSError:
                # 删不掉也不许把"没拿到内容"翻回成功：文件残留只是脏，谎报成功是错。
                pass
            return FetchResult(
                ok=False,
                kind="empty_body",
                http_status=status,
                bytes=0,
                error="empty_body: 上游返回 0 字节 ⇒ 本次没有拿到任何内容",
            )

        warning = _content_type_warning(content_type, extension, _url_suffix(url))
        return FetchResult(
            ok=True,
            path=str(target),
            http_status=status,
            bytes=written,
            sha256=digest.hexdigest(),
            error=warning,
            # 软警告（`ok=True`）时 `kind` 说的是"内容可疑"这一类；
            # 没有警告时是 `None`（干净成功）—— 与 `ok=False` 侧的失败档同属一张词表。
            kind="content_type_mismatch" if warning else None,
        )

    def _target_path(self, dest: Path, filename_hint: str, url: str, extension: str) -> Path:
        """生成并校验落盘路径：必须在 ``dest`` 之内，且不与已有文件冲突。

        回退链（三级，每一级都可观测，不是"悄悄变成占位名"）：
        ``filename_hint`` → URL 最后一段 → ``"untitled"``。
        判据"这个 hint 是不是空的"直接问 ``slugify``，而不是拿它的输出
        去比较一个魔法字符串（旧实现比较 ``hint == "download"``：那条判据
        与 ``slugify`` 的默认回退值耦合，合并判据后就会静默失效）。
        """
        hint = slugify(filename_hint) if filename_hint else ""
        if not hint or hint == "untitled":
            # 没有可读标题时退回 URL 的最后一段，好歹能看出来源。
            tail = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).stem
            hint = slugify(tail) if tail else "untitled"

        base = f"{hint}{extension}"
        candidate = _safe_join(dest, base)
        if not candidate.exists():
            return candidate

        # 已存在：加短哈希后缀（取自 URL），既不覆盖又能稳定复现。
        tag = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        candidate = _safe_join(dest, f"{hint}-{tag}{extension}")
        index = 2
        while candidate.exists():
            candidate = _safe_join(dest, f"{hint}-{tag}-{index}{extension}")
            index += 1
        return candidate

    @staticmethod
    def _cleanup(temp_path: str | None) -> None:
        if not temp_path:
            return
        try:
            os.unlink(temp_path)
        except OSError:
            logger.debug("临时文件清理失败（可忽略）：%s", temp_path)


def _safe_join(dest: Path, name: str) -> Path:
    """拼路径并断言结果在 ``dest`` 内，双保险挡路径穿越。

    ``name`` 已经过 ``slugify``，理论上不含分隔符；但"防路径穿越"是安全要求，
    必须由结构性检查而非"上游一定干净"的假设来保证（§4.1 明确要求 resolve 校验）。
    """
    dest_resolved = dest.resolve()
    candidate = (dest / name)
    resolved = candidate.resolve()
    if resolved != dest_resolved and dest_resolved not in resolved.parents:
        raise DownloadError(f"path_escape_detected: {name!r} -> {resolved}")
    return candidate


def _content_type_warning(
    content_type: str, extension: str, url_extension: str | None = None
) -> str | None:
    """判断实际内容是否与预期文档类型不符，返回软警告串或 None。

    这里刻意不把 ``text/html`` 本身当成问题——沙箱/代理可能返回合法的 HTML
    快照。真正值得报警的是"URL 自称 PDF，内容却是网页"（本机 hosts 劫持
    github 系域名后正是这种表现，AMSNet 等站点也会用 HTML 落地页假装 PDF 直链），
    因此判据是"URL 后缀 vs 实际 Content-Type"的一致性，而不是单一 Content-Type。
    """
    ctype = (content_type or "").split(";")[0].strip().lower()
    expected = (url_extension or "").lower()
    is_html = ctype in ("text/html", "application/xhtml+xml")
    looks_pdf_url = expected == ".pdf"
    looks_text_url = expected in (".txt", ".md", ".markdown", ".tex", ".csv", ".json", ".xml")

    if not ctype:
        # 无 Content-Type 时不做判断：不该用猜测去否定一个已经完整落盘的文件。
        return None
    if is_html and (looks_pdf_url or looks_text_url):
        return (
            f"content_type_mismatch: {ctype} (URL 期望 {expected}；"
            "可能被代理/劫持或链接并非直链)"
        )
    if ctype in ("application/pdf", "application/x-pdf") or ctype.startswith("image/"):
        return None
    if ctype.startswith("text/") or ctype in ("application/json", "application/xml", "application/xhtml+xml"):
        return None
    if ctype in ("application/octet-stream", "binary/octet-stream", "application/epub+zip"):
        return None
    if ctype == "application/zip" and extension in (".epub", ".zip"):
        return None
    return (
        f"content_type_mismatch: {ctype}"
        f" (saved as {extension}; 可能被代理/劫持或链接并非直链)"
    )


# --------------------------------------------------------------------------------------
# 工厂
# --------------------------------------------------------------------------------------


def default_downloader(config: Mapping[str, Any] | None = None) -> HttpDownloader:
    """按配置构造 ``HttpDownloader``。

    只透传认识的键，其它键（如 ``library_root``）安静忽略：配置文件是全项目共用的，
    下载器不应因为多了个别人的键就起不来。

    常用键：``mirrors``（list/dict/str，None 表示用默认规则）、``use_github_proxy``
    （bool，默认 True，本机 github 被劫持故默认开启）、``min_interval``、``retries``、
    ``connect_timeout``/``read_timeout``（亦接受 ``timeout_connect``/``timeout_read``）、
    ``max_bytes``、``chunk_size``、``user_agent``、``allow_private_hosts``。
    """
    cfg = dict(config or {})

    mirrors = cfg.get("mirrors", None)
    use_proxy = cfg.get("use_github_proxy", True)
    if mirrors is None and not use_proxy:
        # 显式关闭代理时必须清空默认规则，否则"可配置的默认镜像"就变成了强制。
        mirrors = []
    elif mirrors is not None and not use_proxy:
        mirrors = [m for m in _normalize_mirrors(mirrors) if m.get("name") != "gh-proxy"]

    def pick(*names: str, default: Any) -> Any:
        for name in names:
            if name in cfg and cfg[name] is not None:
                return cfg[name]
        return default

    kwargs: dict[str, Any] = {
        "mirrors": mirrors,
        # 同时接受带 _seconds 后缀的写法：config.yaml 用的是 min_interval_seconds，
        # 两个名字指同一件事时必须都认，否则用户改了配置却毫无效果（静默失效）。
        "min_interval": pick("min_interval", "min_interval_seconds", default=DEFAULT_MIN_INTERVAL),
        "retries": pick("retries", "max_retries", default=DEFAULT_RETRIES),
        "connect_timeout": pick(
            "connect_timeout", "timeout_connect", "connect_timeout_seconds",
            default=DEFAULT_CONNECT_TIMEOUT,
        ),
        "read_timeout": pick(
            "read_timeout", "timeout_read", "read_timeout_seconds",
            default=DEFAULT_READ_TIMEOUT,
        ),
        "max_bytes": pick("max_bytes", "max_file_bytes", default=DEFAULT_MAX_BYTES),
        "chunk_size": pick("chunk_size", default=DEFAULT_CHUNK_SIZE),
        "user_agent": pick("user_agent", default=DEFAULT_USER_AGENT),
        "allow_private_hosts": pick("allow_private_hosts", default=False),
    }
    extra_headers = cfg.get("headers")
    if isinstance(extra_headers, Mapping):
        kwargs["extra_headers"] = extra_headers
    return HttpDownloader(**kwargs)


# --------------------------------------------------------------------------------------
# 自检：真实下载一个 OpenAlex 给出的开放获取 PDF
# --------------------------------------------------------------------------------------


def _selftest() -> int:
    """自检块：用 provider 给出的 pdf_url 真实下载一次，打印流程细节。"""
    import json
    import sys

    try:  # Windows 控制台默认 GBK，避免中文/特殊符号导致 UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("=" * 78)
    print("agentflow.fetch 自检：下载 OpenAlex 检索到的开放获取 PDF")
    print("=" * 78)

    try:
        from .providers import OpenAlexProvider  # 惰性 import：避免模块级循环依赖
    except ImportError:
        root = Path(__file__).resolve().parents[1]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from agentflow.providers import OpenAlexProvider  # type: ignore[no-redef]

    try:
        candidates = OpenAlexProvider(min_interval=1.0).search("abelian group", "topical", "", 5)
    except Exception as exc:
        print(f"[失败] 检索阶段异常，无法取得下载目标：{exc}")
        return 1

    pdf_url = next((c.pdf_url for c in candidates if c.pdf_url), None)
    print(f"候选数={len(candidates)}  选中 pdf_url={pdf_url}")
    if not pdf_url:
        print("[跳过] 本次候选中没有 pdf_url，未执行下载。")
        return 0

    downloader = default_downloader({"min_interval": 1.0})
    result: FetchResult = FetchResult(ok=False, kind="not_attempted", error="not_attempted")
    with tempfile.TemporaryDirectory(prefix="agentflow-fetch-selftest-") as tmp:
        result = downloader.download(pdf_url, Path(tmp), candidates[0].title)
        print(json.dumps(
            {
                "ok": result.ok,
                "http_status": result.http_status,
                "bytes": result.bytes,
                "sha256": (result.sha256 or "")[:16],
                "error": result.error,
                "path": result.path,
            },
            ensure_ascii=False,
            indent=2,
        ))
        if result.path and Path(result.path).exists():
            print(f"落盘复核：{Path(result.path).stat().st_size} 字节")
        print(f"stats={downloader.stats}")
    print("=" * 78)
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover - 手动自检入口
    raise SystemExit(_selftest())

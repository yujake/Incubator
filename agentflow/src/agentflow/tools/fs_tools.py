"""文件 CRUD 工具（A/B/C/D 共用），沙箱在工作区内。

## 这个文件的核心是路径安全，不是 CRUD

`read/write/move/delete` 这四件事本身都是三行代码。真正会让项目出事的是
"工具被 LLM 驱动"这件事本身：一个由模型生成的 `path` 参数，随时可能是
`../../etc/passwd`、`C:\\Windows\\win.ini`、`\\\\?\\GLOBALROOT\\...`、
一个指到工作区外的符号链接，或者 `NUL` / `CON` 这类设备路径（对它们做
"写文件"根本不是写文件）。所以本模块的顺序是：

1. 一切路径先过 `_resolve()`：拒绝绝对路径/盘符/UNC、拒绝设备名、
   拒绝非法字符 → 规范化 → `resolve()`（会展开符号链接）→ 强制仍在 `root` 内。
   任何一步不过就 `fail(...)`，绝不"尽力而为地读一下试试"。
2. 越界是失败，不是异常（模块 docstring 见 `base.py`）：调用方是智能体，
   它需要的是一句能读懂的拒绝理由，而不是被打断的循环。
3. 写入有量级上限（默认 5 MB / 次）：工具层是给 LLM 用的，
   一个"把 200 MB 日志塞进 content 参数"的调用只可能是一次事故，
   不可能是一次有意的操作。

## 为什么用 `resolve()` 做最终判据（而不是只看字符串里有没有 `..`）

字符串检查会被三件事绕过：Windows 的反斜杠、8.3 短名、以及符号链接
（`root/link -> C:\\Windows` 这个路径里一个 `..` 都没有）。
`Path.resolve()` 把这些一次抹平，然后 `relative_to(root)` 是唯一的、可验证的判据。
`..` 本身不被一刀切拒绝 —— 只要解析完仍在 `root` 内（如 `a/../b`）就是合法的。
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from functools import partial, wraps
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator, Mapping

from .. import fs_observation as OBS
from .base import ToolError, ToolRegistry, ToolResult, ToolSpec, fail, ok, tool

#: 与 `table_tools` 一致：文件 CRUD 对 A/B/C/D 全开。
TOOL_ROLES: tuple[str, ...] = ("A", "B", "C", "D")

#: 主控（M）的文件面（`draft/37` §38 用户 2026-10-02 裁定；§57 用户 2026-10-03 追加一件）：
#: 只读四件 + `fs.write` + `fs.edit`，逐工具给 —— 不是把 M 整组塞进 `TOOL_ROLES`。
#:
#: 为什么不整组注入：那样 M 会连 `fs.delete` / `fs.move` 一起拿到，而这两件都不可逆
#: （删了就没了、挪走就换了位置）。要的是"M 自己能看、自己能改该改的那一处、
#: 自己交报告"，不是"M 能删东西"。所以这份白名单就是 M 的文件面边界（判据按它守）。
#:
#: 为什么必须有（真机读数，`draft/37` §37）：那一趟 23 步里 15 步在猜"盘上到底有没有论文"，
#: 最后交不出报告 —— M 缺的不是判断力，是眼睛与笔。
#:
#: ## `fs.edit` 为什么后来补进来了（2026-10-03，`draft/37` §56 第八趟真机的死因）
#:
#: 第八趟主控知道该改哪三处、也找准了逐字文本，然后试图用 `fs.write` 把整份
#: 26 KB 的 `main.tex` 重写一遍 —— 它的回复被输出额度（8192 token）截断在字符串中间
#: （步 27 / 30 的 `text_len` 是 26110 / 26134，`tokens_out` 都是 8192），
#: 连续三次坏 JSON ⇒ `bad_json_limit`，整趟作废。也就是说：`fs.write` 单独不足以改大文件，
#: 而"整文件覆盖"这条路本来也是更危险的那一条。
#:
#: `fs.edit`（锚定替换：`old_string` → `new_string`，一次一处、不命中就拒）正好是这件事
#: 的正确工具：输出量与改动量成正比（改一句就给一句），而不是与文件大小成正比。
#: 它比 `fs.write` 更安全，所以"不可逆"那条理由在这里不适用；仍然不给的是
#: `fs.delete`（真删）与 `fs.move`（换位置）—— 那两件才是 §38 那句话真正要挡的。
CONDUCTOR_FS_TOOLS: tuple[str, ...] = ("fs.list", "fs.read", "fs.search", "fs.stat", "fs.write",
                                       "fs.edit")

#: 单次读的默认上限（字节）。默认值刻意偏小：多数调用只是想"看一眼开头"，
#: 真需要全文的场景（如引文复核）应该走 `extract.py` 的抽取链，而不是把原文灌进上下文。
READ_DEFAULT_BYTES = 200_000
#: 单次读/写的硬上限。超过它的请求会被夹到这个值并如实标注，而不是拒绝服务 ——
#: "少读一点并说清楚"比"什么都不给"对调用方更有用。
MAX_READ_BYTES = 5 * 1024 * 1024
#: 单次写的硬上限（字节）。
#:
#: ⚠️ 2026-10-15 业主裁定 D5：5 MB → 32 MB。理由不是"5 MB 太小"（模型的单次回复
#: 根本到不了 5 MB），而是**这一格曾经是错的工具用在错的场合时的挡箭牌**：
#: 第八趟主控想改 `main.tex` 里三处，却试图整文件重写 26 KB —— 真正卡住它的是
#: **输出额度**（8192 token 截在字符串中间 ⇒ 三次坏 JSON ⇒ 整趟作废），不是这一格。
#: 把这一格抬高到 32 MB，"内容过大"就回到它该有的语义：**挡住一次编程事故**
#: （比如把一个数组序列化成几千万字符塞进来），而不是挡住正常写作。
#: 大文件的正确改法仍然是 `fs.edit`（改动量与输出量成正比），下面那条拒绝报文里写清了。
MAX_WRITE_BYTES = 32 * 1024 * 1024

#: 二进制嗅探的采样长度。8 KB 足够覆盖任何有意义的文本头部。
SNIFF_BYTES = 8192
#: 控制字节占比超过它就判为二进制（见 `_looks_binary`）。
CTRL_RATIO_LIMIT = 0.02

#: `fs.search` 的边界。
SEARCH_LIMIT_MIN, SEARCH_LIMIT_MAX, SEARCH_LIMIT_DEFAULT = 1, 2000, 100
#: 内容搜索不读超大文件（它多半是日志/数据而非文本），跳过并如实计数。
SEARCH_MAX_FILE_BYTES = 20 * 1024 * 1024
#: 单次搜索最多遍历多少文件，防"在工作区根上跑一次正则"变成一次全盘扫描。
SEARCH_MAX_FILES = 20_000
#: 单行返回长度上限，防某行是一个 5 MB 的 base64 把返回体撑爆。
MAX_LINE_CHARS = 500

#: `fs.list` 的边界。
LIST_LIMIT_MIN, LIST_LIMIT_MAX, LIST_LIMIT_DEFAULT = 1, 5000, 200

#: 文本文件里合法出现的 C0 控制字节（\t \n \v \f \r 与 ESC）。
_TEXT_CTRL_OK = frozenset({0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1B})

#: Windows 保留设备名。必须拒绝：`NUL` 不是文件，写它是"扔掉"，
#: 读它得到空，而 `CON` 会挂住进程等输入 —— 对工具调用方来说是静默的行为漂移。
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", "clock$"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
)

#: Windows 文件名里非法的字符。`:` 尤其重要 —— `a:b` 在 NTFS 上是数据流，
#: 写它会生成一个"看不见的文件"，比报错糟糕得多。
_ILLEGAL_CHARS = frozenset('<>:"|?*')

#: 常见二进制扩展名。与 NUL 嗅探互补：有些二进制格式（老式压缩、加密容器）
#: 头部可能恰好没有 NUL，而扩展名是我们手上最便宜的先验。
_BINARY_SUFFIXES = frozenset(
    {
        ".pdf",
        ".zip",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".webp",
        ".ico",
        ".mp3",
        ".mp4",
        ".avi",
        ".mkv",
        ".wav",
        ".flac",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".pyc",
        ".pyo",
        ".class",
        ".o",
        ".a",
        ".bin",
        ".dat",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
    }
)


@dataclass(frozen=True)
class FsContext:
    """沙箱根 + 审计 actor。注册时绑定，handler 保持无状态。"""

    root: Path
    actor: str = "tool"

    def __post_init__(self) -> None:
        # 冻结 dataclass 里要规范化字段只能用 object.__setattr__。
        # 为什么必须 resolve：后续所有 `relative_to(self.root)` 都拿它当基准，
        # 若 root 本身含符号链接（如 %TEMP% 在某些机器上是链接），
        # 不展开就会把合法的子路径误判成越界。
        object.__setattr__(self, "root", Path(self.root).resolve())


# ---------------------------------------------------------------- 路径闸门


def _reject(raw: Any, why: str) -> ToolError:
    return ToolError(f"拒绝路径 {raw!r}：{why}")


def _resolve(ctx: FsContext, raw: Any) -> Path:
    """把工具参数解析成确定在沙箱内的绝对路径。任何可疑输入抛 `ToolError`。

    检查顺序即"越早越便宜"：先字符串（零 IO），再规范化，最后 resolve + 归属判定。
    """
    if not isinstance(raw, str):
        raise ToolError(f"path 必须是字符串，收到 {type(raw).__name__}")
    text = raw.strip()
    if not text:
        raise ToolError("path 不能为空；要表示工作区根请用 '.'")
    if "\x00" in text:
        raise _reject(raw, "含 NUL 字节（绝对不是合法路径名）")

    # 统一分隔符后再判断：否则 Windows 上 `..\\..\\x` 会绕过只看 `/` 的检查。
    norm = text.replace("\\", "/")
    if norm.startswith("/"):
        # 覆盖 POSIX 绝对路径 `/etc/passwd`、UNC `//server/share`、
        # 以及 Win32 设备命名空间 `//?/C:/...` 与 `//./PhysicalDrive0`。
        raise _reject(raw, "只接受工作区内的相对路径（绝对路径/UNC/设备命名空间一律拒绝）")
    if re.match(r"^[A-Za-z]:", norm):
        raise _reject(raw, "只接受相对路径（盘符路径会被解析到工作区之外）")

    parts: list[str] = []
    for part in norm.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            # 不在这里一刀切：`a/../b` 完全合法，最终判据是 resolve 后是否仍在 root 内。
            parts.append(part)
            continue
        if any(ch in _ILLEGAL_CHARS for ch in part):
            raise _reject(raw, f"路径段 {part!r} 含非法字符 {sorted(_ILLEGAL_CHARS)}")
        if part != part.rstrip(" ."):
            # Windows 会静默去掉结尾的空格与点，于是 "con.txt " 与 "con.txt" 是同一个
            # 文件 —— 这种"两个名字一个文件"的别名会让人工排查彻底失效，直接拒绝。
            raise _reject(raw, f"路径段 {part!r} 以空格或点结尾（Windows 会静默改名）")
        if part.split(".")[0].casefold() in _RESERVED_NAMES:
            raise _reject(raw, f"路径段 {part!r} 是 Windows 保留设备名（不是普通文件）")
        parts.append(part)

    candidate = (ctx.root / Path(*parts)).resolve() if parts else ctx.root
    try:
        candidate.relative_to(ctx.root)
    except ValueError:
        # 这一句是唯一的越界判据：`..`、符号链接、短名都已经被 resolve() 展开成
        # 真实路径，因此这里比任何字符串规则都可靠。
        raise _reject(raw, f"越出工作区（解析为 {candidate}，工作区根为 {ctx.root}）") from None
    return candidate


def _rel(ctx: FsContext, path: Path) -> str:
    """工作区内的相对路径（一律 `/` 分隔）。返回给调用方的路径都长这样 ——
    绝对路径会泄露机器布局，且让"同样的调用在不同机器上结果不同"。"""
    try:
        rel = path.relative_to(ctx.root).as_posix()
    except ValueError:  # 理论上不会发生（_resolve 已保证），防御性兜底
        return path.as_posix()
    return rel or "."


def _guard(fn: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
    """把"路径类失败/环境故障"统一转成 `fail(...)`。

    为什么不用异常传播：`ToolRegistry.call` 确实会兜住异常，但直接调用 handler
    （脚本模式、测试、未来的 CLI）不会。沙箱拒绝对这两条路径必须是同一个行为 ——
    「越界」是本模块的第一公民，它不能依赖上层有没有 try。
    """

    @wraps(fn)
    def wrapper(ctx: FsContext, **kwargs: Any) -> ToolResult:
        try:
            return fn(ctx, **kwargs)
        except ToolError as e:
            return fail(str(e), kind="path_denied", tool=getattr(fn, "__name__", ""))
        except OSError as e:
            return fail(f"{type(e).__name__}: {e}", kind="os_error", tool=getattr(fn, "__name__", ""))
        except (ValueError, UnicodeError) as e:
            return fail(f"{type(e).__name__}: {e}", kind="bad_input", tool=getattr(fn, "__name__", ""))

    return wrapper


# ---------------------------------------------------------------- 内容探测


def _looks_binary(head: bytes) -> tuple[bool, str]:
    """启发式二进制判定。返回 (是否二进制, 理由)。

    规则（按强度排序）：
    1. 含 NUL 字节即视为二进制 —— 这条是硬规则：没有任何常见文本编码会在
       正文里出现 NUL（UTF-16 会出现，但那正是我们要拦下来的"看起来像文本、
       其实按 UTF-8 解出来是乱码"的东西）。
    2. 其它 C0 控制字节的占比超过 `CTRL_RATIO_LIMIT` —— 兜住"头部恰好没有 NUL"
       的压缩/加密流。没有这一条的话，一条全随机的字节流会被当成文本读出来，
       而乱码文本比明确的拒绝危险得多：它会一路流进概念抽取，污染知识库。
    """
    if b"\x00" in head:
        return True, "含 NUL 字节"
    if not head:
        return False, "空文件"
    ctrl = sum(1 for b in head if b < 0x20 and b not in _TEXT_CTRL_OK)
    if ctrl / len(head) > CTRL_RATIO_LIMIT:
        return True, f"控制字节占比 {ctrl / len(head):.1%} > {CTRL_RATIO_LIMIT:.0%}"
    return False, ""


def _read_head(path: Path, n: int) -> bytes:
    with open(path, "rb") as f:
        return f.read(n)


def _decode_text(raw: bytes) -> tuple[str, str, bool]:
    """解码字节。返回 (文本, 编码标记, 是否发生了替换)。

    优先 UTF-8 —— 本项目所有落盘产物都是 UTF-8。失败后试 GB18030：中文 Windows 上
    大量历史文本是 GBK 系编码，直接 `errors="replace"` 会把它变成一片 `?`，
    而"读不出来"和"读出来是乱码"对调用方是两件事（前者该换工具，后者该换编码）。
    两者都失败才退到带替换的 UTF-8，并把 `had_errors` 如实报出去。
    """
    try:
        return raw.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:  # noqa: BLE001 —— 理由：这是回退链，不是吞异常。
        # UTF-8 解不开并不表示"读不出来"，只表示"该换下一个编码试"。真正的失败形态是
        # 两个分支都失败，那由最后一行如实回报（`had_errors=True` + 编码标记带 `/replace`）。
        pass
    try:
        return raw.decode("gb18030"), "gb18030", False
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), "utf-8/replace", True


def _sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _entry(ctx: FsContext, path: Path) -> dict:
    """列目录用的一条记录。stat 失败（断链、权限）也要给出记录 —— 静默少一行，
    调用方就再也分不清"没有这个文件"和"我没权限看它"。"""
    is_link = path.is_symlink()
    try:
        st = path.stat()
        size: int | None = st.st_size
        mtime: float | None = st.st_mtime
    except OSError:
        size, mtime = None, None
    return {
        "name": path.name,
        "path": _rel(ctx, path),
        "is_dir": path.is_dir(),
        "is_file": path.is_file(),
        "is_symlink": is_link,
        "size": size,
        "mtime": _iso(mtime),
    }


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().replace(microsecond=0).isoformat()


def _iter_entries(base: Path, *, recursive: bool) -> Iterator[Path]:
    """按确定性顺序遍历（相对路径升序）。

    不排序的话，同一份目录在不同文件系统上返回的顺序不同，测试与 LLM 的复现性都会崩
    （"上次它看到第 3 个是 X"这种判断会随机失效）。
    """
    if base.is_file():
        yield base
        return
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirs = sorted(dirnames, key=str.casefold)
        files = sorted(filenames, key=str.casefold)
        if not recursive:
            dirnames[:] = []  # 阻止 os.walk 继续下钻
        d = Path(dirpath)
        for name in dirs:
            yield d / name
        for name in files:
            yield d / name


def _include_match(pattern: str | None, rel: str) -> bool:
    """`include` 的 glob 语义。

    - 带 `/` 的模式按整条相对路径匹配（`reports/*.md`）；
    - 不带 `/` 的按文件名匹配，等价于 `rg -g '*.py'` 的直觉。
    用 `fnmatchcase` 而不是 `fnmatch`：后者会在 Windows 上按 `normcase` 折叠大小写，
    于是同一个模式在 Windows/macOS/Linux 上筛出不同的文件集 —— 那种"平台相关的
    grep 结果"是最难查的一类不一致。
    """
    if not pattern:
        return True
    target = rel if "/" in pattern else PurePosixPath(rel).name
    return fnmatch.fnmatchcase(target, pattern)


# ---------------------------------------------------------------- 参数片段


def _obj(props: Mapping[str, Any], required: Iterable[str] = ()) -> dict:
    return {
        "type": "object",
        "properties": dict(props),
        "required": list(required),
        "additionalProperties": False,
    }


# ---------------------------------------------------------------- 工具实现


@tool(
    "fs.list",
    "列出工作区内某目录（或单个文件）的条目；recursive=true 时递归。",
    _obj(
        {
            "path": {"type": "string", "default": ".", "description": "相对工作区根的路径"},
            "recursive": {"type": "boolean", "default": False, "description": "是否递归子目录"},
            "limit": {"type": "integer", "minimum": LIST_LIMIT_MIN, "maximum": LIST_LIMIT_MAX, "default": LIST_LIMIT_DEFAULT},
        }
    ),
    side_effect="read",
    roles=TOOL_ROLES,
    # 键名从一个真实调用读出（`fs_list`）。注意 `path` 在 data 里（是被列举的那个
    # 目录），另有一个同名键在 meta 里 —— 两处含义不同，都保留。
    returns="{'entries','path','total','returned','truncated'}；entries[] 每项是 "
    "{'name','path','is_dir','is_file','is_symlink','size','mtime'}。",
    tags=("fs", "read"),
)
@_guard
def fs_list(ctx: FsContext, *, path: str = ".", recursive: bool = False, limit: int = LIST_LIMIT_DEFAULT) -> ToolResult:
    """列目录。

    符号链接只列不跟（`is_symlink=True` 如实标出）：跟随链接既可能走出工作区，
    也会让同一份内容被列两次。要读链接指向的内容，请用真实路径显式调用。
    """
    target = _resolve(ctx, path)
    if not target.exists() and not target.is_symlink():
        raise ToolError(f"路径不存在：{_rel(ctx, target)}")
    items = [_entry(ctx, p) for p in _iter_entries(target, recursive=recursive)]
    items.sort(key=lambda d: d["path"].casefold())
    page = items[:limit]
    return ok(
        {
            "path": _rel(ctx, target),
            "entries": page,
            "total": len(items),
            "returned": len(page),
            "truncated": len(items) > len(page),
        },
        total=len(items),
        returned=len(page),
        truncated=len(items) > len(page),
    )


@tool(
    "fs.read",
    "读文本文件；二进制直接拒绝，超限返回截断内容并标注。**大文件分段读**：给 `start_line`（1 起）与 `max_lines` 取那一段，`"
    "meta.next_line` 是下一段起点（EOF 为 null）。",
    _obj(
        {
            "path": {"type": "string", "description": "相对工作区根的路径"},
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": MAX_READ_BYTES, "default": READ_DEFAULT_BYTES},
            "start_line": {"type": "integer", "minimum": 1, "default": 1,
                           "description": "从第几行开始（1 起）；配合 max_lines 做分段读"},
            "max_lines": {"type": "integer", "minimum": 0, "default": 0,
                          "description": "最多取多少行；0 = 不按行截（只受 max_bytes 限制）"},
        },
        required=("path",),
    ),
    side_effect="read",
    roles=TOOL_ROLES,
    # 豁免清单成员（见 `tests/test_tools_returns_declaration.py::NO_KEY_SET_EXEMPTIONS`）：
    # data 是标量文本，声明不出键集合。meta 里还有 path/encoding/bytes_read/
    # total_bytes/truncated/had_errors/sha256 —— 那是审计附注，不是 data 的形状。
    returns="data=文本（**标量，无键集合**）；meta 里给 encoding / bytes_read / total_bytes / truncated / "
            "start_line / lines_read / total_lines / next_line / had_errors / sha256 / routed_from。"
            "start_line / lines_read / total_lines / next_line / had_errors / sha256。",
    tags=("fs", "read"),
)
@_guard
def fs_read(ctx: FsContext, *, path: str, max_bytes: int = READ_DEFAULT_BYTES,
            start_line: int = 1, max_lines: int = 0) -> ToolResult:
    """读文本。

    三种"读不了"被刻意区分开（这是本工具最容易被做烂的地方）：
    - 二进制：拒绝。把 PDF 按 UTF-8 读出来是一屏乱码，而乱码会被下游当成内容。
    - 超限：截断 + `truncated=True` + 真实 `total_bytes`。只回"太大了"就什么都不给，
      对"只想看看开头"的调用方是纯粹的损失。
    - 编码不是 UTF-8：如实报出实际用的编码，而不是假装它就是 UTF-8。

    第四件事是分段读（`start_line`/`max_lines`）：真机实测（2026-09-30）一个 E 子循环
    拿 17849 字节的台账，连续 14 步反复重读同一个开头 —— 因为它拿到的每个结果都被
    观测层截断（当时的上限是 1200 字），而没有任何办法读后面的部分。观测层的截断发生在
    这一步之后（见 `agent_loop._observe`），所以"能分段"必须由本工具提供：`meta.next_line`
    就是下一段的起点，读到尾时为 `None`。按行而不是按字节分段，是因为按字节切会把一行切两半，
    而调用方拿到的两半都读不成话。
    """
    target = _resolve(ctx, path)
    if not target.exists():
        # 先记"确认缺失"、再抛（逐字照 DSH `TFS:276` 的顺序）：
        # 反过来会让"读一个不存在的路径以授权带防护的创建"这条路断掉。
        OBS.observed_gate().note_absent(OBS.current_owner(), target)
        raise ToolError(f"文件不存在：{_rel(ctx, target)}")
    if target.is_dir():
        raise ToolError(f"{_rel(ctx, target)} 是目录（要列出内容请用 fs.list）")

    st = target.stat()
    size = st.st_size
    suffix = target.suffix.casefold()
    head = _read_head(target, min(size, SNIFF_BYTES))
    is_bin, why = _looks_binary(head)
    # 扩展名只是补充判据：NUL 规则已经覆盖绝大多数二进制，扩展名兜住少数特例。
    if not is_bin and suffix in _BINARY_SUFFIXES:
        is_bin, why = True, f"扩展名 {suffix} 属于二进制格式"
    if is_bin:
        # ⚠️ **2026-10-17 业主口径**：*"把其它智能体要消费论文的请求**自动路由到同名纯文字稿**，
        # 其它智能体不必再做 OCR 等操作。"* ⇒ 这里不再一律拒：若这一份旁边有
        # **同名纯文字稿**（A 用 `text.extract` 转好的那份，落在同一层），**直接把稿子给它**，
        # 并在读数里**说清"你要的是 PDF、我改读的是同名稿"**（不许静默替换来源）。
        sibling = target.with_suffix(".txt")
        if target.suffix.casefold() == ".pdf" and sibling.is_file():
            try:
                routed_text = sibling.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return fail(
                    f"同名纯文字稿读不出来（{type(exc).__name__}）：{_rel(ctx, sibling)} ⇒ "
                    "这一格没读成，不是「没有纯文字稿」；可让 **A** 重跑 `text.extract`。",
                    path=_rel(ctx, sibling), kind="route_unreadable", size=size,
                )
            # 形状与正常读取**逐字同形**：`data` 是标量文本，其余进 `meta`
            # （`fs.read` 在声明判据里是"data 无键集合"的豁免成员 —— 自造 data 键会破那条豁免）。
            routed_lines = routed_text.splitlines(keepends=True)
            return ok(
                routed_text,
                path=_rel(ctx, sibling),
                encoding="utf-8",
                bytes_read=len(routed_text.encode("utf-8")),
                total_bytes=len(routed_text.encode("utf-8")),
                truncated=False,
                start_line=1,
                lines_read=len(routed_lines),
                total_lines=len(routed_lines),
                next_line=None,
                windowed=False,
                had_errors=False,
                sha256=None,
                routed_from=_rel(ctx, target),
                note=("你要读的是二进制 PDF；按业主口径**自动路由到同名纯文字稿**"
                      f"（`routed_from={_rel(ctx, target)}` 是你原本要读的那一份）"
                      "—— 其它角色不必自己做 OCR/抽取。"),
            )
        return fail(
            f"拒绝按文本读取 {_rel(ctx, target)}：判定为二进制（{why}）。"
            "需要它的内容请走抽取链（extract/OCR），不要当文本读 —— 乱码会被下游当成内容。"
            "**出路**：让 **A** 跑 `text.extract`（它会把同名纯文字稿写进 library/，"
            "于是这一件**自动路由**给你，你不必自己做 OCR/抽取）。",
            path=_rel(ctx, target),
            kind="binary",
            size=size,
            reason=why,
        )

    # 硬上限夹紧而不是拒绝：见 MAX_READ_BYTES 的说明。夹紧这件事必须说出来。
    limit = min(max_bytes, MAX_READ_BYTES)
    clamped = max_bytes > MAX_READ_BYTES
    with open(target, "rb") as f:
        raw = f.read(limit)
    truncated = size > len(raw)
    text, encoding, had_errors = _decode_text(raw)
    note = ""
    if truncated:
        note = f"只读了前 {len(raw)} 字节（共 {size} 字节）"
    if clamped:
        note = (note + "；" if note else "") + f"max_bytes 被夹到硬上限 {MAX_READ_BYTES}"

    # 分段读。`start_line <= 1` 且 `max_lines == 0` 时是完全向后兼容的整段读。
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    begin = max(1, int(start_line)) - 1
    windowed = begin > 0 or max_lines > 0
    if windowed:
        end = total_lines if max_lines <= 0 else min(total_lines, begin + int(max_lines))
        picked = lines[begin:end]
        shown = "".join(picked)
        next_line = end + 1 if end < total_lines else None
        # 空窗口（start_line 超过行数）要如实说，且不能说成"文件是空的"。
        seg = (f"第 {begin + 1}–{end} 行" if picked else f"第 {begin + 1} 行起是空的")
        note = (note + "；" if note else "") + f"本次给{seg}（共 {total_lines} 行）"
        if next_line is not None:
            note += f"；续读 start_line={next_line}"
    else:
        shown = text
        next_line = None
        if total_lines > 1:
            scope = "已读窗口内" if truncated else "共"
            note = (note + "；" if note else "") + f"{scope} {total_lines} 行"
    # 读成功即"看过"（DSH `TFS:430`）——哪怕只读了一个窗口/被截断：
    # 授权依据是"版本新鲜度"，不是"视图完整性"（DSH 自己承认的已知弱化，照搬）。
    # 版本取读之前那一次 stat（`st`），与 DSH `TFS:274`→`TFS:430` 同一顺序。
    OBS.observed_gate().observe(OBS.current_owner(), str(target), OBS.Observation(OBS.OBS_PRESENT,
                                                                       OBS.version_of(st)))
    return ok(
        shown,
        path=_rel(ctx, target),
        encoding=encoding,
        bytes_read=len(raw),
        total_bytes=size,
        truncated=truncated,
        start_line=begin + 1,
        lines_read=len(shown.splitlines(keepends=True)),
        total_lines=total_lines,
        next_line=next_line,
        windowed=windowed,
        had_errors=had_errors,
        note=note,
        sha256=_sha256(target) if size <= MAX_READ_BYTES else None,
    )


#: `fs.edit` 的单次改动上限（字节）。定 2,000 的理由：一次 reply 的实测输出约 191 token
#: （`draft/37` §1.2 的读数），而"定点改一处"应当落在一次 reply 的额度内 ——
#: 超过这个量就不是定点替换，而是整段重写，该走 `fs.write` 或拆成几处。
MAX_EDIT_BYTES = 2000


def _atomic_write_bytes(target: Path, payload: bytes) -> None:
    """同目录临时文件 → `os.replace`：要么旧内容，要么新内容，没有第三种可能。

    为什么把这段抽出来：`fs.write` 与 `fs.edit` 都要它，而"原子落盘"这种事
    长成两份实现时，两份的差别只会在崩溃的那一刻显形（本项目最贵的一类 bug）。
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件必须落在同一个目录：跨盘/跨文件系统的 os.replace 不是原子的。
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())  # 先落盘再改名，避免"改名成功但内容还在页缓存里"
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)  # 失败路径不能留下垃圾临时文件
        raise


@tool(
    "fs.write",
    "写文本文件（原子落盘；默认不覆盖已有文件）。",
    _obj(
        {
            "path": {"type": "string", "description": "相对工作区根的路径"},
            "content": {"type": "string", "description": "文件内容（UTF-8）"},
            "overwrite": {"type": "boolean", "default": False, "description": "为 true 才允许覆盖已有文件"},
        },
        required=("path", "content"),
    ),
    side_effect="write_local",
    roles=TOOL_ROLES,
    # 键名从一个真实调用读出（`fs_write`）。
    returns="{'path','bytes','sha256','created'}",
    tags=("fs", "write"),
)
@_guard
def fs_write(ctx: FsContext, *, path: str, content: str, overwrite: bool = False) -> ToolResult:
    """写文本 + 原子落盘。

    原子性用"同目录临时文件 → `os.replace`"实现（与 `store._atomic_write` 同一套路）。
    为什么不能直接 `open(w)`：写到一半崩溃会留下半个文件，而下游无法区分
    "这个文件本来就是残的"和"写入时崩了" —— 前者该忽略，后者该重跑。
    `os.replace` 之后只有"旧内容"或"新内容"两种可能，判断因此是确定的。
    """
    target = _resolve(ctx, path)
    if target.exists() and target.is_dir():
        raise ToolError(f"{_rel(ctx, target)} 是目录，不能当文件写")

    payload = content.encode("utf-8")
    if len(payload) > MAX_WRITE_BYTES:
        return fail(
            f"内容过大：{len(payload)} 字节 > 单次上限 {MAX_WRITE_BYTES} 字节。"
            "（工具层是给 LLM 用的，一次写这么大几乎总是误用。"
            "要改**已有**的大文件请用 `fs.edit`：一次一处锚定替换，"
            "输出量与改动量成正比而不是与文件大小成正比 —— 这条路上真机踩过的坑是"
            "「整文件重写 26 KB ⇒ 回复被截在字符串中间 ⇒ 连续三次坏 JSON ⇒ 整趟作废」。"
            "要**新建**大文件请分块写，或改用脚本模式直接落盘。）",
            path=_rel(ctx, target),
            kind="too_large",
            bytes=len(payload),
            max_bytes=MAX_WRITE_BYTES,
        )
    existed = target.exists()
    if existed and not overwrite:
        return fail(
            f"{_rel(ctx, target)} 已存在；要覆盖请显式传 overwrite=true。"
            "（默认不覆盖：覆盖不可逆，而『我以为它在写新文件』是最常见的事故来源。）",
            path=_rel(ctx, target),
            kind="exists",
            existed=True,
        )

    # 读后写那一闸（裁定 9甲；DSH `FSL:821-828` 的搬运）。
    # 顺序：意图（policy 层）→ 版本核对（provider 层）→ 落盘 → 重新观察。
    owner = OBS.current_owner()
    key = str(target)
    intent, expected = OBS.observed_gate().write_intent(owner, key)
    if intent == "replace_if_version":
        now = OBS.stat_version(target)
        if not now:
            return fail(OBS.remedy_stale(f'不能写 "{_rel(ctx, target)}"：它在你读过之后没了'),
                        path=_rel(ctx, target), kind=OBS.CODE_STALE_VERSION,
                        observed_version=expected, version_now="")
        if now != expected:
            return fail(OBS.remedy_stale(f'不能写 "{_rel(ctx, target)}"：它在你读过之后变过了'),
                        path=_rel(ctx, target), kind=OBS.CODE_STALE_VERSION,
                        observed_version=expected, version_now=now)
    elif existed:
        # createIfAbsent + 目标已存在 = 没读过就要覆盖 ⇒ 拒（这是本闸的主战场）。
        return fail(OBS.remedy_not_observed(_rel(ctx, target)),
                    path=_rel(ctx, target), kind=OBS.CODE_NOT_OBSERVED,
                    existed=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(target, payload)
    # 写完之后重新观察"写后版本"，而不是沿用意图里的期望版本（DSH `FSL:831`、`TFS:657`）：
    # 否则同一步里"写 → 再写"会被自己拒掉。
    OBS.observed_gate().note_present(owner, target)
    return ok(
        {"path": _rel(ctx, target), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "created": not existed},
        path=_rel(ctx, target),
        bytes=len(payload),
        created=not existed,
    )


@tool(
    "fs.edit",
    "定点替换文件里的一段文本（old_string → new_string）：默认要求 old_string 恰好出现一次，可选要求 sha256 与读到的那一版一致。",
    _obj(
        {
            "path": {"type": "string", "description": "相对工作区根的路径"},
            "old_string": {"type": "string", "description": "要被替换的那段原文（逐字，默认必须唯一）"},
            "new_string": {"type": "string", "description": "替换成什么（空串 = 删掉这一段）"},
            "sha256": {"type": "string", "description": "可选：调用方读到文件时的 sha256；不符即拒（防「我拿的是旧版」）"},
            "allow_multiple": {"type": "boolean", "default": False,
                               "description": "为 true 才允许 old_string 出现多次（全部替换）"},
            "note": {"type": "string", "description": "为什么改这一处（回在返回值里，供审计）"},
        },
        required=("path", "old_string", "new_string"),
    ),
    side_effect="write_local",
    roles=TOOL_ROLES,
    returns="{'path','sha256_before','sha256_after','replacements','bytes_before','bytes_after','note'}",
    tags=("fs", "write", "edit"),
)
@_guard
def fs_edit(ctx: FsContext, *, path: str, old_string: str, new_string: str,
            sha256: str | None = None, allow_multiple: bool = False,
            note: str = "") -> ToolResult:
    """把 `old_string` 换成 `new_string` —— 只动那一处。

    为什么必须有这一件（`draft/37` §1.2/§16 P0，真机实测 2026-10-01）：
    `fs.write` 是整文件覆盖语义，而观测层每次只回显约 3,000 字。一篇 51,285 字节
    （≈25.6K token）的论文要改一处措辞，用整文件覆盖就意味着"在一次回复里逐字吐出全文"
    —— 模型单次输出上限 4,096 token，物理上写不出来；G 因此三次拒绝改稿
    （原话：「在无法逐字重建全文的前提下做整文件 overwrite，有静默损坏正文的风险」）。
    定点替换把一次改动的代价从"全文"降到"那一处"。

    三道闸（对应 §16 P0 的判据）：
    - 唯一匹配：`old_string` 出现多次时默认拒绝（`kind="ambiguous"`）—— 替换错地方比不替换更坏；
    - 前置版本：给了 `sha256` 就必须与盘上现在这一版相等，否则拒（`kind="sha_mismatch"`）；
    - 改动上限：`new_string` 超过 `MAX_EDIT_BYTES` 就拒 —— 那说明这次改动不是"定点"。
    """
    target = _resolve(ctx, path)
    # 读后写那一闸在最前面（policy 层先于 provider 层，逐字照 DSH `POL:64-70` → `FSL:840`）：
    # DSH 的编辑闸跑在逐字匹配之前，为的是"陈旧的编辑绝不报成误导性的「找不到」"。
    rel = _rel(ctx, target)
    owner = OBS.current_owner()
    key = str(target)
    try:
        observed_version = OBS.observed_gate().edit_intent(owner, key, rel)
    except OBS.ObservationRefusal as refusal:
        return fail(refusal.message, path=rel, kind=refusal.code)
    if not target.exists():
        return fail(f"{rel} 不存在（定点替换只能改已有文件）",
                    path=rel, kind="not_found")
    if target.is_dir():
        raise ToolError(f"{rel} 是目录，不能当文件改")
    before = target.read_bytes()
    if len(before) > MAX_READ_BYTES:
        return fail(f"{rel} 有 {len(before)} 字节，超过可改上限 {MAX_READ_BYTES}",
                    path=rel, kind="too_large", bytes=len(before))
    if OBS.stat_version(target) != observed_version:
        return fail(OBS.remedy_stale(f'不能改 "{rel}"：它在你读过之后变过了'),
                    path=rel, kind=OBS.CODE_STALE_VERSION,
                    observed_version=observed_version, version_now=OBS.stat_version(target))
    if sha256 and sha256 != hashlib.sha256(before).hexdigest():
        return fail(
            f"{rel} 现在这一版的 sha256 与调用方给的不符 ⇒ 拒绝改。"
            "（这一条防的是「我拿到的是别人改之前的那一版」—— 盲改会把别人的改动覆盖掉。）",
            path=rel, kind="sha_mismatch",
            sha256_now=hashlib.sha256(before).hexdigest(),
        )
    text, encoding, had_errors = _decode_text(before)
    if had_errors:
        return fail(f"{_rel(ctx, target)} 不是干净的 UTF-8（解码时有替换字符）⇒ 拒绝改，"
                    "免得把编码问题写坏成内容问题",
                    path=_rel(ctx, target), kind="not_utf8", encoding=encoding)
    if not old_string:
        return fail("old_string 不能为空（空串会在每一处之间插入 new_string）",
                    path=_rel(ctx, target), kind="empty_old_string")
    count = text.count(old_string)
    if count == 0:
        return fail(f"old_string 在 {_rel(ctx, target)} 里找不到（逐字比对，含空白）⇒ 拒绝改",
                    path=_rel(ctx, target), kind="not_found_old_string")
    if count > 1 and not allow_multiple:
        return fail(
            f"old_string 在 {_rel(ctx, target)} 里出现了 {count} 次 ⇒ 拒绝改。"
            "要改哪一处，就把 old_string 写长到唯一（带上前后文），"
            "或显式 allow_multiple=true 表示「每一处都换」。",
            path=_rel(ctx, target), kind="ambiguous", occurrences=count,
        )
    payload = new_string.encode("utf-8")
    if len(payload) > MAX_EDIT_BYTES:
        return fail(
            f"new_string 有 {len(payload)} 字节 > 单次定点替换上限 {MAX_EDIT_BYTES} 字节 ⇒ 拒绝。"
            "（一次改动这么大就不是「定点」了：请拆成几处，或改用整文件 fs.write。）",
            path=_rel(ctx, target), kind="too_large", bytes=len(payload),
            max_bytes=MAX_EDIT_BYTES,
        )
    after_text = text.replace(old_string, new_string)
    after_bytes = after_text.encode("utf-8")
    _atomic_write_bytes(target, after_bytes)
    # 改完之后重新观察"改后版本"（DSH `FSL:850`、`TFS:810`）——
    # 于是同一步里"改 → 再改同一处"不必再读一遍才被允许。
    OBS.observed_gate().note_present(owner, target)
    return ok(
        {
            "path": _rel(ctx, target),
            "sha256_before": hashlib.sha256(before).hexdigest(),
            "sha256_after": hashlib.sha256(after_bytes).hexdigest(),
            "replacements": count,
            "bytes_before": len(before),
            "bytes_after": len(after_bytes),
            "note": str(note or ""),
        },
        path=_rel(ctx, target),
        replacements=count,
        note=str(note or ""),
    )


@tool(
    "fs.delete",
    "删除文件；删目录必须显式 recursive=true（不许删工作区根）。",
    _obj(
        {
            "path": {"type": "string", "description": "相对工作区根的路径"},
            "recursive": {"type": "boolean", "default": False, "description": "为 true 才允许删除目录（含非空目录）"},
        },
        required=("path",),
    ),
    side_effect="write_local",
    roles=TOOL_ROLES,
    # 豁免清单成员：data 是布尔标量（是否真的删掉了），声明不出键集合。
    # "文件本来就不存在"由 meta.found 与 meta.deleted 区分。
    returns="data=是否真的删掉了（**布尔标量，无键集合**）；meta.found 区分本来就没有的情况。",
    tags=("fs", "write"),
)
@_guard
def fs_delete(ctx: FsContext, *, path: str, recursive: bool = False) -> ToolResult:
    """删除。

    默认只删文件：删目录必须显式 `recursive=true`。这条不是洁癖 ——
    `fs.delete("reports")` 与 `fs.delete("reports/old.md")` 在参数上只差几个字符，
    而后果差一个目录树；要求显式开关，就等于要求调用方在参数里表达出"我知道这是目录"。
    工作区根被无条件拒绝：删掉它等于删掉整个项目的数据。
    """
    target = _resolve(ctx, path)
    if target == ctx.root or target.parent == target:
        return fail(
            f"拒绝删除工作区根（{target}）。",
            path=_rel(ctx, target),
            kind="refuse_root",
            deleted=False,
        )
    if not target.exists() and not target.is_symlink():
        return ok(False, path=_rel(ctx, target), found=False, deleted=False)

    if target.is_symlink():
        # 符号链接只删链接本身。跟随删除会打到链接指向的文件 ——
        # 那可能在工作区外，而调用方从参数上完全看不出来。
        target.unlink()
        return ok(True, path=_rel(ctx, target), found=True, deleted=True, kind="symlink")

    if target.is_dir():
        if not recursive:
            return fail(
                f"{_rel(ctx, target)} 是目录。删除目录必须显式传 recursive=true"
                "（默认只删文件，避免一次参数笔误删掉整棵目录树）。",
                path=_rel(ctx, target),
                kind="is_dir",
                deleted=False,
            )
        shutil.rmtree(target)
        return ok(True, path=_rel(ctx, target), found=True, deleted=True, kind="dir")

    target.unlink()
    return ok(True, path=_rel(ctx, target), found=True, deleted=True, kind="file")


@tool(
    "fs.move",
    "移动或重命名（目标已存在时拒绝，不静默覆盖）。",
    _obj({"src": {"type": "string"}, "dst": {"type": "string"}}, required=("src", "dst")),
    side_effect="write_local",
    roles=TOOL_ROLES,
    # 键名从一个真实调用读出（`fs_move`）：只有 src/dst 两个键。
    returns="{'src','dst'}",
    tags=("fs", "write"),
)
@_guard
def fs_move(ctx: FsContext, *, src: str, dst: str) -> ToolResult:
    """移动/重命名。

    目标存在时拒绝而不是覆盖：`shutil.move` 在 POSIX 上会直接把目标目录挪进去
    （`mv a b` 当 b 是目录时变成 `b/a`），在 Windows 上又是另一套行为 ——
    与其在两种平台上给出两种结果，不如让调用方自己先删或先改名。
    """
    s = _resolve(ctx, src)
    d = _resolve(ctx, dst)
    if s == ctx.root or d == ctx.root:
        return fail("拒绝移动工作区根", src=_rel(ctx, s), dst=_rel(ctx, d), kind="refuse_root")
    if not s.exists() and not s.is_symlink():
        return fail(f"源不存在：{_rel(ctx, s)}", src=_rel(ctx, s), kind="not_found")
    if s == d:
        return fail("源与目标相同", src=_rel(ctx, s), kind="same_path")
    if d.exists() or d.is_symlink():
        return fail(
            f"目标已存在：{_rel(ctx, d)}（本工具不静默覆盖，请先删除或换一个名字）",
            src=_rel(ctx, s),
            dst=_rel(ctx, d),
            kind="exists",
        )
    if s.is_dir():
        try:
            # 把目录移进自己的子目录会让内容"消失"（其实是递归包含），必须拦住。
            d.relative_to(s)
            return fail(f"不能把目录移动到它自己的子目录里：{_rel(ctx, s)} → {_rel(ctx, d)}", kind="self_nesting")
        except ValueError:  # noqa: BLE001 —— 理由："不是子路径"恰恰是通过检查。
            # `relative_to` 抛 ValueError 只有一种含义：`d` 不在 `s` 之下 ⇒ 这次移动是合法的，
            # 于是继续往下走。它不是"出错了"，所以这里既不该记日志也不该 fail。
            # （用"异常当控制流"本身不漂亮，但换成 `is_relative_to` 会改最低 Python 版本要求。）
            pass
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return ok({"src": _rel(ctx, s), "dst": _rel(ctx, d)}, src=_rel(ctx, s), dst=_rel(ctx, d))


@tool(
    "fs.stat",
    "查看路径的大小/类型/修改时间；文件另给 sha256。",
    _obj({"path": {"type": "string"}}, required=("path",)),
    side_effect="read",
    roles=TOOL_ROLES,
    # 键名从一个真实调用读出（`fs_stat`）。`mtime_epoch` 与 `link_target` 都在
    # 同一次返回里出现过；`link_target` 对非符号链接是 null（键仍在）。
    returns="{'path','exists','is_dir','is_file','is_symlink','size','mtime','mtime_epoch','sha256','link_target'}",
    tags=("fs", "read"),
)
@_guard
def fs_stat(ctx: FsContext, *, path: str) -> ToolResult:
    """查看元信息。

    sha256 是文件内容的指纹，用来回答"这个文件和刚才那个是不是同一份"
    （比 mtime 可靠：复制/重新下载都会改 mtime，但内容哈希不变）。
    目录不算 sha256；符号链接额外给出 `link_target`，因为"它指到哪儿"本身就是关键信息。
    """
    target = _resolve(ctx, path)
    if not target.exists() and not target.is_symlink():
        return ok({"path": _rel(ctx, target), "exists": False}, path=_rel(ctx, target), exists=False)
    st = target.stat()
    data: dict[str, Any] = {
        "path": _rel(ctx, target),
        "exists": True,
        "is_dir": target.is_dir(),
        "is_file": target.is_file(),
        "is_symlink": target.is_symlink(),
        "size": st.st_size,
        "mtime": _iso(st.st_mtime),
        "mtime_epoch": round(st.st_mtime, 3),
        "link_target": os.readlink(target) if target.is_symlink() else None,
        "sha256": None,
    }
    if target.is_file():
        data["sha256"] = _sha256(target)
    return ok(data, path=data["path"], size=data["size"], sha256=data["sha256"])


@tool(
    "fs.search",
    "在工作区文本文件里按 ripgrep 风格正则搜内容，返回「文件:行号: 行内容」。",
    _obj(
        {
            "pattern": {"type": "string", "minLength": 1, "description": "Python re 语法（与 ripgrep 的 Rust regex 基本兼容）"},
            "path": {"type": "string", "default": ".", "description": "搜索起点"},
            "include": {"type": "string", "description": "文件名或相对路径 glob，如 *.py / reports/*.md"},
            "limit": {"type": "integer", "minimum": SEARCH_LIMIT_MIN, "maximum": SEARCH_LIMIT_MAX, "default": SEARCH_LIMIT_DEFAULT},
        },
        required=("pattern",),
    ),
    side_effect="read",
    roles=TOOL_ROLES,
    # 键名从一个真实调用读出（`fs_search`）。注意 `lines` 的元素是字符串
    # （`'文件:行号: 行内容'`），不是对象。
    returns="{'matches','lines','path','pattern','total','truncated','scanned','skipped'}；"
    "matches[] 每项是 {'path','line','text'}，lines[] 每项是 '文件:行号: 行内容' 字符串。",
    tags=("fs", "read", "search"),
)
@_guard
def fs_search(
    ctx: FsContext,
    *,
    pattern: str,
    path: str = ".",
    include: str | None = None,
    limit: int = SEARCH_LIMIT_DEFAULT,
) -> ToolResult:
    """内容搜索。

    与 `table.search` 的分工：那边是数据面的子串匹配，这边是文本面的正则搜索。
    刻意跳过二进制与超大文件并如实计数：正则扫二进制文件既慢又只会产出噪声，
    而"扫了 0 个文件"和"扫了 100 个文件但都没命中"是两个完全不同的结论。
    """
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return fail(f"正则不合法：{e}（本工具用 Python re 语法）", pattern=pattern, kind="bad_regex")

    base = _resolve(ctx, path)
    if not base.exists():
        raise ToolError(f"搜索起点不存在：{_rel(ctx, base)}")

    matches: list[dict] = []
    skipped = {"binary": 0, "large": 0, "undecodable": 0, "include_miss": 0}
    scanned = 0
    truncated = False
    for p in _iter_entries(base, recursive=True):
        if not p.is_file() or p.is_symlink():
            continue
        rel = _rel(ctx, p)
        if not _include_match(include, rel):
            skipped["include_miss"] += 1
            continue
        if scanned >= SEARCH_MAX_FILES:
            truncated = True
            break
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > SEARCH_MAX_FILE_BYTES:
            skipped["large"] += 1
            continue
        try:
            raw = _read_head(p, min(size, SEARCH_MAX_FILE_BYTES))
        except OSError:
            continue
        is_bin, _why = _looks_binary(raw[:SNIFF_BYTES])
        if is_bin or p.suffix.casefold() in _BINARY_SUFFIXES:
            skipped["binary"] += 1
            continue
        text, _enc, had_errors = _decode_text(raw)
        if had_errors:
            # 解出来带替换字符 = 这份内容按 UTF-8/GB18030 都不是文本，
            # 拿来跑正则只会产出无法核对的"命中"。
            skipped["undecodable"] += 1
            continue
        scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            if not rx.search(line):
                continue
            shown = line.strip()
            if len(shown) > MAX_LINE_CHARS:
                shown = shown[:MAX_LINE_CHARS] + "…"
            matches.append({"path": rel, "line": lineno, "text": shown})
            if len(matches) >= limit:
                truncated = True
                break
        if truncated and len(matches) >= limit:
            break

    lines = [f"{m['path']}:{m['line']}: {m['text']}" for m in matches]
    return ok(
        {
            "pattern": pattern,
            "path": _rel(ctx, base),
            "matches": matches,
            "lines": lines,
            "total": len(matches),
            "truncated": truncated,
            "scanned": scanned,
            "skipped": skipped,
        },
        total=len(matches),
        truncated=truncated,
        scanned=scanned,
        skipped=skipped,
    )


# ---------------------------------------------------------------- 装配

_TOOL_FUNCTIONS: tuple[Callable[..., ToolResult], ...] = (
    fs_list,
    fs_read,
    fs_write,
    fs_edit,
    fs_delete,
    fs_move,
    fs_stat,
    fs_search,
)


def tool_specs() -> list[ToolSpec]:
    """未绑定 root 的工具清单（供装配前做目录/审计/文档生成）。"""
    return [fn.__tool_spec__ for fn in _TOOL_FUNCTIONS]  # type: ignore[attr-defined]


def _effective_roles(base: ToolSpec, injected: tuple[str, ...]) -> tuple[str, ...]:
    """把注入的角色集合按"只读角色不能拿写工具"过一遍。

    为什么要在这里做：`build_registry` 会把全部 `ROLES` 传进来，
    于是本模块的 8 个表工具（含 `create/update/delete`）会被声明给所有角色 ——
    包括只读的 C 与 H。实测过：`AgentH` 的工具面里出现了 `table.update`，
    即 审校者手里有能改稿件的刀。

    `ToolRegistry.for_role` 已经会做结构性拦截（防御不能只靠声明），
    但声明本身也应该对 —— 否则那条拦截会一直在“救火”，而调试者看到的
    角色工具数与声明不一致时会怀疑自己。
    """
    from . import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE

    if base.side_effect in SIDE_EFFECTS_WRITE:
        out = tuple(r for r in injected if r not in READ_ONLY_ROLES)
    else:
        out = tuple(injected)
    # 主控的成员资格逐工具给（见 `CONDUCTOR_FS_TOOLS` 的说明）：
    # 白名单里的五件加上 M，其余（`fs.edit` / `fs.delete` / `fs.move`）一律不给。
    from ..schema import CONDUCTOR_ROLE

    if base.name in CONDUCTOR_FS_TOOLS and CONDUCTOR_ROLE not in out:
        out = out + (CONDUCTOR_ROLE,)
    return out

def register(
    registry: ToolRegistry,
    *,
    root: str | os.PathLike[str],
    roles: Iterable[str] = TOOL_ROLES,
    actor: str = "tool",
) -> list[ToolSpec]:
    """注册 7 个文件工具，并把沙箱根绑定进 handler。

    root 在 `FsContext.__post_init__` 里就 resolve 成绝对路径 —— 这样每个 handler
    都不必再关心"root 是不是相对的"（相对 root 会随进程 cwd 漂移，
    表现为"同一个调用在不同工作目录下写到不同地方"，是最难复现的一类 bug）。

    `root=None` 时显式报错而不是让它变成 `Path(None)` 的 TypeError：
    `tools/__init__.py` 会把 register() 抛出的异常记进 `skipped`，
    一句话能读懂的跳过理由比一个堆栈有用得多。
    """
    if root is None:
        raise ToolError("fs_tools 需要一个工作区根（root / workspace_root），当前为 None：沙箱边界不可省略")
    # 新装配 = 新的一趟：清空观察台账（DSH 的 `gate.clear()`，`POL:87-89`）。
    # 为什么在这里清：观察表不持久化，而"恢复的会话必须重读目标"是照搬的语义；
    # 进程内多次装配（换工作区、换注册表）时不清就会把上一趟的账带过来。
    OBS.clear()
    ctx = FsContext(root=Path(root), actor=actor)
    out: list[ToolSpec] = []
    for fn in _TOOL_FUNCTIONS:
        base_spec: ToolSpec = fn.__tool_spec__  # type: ignore[attr-defined]
        spec = replace(base_spec, handler=partial(fn, ctx), roles=_effective_roles(base_spec, tuple(roles)))
        out.append(registry.register(spec))
    return out


# ---------------------------------------------------------------- 自检


def _selftest() -> int:
    """端到端自检：真建沙箱、真走 registry、正/负用例都跑。返回 0 表示全过。"""
    import shutil as _shutil
    import tempfile as _tempfile

    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f" —— {detail}" if detail else ""))
        if not cond:
            failures.append(label)

    sandbox = Path(_tempfile.mkdtemp(prefix="agentflow_fs_selftest_")).resolve()
    try:
        reg = ToolRegistry(name="selftest")
        # 绑定角色（`P-14`）：本自检要真的写文件，而 `fs.*` 的声明角色是 A/B/C/D ——
        # 取一个非只读角色（C 是只读，拿不到写工具）。不绑的话每一处 `reg.call`
        # 都会以"调用方没有声明角色"失败。
        reg.bound_role = "A"
        register(reg, root=sandbox, roles=("A", "B", "C", "D"))
        print(f"[环境] 沙箱根={sandbox}；已注册工具={reg.names()}")

        # ---- (5) 正面：write → read → stat(核对 sha256) → search → list → move → delete
        print("\n[1] 正面链路：write → read → stat → search → list → move → delete")
        body = "line one: hello\nline two: world\nline three: hello again\n"
        w = reg.call("fs.write", path="notes/a.txt", content=body)
        check("fs.write 建文件（含父目录）", w.ok and w.data["created"] is True and w.data["bytes"] == len(body.encode()), f"{w.data if w.ok else w.error}")
        r = reg.call("fs.read", path="notes/a.txt")
        check("fs.read 内容一致", r.ok and r.data == body, f"encoding={r.meta.get('encoding')} truncated={r.meta.get('truncated')}")
        st = reg.call("fs.stat", path="notes/a.txt")
        expect = hashlib.sha256(body.encode("utf-8")).hexdigest()
        check("fs.stat sha256 与本地哈希一致", st.ok and st.data["sha256"] == expect, f"{st.data['sha256'] if st.ok else st.error}")
        check("fs.stat 报出类型/大小/mtime", st.ok and st.data["is_file"] and st.data["size"] == len(body.encode()) and bool(st.data["mtime"]))
        s = reg.call("fs.search", pattern="hello", path="notes")
        check("fs.search 命中 2 行", s.ok and s.data["total"] == 2, f"lines={s.data['lines'] if s.ok else s.error}")
        check("fs.search 行格式为 文件:行号: 内容", s.ok and s.data["lines"][0].startswith("notes/a.txt:1: "), f"{s.data['lines'][0] if s.ok else ''}")
        s2 = reg.call("fs.search", pattern="hello", path=".", include="*.md")
        check("fs.search include 过滤生效（*.md 命中 0）", s2.ok and s2.data["total"] == 0, f"skipped={s2.meta.get('skipped')}")
        s3 = reg.call("fs.search", pattern="HELLO", path=".")
        check("fs.search 正则大小写：HELLO 不命中（无 IGNORECASE）", s3.ok and s3.data["total"] == 0, f"total={s3.data['total'] if s3.ok else s3.error}")
        s4 = reg.call("fs.search", pattern="(?i)HELLO", path=".")
        check("fs.search 内联 (?i) 生效", s4.ok and s4.data["total"] == 2, f"total={s4.data['total'] if s4.ok else s4.error}")
        li = reg.call("fs.list", path=".", recursive=True)
        paths = [e["path"] for e in li.data["entries"]] if li.ok else []
        check("fs.list 递归列出目录与文件", li.ok and "notes" in paths and "notes/a.txt" in paths, f"entries={paths}")
        mv = reg.call("fs.move", src="notes/a.txt", dst="notes/b.txt")
        check("fs.move 改名", mv.ok, f"{mv.data if mv.ok else mv.error}")
        check("move 后旧路径不存在", reg.call("fs.stat", path="notes/a.txt").data["exists"] is False)
        d = reg.call("fs.delete", path="notes/b.txt")
        check("fs.delete 删文件", d.ok and d.data is True, f"{d.data if d.ok else d.error}")
        d2 = reg.call("fs.delete", path="notes")
        check("fs.delete 目录默认被拒（需 recursive=true）", not d2.ok and "recursive" in (d2.error or ""), f"error={d2.error}")
        d3 = reg.call("fs.delete", path="notes", recursive=True)
        check("fs.delete 目录 recursive=true 放行", d3.ok and d3.data is True, f"err={d3.error}")

        # ---- (4) 负面：越界路径
        print("\n[2] 负面：路径越界/设备名/绝对路径（必须 ok=False 且不碰文件系统）")
        for label, bad_path in (
            ("../../etc/passwd", "../../etc/passwd"),
            ("../outside.txt", "../outside.txt"),
            ("C:\\Windows\\win.ini", "C:\\Windows\\win.ini"),
            ("/etc/shadow（POSIX 绝对路径）", "/etc/shadow"),
            ("\\\\server\\share\\x（UNC）", "\\\\server\\share\\x"),
            ("\\\\?\\C:\\Windows\\win.ini（设备命名空间）", "\\\\?\\C:\\Windows\\win.ini"),
            ("NUL（Windows 保留设备）", "NUL"),
            ("aux.txt（保留设备+扩展名）", "aux.txt"),
            ("a:b（NTFS 数据流）", "a:b"),
            ("CON（带尾随空格仍会被 Windows 当成设备名）", "CON "),
        ):
            res = reg.call("fs.read", path=bad_path)
            check(f"fs.read 拒绝 {label}", not res.ok, f"error={(res.error or '')[:70]}")
        res = reg.call("fs.write", path="..\\escape.txt", content="x")
        check("fs.write 拒绝越界（反斜杠形式）", not res.ok, f"error={(res.error or '')[:70]}")
        check("越界写入确实没有发生", not (sandbox.parent / "escape.txt").exists())
        res = reg.call("fs.write", path="C:\\Windows\\evil.txt", content="x")
        check("fs.write 拒绝绝对路径", not res.ok, f"error={(res.error or '')[:70]}")

        # ---- 符号链接逃逸（环境不支持创建链接时跳过，并如实说明）
        print("\n[3] 负面：符号链接逃逸")
        outside = Path(_tempfile.mkdtemp(prefix="agentflow_fs_outside_")).resolve()
        (outside / "secret.txt").write_text("外部机密", encoding="utf-8")
        link = sandbox / "escape_link"
        link_ok = False
        try:
            os.symlink(outside, link, target_is_directory=True)
            link_ok = True
        except (OSError, NotImplementedError) as e:
            print(f"    [SKIP] 本机无法创建符号链接（{type(e).__name__}: {e}），该项未验证")
        if link_ok:
            res = reg.call("fs.read", path="escape_link/secret.txt")
            check("fs.read 拒绝经符号链接出逃", not res.ok, f"error={(res.error or '')[:70]}")
            res = reg.call("fs.list", path="escape_link")
            check("fs.list 拒绝经符号链接出逃", not res.ok, f"error={(res.error or '')[:70]}")
            res = reg.call("fs.delete", path="escape_link", recursive=True)
            check("fs.delete 拒绝经符号链接出逃", not res.ok, f"error={(res.error or '')[:70]}")
        _shutil.rmtree(outside, ignore_errors=True)

        # ---- 其它安全边界
        print("\n[4] 其它安全边界")
        res = reg.call("fs.delete", path=".", recursive=True)
        check("fs.delete 拒绝工作区根", not res.ok and res.meta.get("kind") == "refuse_root", f"error={res.error}")
        res = reg.call("fs.move", src=".", dst="x")
        check("fs.move 拒绝工作区根", not res.ok, f"error={res.error}")
        reg.call("fs.write", path="dup.txt", content="1")
        res = reg.call("fs.write", path="dup.txt", content="2")
        check("fs.write 默认不覆盖", not res.ok and res.meta.get("kind") == "exists", f"error={res.error}")
        res = reg.call("fs.write", path="dup.txt", content="2", overwrite=True)
        check("fs.write overwrite=true 覆盖成功", res.ok and res.data["created"] is False)
        res = reg.call("fs.write", path="huge.txt", content="a" * (MAX_WRITE_BYTES + 1))
        check(f"fs.write 超 {MAX_WRITE_BYTES} 字节上限被拒",
              not res.ok and res.meta.get("kind") == "too_large", f"error={(res.error or '')[:70]}")
        check("超限写入的报文指向 fs.edit（改大文件的正确工具）",
              "fs.edit" in str(res.error or ""), f"error={(res.error or '')[:70]}")
        check("超限写入没有留下文件", not (sandbox / "huge.txt").exists())
        (sandbox / "raw.bin").write_bytes(b"\x00\x01\x02\xff\xfe" * 100)
        res = reg.call("fs.read", path="raw.bin")
        check("fs.read 拒绝二进制（NUL 嗅探）", not res.ok and res.meta.get("kind") == "binary", f"error={(res.error or '')[:70]}")
        reg.call("fs.write", path="long.txt", content="0123456789")
        res = reg.call("fs.read", path="long.txt", max_bytes=4)
        check(
            "fs.read 超 max_bytes 时截断并如实标注",
            res.ok and res.meta.get("truncated") is True and res.data == "0123" and res.meta.get("total_bytes") == 10,
            f"data={res.data!r} total={res.meta.get('total_bytes')} note={res.meta.get('note')}",
        )
        res = reg.call("fs.read", path="missing.txt")
        check("fs.read 不存在 → fail", not res.ok, f"error={res.error}")
        res = reg.call("fs.read", path=".")
        check("fs.read 目录 → fail", not res.ok, f"error={res.error}")
        res = reg.call("fs.search", pattern="(", path=".")
        check("fs.search 非法正则 → fail", not res.ok, f"error={(res.error or '')[:70]}")
        res = reg.call("fs.list", path="nope_dir")
        check("fs.list 不存在 → fail", not res.ok, f"error={res.error}")
        res = reg.call("fs.stat", path=".")
        check("fs.stat 工作区根允许（读元信息）", res.ok and res.data["is_dir"] is True)
        res = reg.call("fs.write", path="a/../b.txt", content="normalized")
        check("a/../b.txt 解析到 root 内，允许", res.ok and res.data["path"] == "b.txt", f"{res.data if res.ok else res.error}")
        res = reg.call("fs.write", path="sub/deep/c.txt", content="deep")
        check("多级父目录自动创建", res.ok, f"{res.error}")
        res = reg.call("fs.move", src="sub", dst="sub/deep/inner")
        check("fs.move 拒绝移进自己的子目录", not res.ok, f"error={res.error}")

        print(f"\n[结果] 失败 {len(failures)} 项" + (f"：{failures}" if failures else "，全部通过"))
        return 1 if failures else 0
    finally:
        _shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(_selftest())

# -*- coding: utf-8 -*-
"""文献读侧的两个口径：`literature.path` 落在哪个基准上，以及 `download.fulltext` 是哪一档。

## 为什么需要一个独立模块

这两件事各有一份"读侧真相"，而它们此前都分处两端、还各自漂过：

1. `literature.path` 有两个写入坐标系：`search_tools._adopt_file` 写着
   「相对路径优先按 `library/` 解释（表里存的就是这个坐标系），不存在再按 workspace
   解释」，而抽取入口 `agent_b.run_once` 只走 `store.library_path`（只认 `library/`）
   ⇒ 一条按工作区相对写下的 `library/000001/…` 被解析成 `library/library/000001/…`，
   真机 19 条 `no_fulltext` 里就有 1 条是这么来的。
   写入侧的归一化不在这里（`schema.literature_path_problem` 与 `table_tools` 的
   归一化是 2026-11-05 的 M4，属 FC-27、人审）：本模块只负责让存量行读得回来 ——
   历史行仍然带着那个前缀躺在盘上，读侧不认它就会把那篇文献判成 `file_missing`，
   而"文件真的不在"与"在另一个基准下"在读数上同形。
2. `download.fulltext` 的三个档只有写点、没有清除点：改前全仓只有
   `search_tools._mark_candidate_locator` 写过一个 `no_fulltext_this_time`，
   而 `status=ok` 的行照样一直挂着它（19 条里 6 条自相矛盾）。

两边各写一份判据，迟早会出现第三种口径。所以这里只收两件事的实现：

* :func:`resolve_literature_path`：先 `library/` 后 workspace（只对以
  `library/` 开头的串启用回退；其余串按老口径只认 `library/`），两条路都把结果
  钉在工作区之内 —— 放宽的是"文件在哪"，不是"能读到工作区外面去"。口径与
  `search_tools._lit_file` 同一套（它是读侧的先例）。
* :func:`fulltext_tier` / :func:`with_fulltext`：三档现算（`ok` /
  `no_text_layer` / `no_fulltext`），以及"写入与清除成对"的那一半 ——
  有字节但这一处还没抽过文本时不算档（返回 `None`），由 :func:`with_fulltext`
  把旧标签清掉，而不是猜一个档位或把上次的标签留着。

三态纪律在这里的具体形态：`None` 不是"没有全文"，是"这一处判不了"。
把它折成 `no_fulltext` 会让 `status=ok` 的行重新出现"有字节却没有全文"的自相矛盾；
把它折成 `ok` 则会让扫描件被记成可引用。两者都是把"没查成"说成了结论。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .schema import LIT_PATH_PREFIX

#: `download.fulltext` 的三档：有可抽文本 / 有字节但没有文本层 / 真的没有字节。
FULLTEXT_OK = "ok"
FULLTEXT_NO_TEXT_LAYER = "no_text_layer"
FULLTEXT_NO_FULLTEXT = "no_fulltext"
FULLTEXT_TIERS: tuple[str, ...] = (
    FULLTEXT_OK,
    FULLTEXT_NO_TEXT_LAYER,
    FULLTEXT_NO_FULLTEXT,
)

#: `path_base` 的两个取值：这一条 `literature.path` 是按哪个基准解析出来的。
BASE_LIBRARY = "library"
BASE_WORKSPACE = "workspace"

#: 只有以它开头的串才允许按 workspace 基准回退（见模块 docstring 第 1 条）。
#: 取值不在这里另写一遍：`schema.LIT_PATH_PREFIX` 是"这一格不该带它"的唯一声明
#: （2026-11-05 的 M4 写入闸拒的就是这个前缀）—— 读侧要认的正是同一串，
#: 两处各写一个 `"library/"` 早晚会漂。
WORKSPACE_PREFIX = LIT_PATH_PREFIX


@dataclass(frozen=True)
class ResolvedLiteraturePath:
    """一条 `literature.path` 的解析结果。

    `path is None` 时三个字段是这样分工的：`base` 为空串（没有解析出来），
    `candidates` 是试过的绝对路径（1 个或 2 个），`reason` 是写进
    `last_mine_error` 的那句 `file_missing` —— 两个候选都必须在里面
    （只写一个会让"另一个基准下其实有文件"这件事在读数上消失）。
    """

    path: Path | None
    base: str
    candidates: tuple[Path, ...]
    reason: str

    @property
    def found(self) -> bool:
        """解析到了一份盘上的普通文件。"""
        return self.path is not None


def _library_candidate(library: Path, rel: str) -> Path | None:
    """按 `library/` 基准解析；越出 `library/` 的写法在这里被拒。"""
    try:
        cand = (library / rel).resolve()
    except OSError:
        return None
    try:
        cand.relative_to(library.resolve())
    except ValueError:
        return None
    return cand


def _workspace_candidate(root: Path, rel: str) -> Path | None:
    """按 workspace 基准解析，并把结果钉在工作区之内。

    为什么"仍在工作区内"是硬条件：表里的 `path` 来自下载器与检索器，不是可信输入。
    放宽回退的是"文件可能在两个坐标系里"，不是"可以读到工作区外面去"。
    """
    base = Path(root).resolve()
    try:
        cand = (base / rel).resolve()
        cand.relative_to(base)
    except (OSError, ValueError):
        return None
    return cand


def _missing_reason(rel: str, candidates: Sequence[Path]) -> str:
    """`file_missing` 的逐字原因：试过几个基准就写几个绝对路径，一个都不许省。"""
    paths = [str(p) for p in candidates]
    if not paths:
        return f"file_missing: 没有可解析的候选（path={rel!r}）"
    if len(paths) == 1:
        return f"file_missing: {paths[0]}"
    return (f"file_missing: 两处都找不到（library 基准 {paths[0]}；"
            f"workspace 基准 {paths[1]}）")


def resolve_literature_path(root: Path | str, library: Path | str,
                            rel: str | None) -> ResolvedLiteraturePath:
    """把一条 `literature.path` 解析成盘上的文件，并说明用的是哪个基准。

    顺序：先 `library/` 基准；它不存在、且串以 `library/` 开头时才试 workspace
    基准。两个条件缺一不可 —— 不加前缀条件会让 `downloads/x.pdf` 这类本来就按
    workspace 写的旧行改变解析口径，而那是另一件事（`search_tools._lit_file`
    那一侧的口径）。

    返回的 `base` 是读数：`library` / `workspace` / 空串。哪一基准解析的必须能读出来，
    否则"工作区相对"与"library 相对"两种历史写法在下游看起来完全一样。
    """
    rel_text = str(rel or "").strip()
    if not rel_text:
        return ResolvedLiteraturePath(path=None, base="", candidates=(), reason="")

    library_dir = Path(library)
    tried: list[Path] = []
    lib_cand = _library_candidate(library_dir, rel_text)
    if lib_cand is not None:
        tried.append(lib_cand)
        if lib_cand.is_file():
            return ResolvedLiteraturePath(path=lib_cand, base=BASE_LIBRARY,
                                          candidates=tuple(tried), reason="")

    rel_posix = rel_text.replace("\\", "/")
    if rel_posix.startswith(WORKSPACE_PREFIX):
        ws_cand = _workspace_candidate(Path(root), rel_text)
        if ws_cand is not None:
            tried.append(ws_cand)
            if ws_cand.is_file():
                return ResolvedLiteraturePath(path=ws_cand, base=BASE_WORKSPACE,
                                              candidates=tuple(tried), reason="")

    return ResolvedLiteraturePath(path=None, base="", candidates=tuple(tried),
                                  reason=_missing_reason(rel_text, tried))


def bytes_on_disk(path: Path | str | None) -> int:
    """盘上那份文件的字节数；没有文件 / 不是普通文件 / 读不到 ⇒ 0。

    "读不到"按 0 算不是把两种东西折平：本函数只回答"有没有字节"，
    而"为什么读不到"由路径解析那一侧（`ResolvedLiteraturePath.reason`）说清楚。
    """
    if path is None:
        return 0
    p = Path(path)
    try:
        if not p.is_file():
            return 0
        return int(p.stat().st_size)
    except OSError:
        return 0


def fulltext_tier(*, bytes_on_disk: int | None,
                  pages: Sequence[str] | None) -> str | None:
    """`download.fulltext` 的三档现算；`None` = 有字节但这一处还没抽过文本。

    判据只有三条（顺序即优先级）：

    1. 没有字节（`bytes_on_disk` 为假值 / <= 0）⇒ `no_fulltext`；
    2. 有字节、且给了逐页文本，其中有任何一页去空白后非空 ⇒ `ok`；
    3. 有字节、给了逐页文本但一页可抽文本都没有（扫描件等）⇒ `no_text_layer`。

    `pages is None`（这一处没抽过）返回 `None`，不是上面三档里的任何一个：
    这是三态纪律的"没查成"，调用方必须用 :func:`with_fulltext` 清掉旧标签，
    而不是把一个猜测的档位落盘。
    """
    if not bytes_on_disk or int(bytes_on_disk) <= 0:
        return FULLTEXT_NO_FULLTEXT
    if pages is None:
        return None
    for page in pages:
        if str(page or "").strip():
            return FULLTEXT_OK
    return FULLTEXT_NO_TEXT_LAYER


def with_fulltext(download: dict | None, tier: str | None) -> dict:
    """把档位写进 `download` 栏；`tier is None` ⇒ 清掉旧的 `fulltext` 键。

    为什么写入与清除必须是同一处：改前只有写点、没有清除点，于是"这一行后来
    有字节了"之后旧标签还在（真机 6 条 `status=ok` 却写着没有全文）。这个函数是
    "写/清成对"的唯一实现 —— 两个调用点都调它，谁都不许自己 `dl["fulltext"] = ...`。
    """
    out = dict(download or {})
    if tier is None:
        out.pop("fulltext", None)
    else:
        out["fulltext"] = tier
    return out

# -*- coding: utf-8 -*-
"""文献读侧的两个口径：`literature.path` 落在哪个基准上，以及 `download.fulltext` 是哪一档。

## 为什么需要一个独立模块

这两件事各有一份"读侧真相"，而它们此前分处两端、各自漂过：

1. `literature.path` 有两个写入坐标系：`search_tools._adopt_file` 写着
   「相对路径优先按 `library/` 解释（表里存的就是这个坐标系），不存在再按 workspace
   解释」，而抽取入口 `agent_b.run_once` 只走 `store.library_path`（只认 `library/`）
   ⇒ 一条按工作区相对写下的 `library/000001/…` 被解析成 `library/library/000001/…`。
   写入侧的归一化不在这里（`schema.literature_path_problem` 与 `table_tools` 的
   归一化属 FC-27、人审）：本模块只负责让存量行读得回来 —— 历史行仍然带着那个前缀
   躺在盘上，读侧不认它就会把那篇文献判成 `file_missing`，而"文件真的不在"与
   "在另一个基准下"在读数上同形。
2. `download.fulltext` 的四个档只有写点、没有清除点：全仓只有
   `search_tools._mark_candidate_locator` 写过一个 `no_fulltext_this_time`，
   而 `status=ok` 的行照样一直挂着它。（2026-11-16 裁定 16 后第三档之外多了
   `extract_failed`：「抽过但失败」从此有落点；`garbled_text` 是乱码的唯一判据，
   `fulltext_tier` 与 `text.extract` 两边互认。）

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

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .schema import LIT_PATH_PREFIX

#: `download.fulltext` 的四档：有可抽文本 / 有字节但没有文本层 / 真的没有字节 /
#: 有字节但抽出来的不是可读文本（抽过但失败）。
#:
#: 第四档是业主 2026-11-16 裁定 16（「A」加 `extract_failed` 一档：抽过但失败要有落点）
#: 的落点。它替代的不是别的档，而是现场那个模型自拼的值：AH6 实测 07:44:26，
#: A 把 `download.fulltext` 写成 `pdf_no_text`、顺带把 `status` 写成 `downloaded`
#: ⇒ 写入被 `schema.DOWNLOAD_STATUSES` 整笔拒绝，随后被洗成 `status=ok/error=""`
#: —— 两次抽取都乱码这件事在盘上没有留下任何痕迹。所以这一档必须是受控取值：
#: 加在这一处（`FULLTEXT_TIERS` 是它的词表真身），不许模型现拼。
FULLTEXT_OK = "ok"
FULLTEXT_NO_TEXT_LAYER = "no_text_layer"
FULLTEXT_NO_FULLTEXT = "no_fulltext"
FULLTEXT_EXTRACT_FAILED = "extract_failed"
FULLTEXT_TIERS: tuple[str, ...] = (
    FULLTEXT_OK,
    FULLTEXT_NO_TEXT_LAYER,
    FULLTEXT_NO_FULLTEXT,
    FULLTEXT_EXTRACT_FAILED,
)

#: 可读性判据的唯一真身：`text.extract` 拒写乱码读它，`fulltext_tier` 判
#: `extract_failed` 读它，`scripts/seed_corpus.py --verify` 判种子也读它（改前
#: 种子验证另有一份 `_reading_of` / `_judge`：两边对同一份 PDF 给出相反结论，
#: 真机 lp-ball-15 的 7 份文献就是这样一边判拒、一边判 usable）。
#:
#: 判两件事，缺一不可：
#:   1. 噪声有没有越过"还能读"的界线（NUL / 替换字符 / 控制字符占比）；
#:   2. 有没有正文（字数 / 完整英文词 / 字母占比）—— 排除符号汤与只有标题页的
#:      扫描件。
#:
#: 为什么 NUL 不是"有就是乱码"（2026-11-21 实测，读数见
#: `temp/garbledchk/readings.json`）：PDF 文字层里少量 NUL 来自没有 ToUnicode
#: 映射的字形，正文照样可读。真读数：22 页论文 51416 字符里 77 个 NUL（0.15%）、
#: 426 页教材 781264 字符里 339 个（0.04%）、56 页综述 121668 字符里 1 个；这三份的
#: 完整英文词都在 2600 以上、字母占比 0.62 以上。改前 `nuls > 0` 把 25 份真种子
#: PDF 里的 8 份判成乱码（真机 lp-ball-15 那一批拒了其中的 7 份）。真乱码是
#: "成片"的：逐字节错位解码时 NUL 与不可打印字符大面积出现（实测随机字节解码后
#: 控制字符占 11.07%），所以三条都按占比判，阈值与实测可读样本留出数倍余量。
GARBLED_REPLACEMENT_MAX = 0
GARBLED_CONTROL_RATIO_MAX = 0.05
GARBLED_NUL_RATIO_MAX = 0.005

#: 正文的最低体量。它属"够不够一篇正文"，不属"是不是乱码"：一份干净的短文本
#: 不是乱码，`garbled_text` 不因它拒写（`text.extract` 对 `.txt` 直通），但
#: 种子验证与判收侧要的是整篇正文，于是把这一档如实报成 `too_short`。
READABLE_MIN_CHARS = 200
READABLE_MIN_LONG_WORDS = 20
READABLE_MIN_ALPHA_RATIO = 0.25

#: 控制字符（`ord < 32` 且不是换行/回车/制表）：交给正则的 C 层扫描。
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
#: 完整英文词（长度 >= 4 的那一档在 :func:`assess_text` 里再筛）。
_WORDS = re.compile(r"[A-Za-z][A-Za-z'\-]+")
_SPACES = re.compile(r"\s+")


def assess_text(text: str) -> dict:
    """一份正文的读数与判定（可读性判据的唯一实现，四条读数与四档判定都在这里）。

    `state` 四档，调用方按自己的口径取用：

    * `readable`：有体量、噪声在界内；
    * `too_short`：干净但不够一篇正文 —— `text.extract` 不因此拒写一份短文本，
      种子验证与判收侧据此判"不可用"；
    * `garbled`：噪声越界或符号汤（`text.extract` 判 `garbled_text`、拒写）；
    * `no_text_layer`：空白文本（扫描件；`text.extract` 另走 `no_text_layer` 一档）。

    返回字典同时是 `text.extract` 的 `quality` 读数，所以旧的五个键
    （`chars` / `nul_bytes` / `replacement_chars` / `control_chars` /
    `control_ratio`）一个不少。
    """
    body = str(text or "")
    total = max(1, len(body))
    nonspace = _SPACES.sub("", body)
    words = _WORDS.findall(body)
    long_words = [w for w in words if len(w) >= 4]
    alpha = sum(1 for ch in nonspace if ch.isalpha())
    nuls = body.count("\x00")
    replacement = body.count("\ufffd")
    control = len(_CONTROL_CHARS.findall(body))
    nul_ratio = nuls / total
    control_ratio = control / total
    alpha_ratio = round(alpha / len(nonspace), 4) if nonspace else 0.0
    state, why = _verdict(
        body=body, chars=len(body), nuls=nuls, nul_ratio=nul_ratio,
        replacement=replacement, control_ratio=control_ratio,
        long_words=len(long_words), alpha_ratio=alpha_ratio)
    return {
        "state": state,
        "why": why,
        "chars": len(body),
        "nonspace_chars": len(nonspace),
        "nul_bytes": nuls,
        "nul_ratio": round(nul_ratio, 6),
        "replacement_chars": replacement,
        "control_chars": control,
        "control_ratio": round(control_ratio, 6),
        "words": len(words),
        "long_words": len(long_words),
        "alpha_ratio": alpha_ratio,
    }


def _verdict(*, body: str, chars: int, nuls: int, nul_ratio: float,
             replacement: int, control_ratio: float, long_words: int,
             alpha_ratio: float) -> tuple[str, str]:
    """把读数折成四档之一 + 一句凭什么（阈值只在模块常量里，不在调用方）。"""
    if not body.strip():
        return "no_text_layer", "抽不到任何正文（空白）"
    if nul_ratio > GARBLED_NUL_RATIO_MAX:
        return "garbled", (
            f"NUL 占 {nul_ratio:.4%}（> {GARBLED_NUL_RATIO_MAX:.2%}，{nuls} 个）"
            "—— 成片的 NUL 是错位解码，不是个别字形缺映射")
    if replacement > GARBLED_REPLACEMENT_MAX:
        return "garbled", f"含 {replacement} 个 U+FFFD 替换字符（解码器认不出那个字节）"
    if control_ratio > GARBLED_CONTROL_RATIO_MAX:
        return "garbled", (
            f"控制字符占 {control_ratio:.4%}（> {GARBLED_CONTROL_RATIO_MAX:.2%}）"
            "—— 成片的不可打印字符是错位解码")
    if chars < READABLE_MIN_CHARS:
        return "too_short", (
            f"抽取正文只有 {chars} 字符（< {READABLE_MIN_CHARS}）"
            "—— 干净但不够一篇正文")
    if long_words < READABLE_MIN_LONG_WORDS:
        return "garbled", (
            f"完整词只有 {long_words} 个（< {READABLE_MIN_LONG_WORDS}，"
            "是符号/单字母串形态）")
    if alpha_ratio < READABLE_MIN_ALPHA_RATIO:
        return "garbled", (
            f"字母占比 {alpha_ratio}（< {READABLE_MIN_ALPHA_RATIO}，"
            "是符号/单字母串形态）")
    return "readable", ""


def garbled_text(text: str) -> tuple[bool, dict]:
    """核一遍"这段文本是不是乱码"。返回 `(是否疑似乱码, 读数)`。

    这是"乱码"这件事的唯一判据：`text.extract` 拒写乱码读它，`fulltext_tier`
    判 `extract_failed` 也读它，种子验证读的是同一个 :func:`assess_text`。
    短文本（`too_short`）不算乱码：短不等于坏，够不够整篇是另一件事。
    """
    reading = assess_text(text)
    return reading["state"] == "garbled", reading


#: `path_base` 的两个取值：这一条 `literature.path` 是按哪个基准解析出来的。
BASE_LIBRARY = "library"
BASE_WORKSPACE = "workspace"

#: 只有以它开头的串才允许按 workspace 基准回退（见模块 docstring）。
#: 取值不在这里另写一遍：`schema.LIT_PATH_PREFIX` 是"这一格不该带它"的唯一声明
#: （写入闸拒的就是这个前缀）—— 读侧要认的正是同一串，两处各写一个 `"library/"`
#: 早晚会漂。
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
                  pages: Sequence[str] | None,
                  text: str | None = None,
                  garbled: bool | None = None) -> str | None:
    """`download.fulltext` 的四档现算；`None` = 有字节但这一处还没抽过文本。

    判据（顺序即优先级）：

    1. 没有字节（`bytes_on_disk` 为假值 / <= 0）⇒ `no_fulltext`；
    2. 抽出来的文本被判成乱码（`garbled=True`，或给了 `text` 现判）⇒ `extract_failed`
       —— 这是裁定 16 的第四档：抽过、但抽出来的不是可读文本；
    3. 有字节、给了逐页文本/整段文本，其中有任何一页去空白后非空 ⇒ `ok`；
    4. 有字节、给了文本但一页可抽文本都没有（扫描件等）⇒ `no_text_layer`。

    `pages is None and text is None`（这一处没抽过）返回 `None`，不是上面四档里的任何
    一个：这是三态纪律的"没查成"，调用方必须用 :func:`with_fulltext` 清掉旧标签，
    而不是把一个猜测的档位落盘。
    """
    if not bytes_on_disk or int(bytes_on_disk) <= 0:
        return FULLTEXT_NO_FULLTEXT
    if garbled is None and text is not None:
        garbled = garbled_text(text)[0]
    if garbled:
        return FULLTEXT_EXTRACT_FAILED
    if pages is None and text is None:
        return None
    if text is not None and str(text).strip():
        return FULLTEXT_OK
    for page in pages or ():
        if str(page or "").strip():
            return FULLTEXT_OK
    return FULLTEXT_NO_TEXT_LAYER


def with_fulltext(download: dict | None, tier: str | None) -> dict:
    """把档位写进 `download` 栏；`tier is None` ⇒ 清掉旧的 `fulltext` 键。

    为什么写入与清除必须是同一处：只有写点、没有清除点，"这一行后来有字节了"之后
    旧标签还在。这个函数是"写/清成对"的唯一实现 —— 两个调用点都调它，谁都不许自己
    `dl["fulltext"] = ...`。
    """
    out = dict(download or {})
    if tier is None:
        out.pop("fulltext", None)
    else:
        out["fulltext"] = tier
    return out

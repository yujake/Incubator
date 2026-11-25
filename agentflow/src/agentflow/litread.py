# -*- coding: utf-8 -*-
"""文献读侧的两个口径：`literature.path` 落在哪个基准上，以及 `download.fulltext` 是哪一档。

## 为什么需要一个独立模块

这两件事各有一份"读侧真相"，而它们此前分处两端、各自漂过：

1. `literature.path` 只有一个读侧口径（2026-11-22 业主裁定「旧工作区不必兼容」）：
   扁平落点 `<内容 hash 前缀>-<名>`，相对 `library/`（`locallib.library_landing_name`）。
   唯一真身是 `store.Store.library_path` —— 它同时是写侧落地闸与工具面的读口。
   本模块的 :func:`resolve_literature_path` 是它在抽取 / 回验 / 审计那几条路上的
   同一条判据：同一种形态、同一个基准、同一句拒词。
2. `download.fulltext` 的四个档只有写点、没有清除点：全仓只有
   `search_tools._mark_candidate_locator` 写过一个 `no_fulltext_this_time`，
   而 `status=ok` 的行照样一直挂着它。（2026-11-16 裁定 16 后第三档之外多了
   `extract_failed`：「抽过但失败」从此有落点；`garbled_text` 是乱码的唯一判据，
   `fulltext_tier` 与 `text.extract` 两边互认。）

## 2026-11-22 之后：只有扁平落点（旧形态明确"不再支持"）

改前这里是双基准：先 `library/`，再为以 `library/` 开头的串回退 workspace。
而 `store.library_path` 在同一时刻已经严格（旧形态 ⇒ 「旧布局（不再支持）」）——
于是同一份 `literature.path`，一条读路拒、另一条收：写侧说"这个写法不合法"，
B 却照旧把那份文件抽成了概念；5 个测试文件用旧分目录夹具仍然"绿"，因为它们
测的是宽容的那条路（B2a 实测）。业主裁定「旧工作区不必兼容」之后，那个回退分支
整段删掉：它只服务过旧前缀形态（`library/…`），而那一形态正是写入闸拒的形态。

三态纪律在这里的具体形态（不静默）：

* 旧形态（`<lit_id>/<名>`、带 `library/` 前缀）⇒ `path is None` + `reason` 逐字带
  「旧布局（不再支持）」，`candidates` 为空 —— 不折成 `file_missing`（"路径写旧了"
  与"文件不见了"处置相反），也不返回一个解析得到的路径（那就等于继续支持它）。
* 越界（绝对路径 / `..` 绕出 `library/`）⇒ `path is None` + `reason` 说越界。
* 扁平形态、文件不在 ⇒ `path is None` + `candidates` 里有那一条绝对路径 +
  `reason` 以 `file_missing` 开头。

`root` 形参保留（几条调用方原样传）：工作区根不再参与解析 —— 唯一基准是 `library/`。

两边各写一份判据，迟早会出现第三种口径。所以这里只收两件事的实现：

* :func:`resolve_literature_path`：按 `store.Store.library_path` 的同一套形态判据
  解析（扁平相对 `library/` 钉在工作区之内）；两条读路给同一个结论这件事由
  `tests/test_litread_and_library_path_give_the_same_answer.py` 逐形态对拍钉住 ——
  任何一侧让步（把这里改回双基准 / 把 store 的旧形态判据摘掉）那条判据当场红。
* :func:`fulltext_tier` / :func:`with_fulltext`：三档现算（`ok` /
  `no_text_layer` / `no_fulltext`），以及"写入与清除成对"的那一半 ——
  有字节但这一处还没抽过文本时不算档（返回 `None`），由 :func:`with_fulltext`
  把旧标签清掉，而不是猜一个档位或把上次的标签留着。

`None` 不是"没有全文"，是"这一处判不了"。
把它折成 `no_fulltext` 会让 `status=ok` 的行重新出现"有字节却没有全文"的自相矛盾；
把它折成 `ok` 则会让扫描件被记成可引用。两者都是把"没查成"说成了结论。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
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

#: 抽读件里页与页之间的分隔标记（`text.extract` 与 `locallib.ingest_directory` 共用）。
#: 为什么收在 `litread`：`locallib` 与 `tools/text_tools.py` 都要写抽读件，两处各拼一份
#: 标记格式，下一次只改一处就会让两份 `.txt` 的页号对不上（逐字引文按页定位）。
PAGE_MARKER = "===== page {n} ====="


def marked_pages(pages: Sequence[str] | None) -> str:
    """逐页文本 → 带页标记的正文（写抽读件的唯一格式：页间插标记、每页去尾空行、收尾一个换行）。"""
    blocks: list[str] = []
    for i, text in enumerate(pages or (), 1):
        blocks.append(PAGE_MARKER.format(n=i))
        blocks.append(str(text or "").rstrip("\n"))
    if not blocks:
        return ""
    return "\n".join(blocks).strip("\n") + "\n"


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


#: `path_base` 的取值：这一条 `literature.path` 是按哪个基准解析出来的。
#: 只有 `library` 一个基准（工作区回退分支已删）。
BASE_LIBRARY = "library"
#: 历史读数：改前那条 workspace 回退分支留下的基准名。现在不再产出
#: （回退只服务过旧前缀形态，而旧形态现在明确"不再支持"）。名字留着有两个理由：
#: `verify.py` 还拿它比一次（那次比较现在恒假 —— 拒绝发生在解析之前），
#: 以及历史报告里的 `path_base=workspace` 要读得懂。任何新代码都不许再产出它。
BASE_WORKSPACE = "workspace"

#: 旧前缀形态的识别串：写入闸（`schema.LIT_PATH_PREFIX`）拒的就是这个前缀，
#: 读侧要认的正是同一串 —— 两处各写一个 `"library/"` 早晚会漂。
WORKSPACE_PREFIX = LIT_PATH_PREFIX

#: 受控拒的判词（逐字）。与 `store.Store.library_path` 的拒信同源：
#: "这个写法不合法"与"文件不见了"必须说成两句话，处置相反。
RETIRED_LAYOUT_NOTE = "扁平落点已退役（2026-11-25 起回归 `<6位号>/<名>`）"

#: `literature.path` 的四种形态（与 `store.Store.library_path` 同一套判据的读数面）。
#: 为什么要一个显式的形态分类：读侧要"宽容两档历史形态、只拒非法形状"，
#: `wellformed` 要"规范报 ok、历史报 legacy、其余报 malformed" —— 两条路必须对同一个
#: 分类说话，各写一份 `split("/")` 就是下一次漂移的起点。
SHAPE_ENTRY = "entry"                  # `<6位号>/<名>`（规范）
SHAPE_LEGACY4 = "legacy4"              # `<4位号>/<名>`（p9 那批老盘）
SHAPE_LEGACY_FLAT = "legacy_flat"      # 一位扁平 `<内容 hash 前缀>-<名>`（B2a 落点，已退役）
SHAPE_BAD = "bad"                      # 带斜杠但首段不是 2–6 位数字 / 段数不对
SHAPE_UNJUDGED = ""                    # 空路径：没有形态可判


def path_shape(rel: str | None) -> str:
    """一条 `literature.path` 的形态（:data:`SHAPE_ENTRY` 等五档之一）。

    * `entry`：`<6位号>/<名>` —— 现行规范（2026-11-25 业主裁定）；
    * `legacy4`：`<4位号>/<名>` —— p9 那批 4 位号时代的老盘，读得通；
    * `legacy_flat`：一位的扁平名（含 `<内容 hash 前缀>-<名>`）—— B2a 的落点，已退役，
      但旧工作区（lp-ball-15/22）还要读得通；
    * `bad`：带斜杠而首段不是 2–6 位数字、或段数 > 2（含带 `library/` 前缀的事故写法）；
    * 空路径 ⇒ 空串（没有形态可判，调用方不据此报错）。
    """
    text = _normalized(rel)
    if not text:
        return SHAPE_UNJUDGED
    if text.startswith(WORKSPACE_PREFIX):
        return SHAPE_BAD
    parts = [p for p in text.split("/") if p]
    if len(parts) == 1:
        return SHAPE_LEGACY_FLAT
    if len(parts) != 2:
        return SHAPE_BAD
    head = parts[0]
    if not (head.isdigit() and 2 <= len(head) <= 6):
        return SHAPE_BAD
    return SHAPE_ENTRY if len(head) == 6 else SHAPE_LEGACY4


@dataclass(frozen=True)
class ResolvedLiteraturePath:
    """一条 `literature.path` 的解析结果。

    `path is None` 时三个字段是这样分工的：`base` 为空串（没有解析出来），
    `candidates` 是试过的绝对路径（0 个或 1 个；非法形状与越界给 0 个），
    `reason` 是写进 `last_mine_error` / 审计读数的那句话 ——

    * 非法形状 ⇒ 逐字带 :data:`RETIRED_LAYOUT_NOTE`（不是 `file_missing`：处置相反）；
    * 越界 ⇒ 「文献路径越出 library/」（与 `store.Store.library_path` 同一句）；
    * 文件不存在 ⇒ 以 `file_missing` 开头，候选绝对路径在里面。

    `shape` 是 :func:`path_shape` 的分类（解析成功时也带着：读侧要能说"读到的是历史
    形态"而不是把它当规范 —— 三态纪律：读得通不等于形态合规）。
    """

    path: Path | None
    base: str
    candidates: tuple[Path, ...]
    reason: str
    shape: str = SHAPE_UNJUDGED

    @property
    def found(self) -> bool:
        """解析到了一份盘上的普通文件。"""
        return self.path is not None

    @property
    def legacy(self) -> bool:
        """读到的是一个历史形态（`legacy4` / `legacy_flat`）。"""
        return self.shape in (SHAPE_LEGACY4, SHAPE_LEGACY_FLAT)


def _normalized(rel: str | None) -> str:
    """`literature.path` 的形态判据输入：与 `store.Store.library_path` 逐字同一套归一。

    `\\` ⇒ `/`（Windows 上两种写法是同一个路径）、去两端空白、反复剥 `./`。
    为什么归一化只有这一处：下面 :func:`path_shape` 与 store 的判据都吃它的输出，
    两处各写一遍"剥几层 `./`"必然分家（`././000000/x.pdf` 就是一个例子）。
    """
    text = str(rel or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def text_rel(rel: str) -> str:
    """原件的库内相对名 ⇒ 它的抽读件：同目录、同 stem、`.txt`（唯一实现）。

    现行规范（2026-11-25）里抽读件与原件住同一条文献目录：

        library/000003/paper.pdf  →  library/000003/paper.txt

    旧的扁平层 `library/000003.txt` 已退役；抽读件的位置不再由文献号单独决定，
    而是跟着原件走。`text.extract` 写它、`wellformed` 判它、`fs.read` 的路由找它。
    """
    text = str(rel or "").replace("\\", "/").strip()
    if not text:
        return ""
    p = PurePosixPath(text)
    return str(p.with_suffix(".txt"))


def legacy_note(rel: str | None) -> str:
    """历史形态的说明（空串 = 不是历史形态）。给读数用，不是拒词。

    两档历史形态都读得通，但都不许再写：

    * `<4位号>/<名>` —— p9 那批 4 位号时代的老盘（`wellformed` 报 legacy）；
    * 一位扁平名（含 `<内容 hash 前缀>-<名>`）—— B2a（2026-11-22）的落点，
      自 2026-11-25 起退役（lp-ball-15/22 这类历史数据还要读得通，所以不报 error）。
    """
    shape = path_shape(rel)
    if shape == SHAPE_LEGACY4:
        return ("遗留形态（读得通、新写不产出）：`<4位号>/<名>` —— 4 位号时代的老盘"
                "（p9 那批）；规范形态是 `<6位号>/<名>`（2026-11-25 业主裁定）")
    if shape == SHAPE_LEGACY_FLAT:
        return ("遗留形态（读得通、新写不产出）：扁平 `<内容 hash 前缀>-<名>` —— "
                "B2a（2026-11-22）的落点，自 2026-11-25 起退役；"
                "规范形态是 `<6位号>/<名>`")
    return ""


def _library_candidate(library: Path, rel: str) -> Path | None:
    """按 `library/` 基准解析；越出 `library/` 的写法在这里被拒（`None`）。"""
    try:
        cand = (library / rel).resolve()
    except OSError:
        return None
    try:
        cand.relative_to(library.resolve())
    except ValueError:
        return None
    return cand


def _missing_reason(rel: str, candidates: Sequence[Path]) -> str:
    """`file_missing` 的逐字原因：候选绝对路径一个都不许省。"""
    paths = [str(p) for p in candidates]
    if not paths:
        return f"file_missing: 没有可解析的候选（path={rel!r}）"
    return f"file_missing: {paths[0]}"


def resolve_literature_path(root: Path | str, library: Path | str,
                            rel: str | None) -> ResolvedLiteraturePath:
    """把一条 `literature.path` 解析成盘上的文件（唯一基准：`library/`）。

    与 `store.Store.library_path` 是同一套形态判据（那是唯一真身）：

    * 规范形态 `<6位号>/<名>` ⇒ 解析；
    * 历史形态 `<4位号>/<名>`、一位扁平名 ⇒ 照样解析（读得通），
      结果里 `shape` 标明它是哪一档（`legacy` 为真）—— 读侧不许假装它合规；
    * 非法形状（带斜杠而首段不是 2–6 位数字 / 段数 > 2 / 带 `library/` 前缀）⇒
      明确 :data:`RETIRED_LAYOUT_NOTE`，不静默返回、也不折成 `file_missing`；
    * 越界（绝对路径 / `..`）⇒ 「文献路径越出 library/」。

    `root` 形参保留但不再参与解析（工作区基准那条路已删：它只服务过旧前缀形态）。
    留着它是因为三条调用方（`agent_b/run_once`、`verify`、`table_tools`）与
    `litavail.tier_of_literature` 都原样传"工作区根 + 库根"两个位置参数 ——
    改签名会让它们各自再拼一次，而"路径怎么拼"正是本模块要收口的东西。
    """
    rel_text = str(rel or "").strip()
    if not rel_text:
        return ResolvedLiteraturePath(path=None, base="", candidates=(), reason="")

    shape = path_shape(rel_text)
    if shape == SHAPE_BAD:
        return ResolvedLiteraturePath(
            path=None, base="", candidates=(), shape=shape,
            reason=(f"{RETIRED_LAYOUT_NOTE}：文献路径 {rel_text!r} 不是 "
                    "「<6位号>/<文件名>」两段式（带斜杠而首段不是 2–6 位数字，"
                    "或段数不对，或带了 `library/` 前缀）"))
    if shape == SHAPE_UNJUDGED:
        return ResolvedLiteraturePath(path=None, base="", candidates=(), reason="")

    text = _normalized(rel_text)
    library_dir = Path(library)
    cand = _library_candidate(library_dir, text)
    if cand is None:
        # 越界：与 `store.Store.library_path` 的拒信同一句（"路径非法"不是"文件不在"）。
        return ResolvedLiteraturePath(path=None, base="", candidates=(), shape=shape,
                                      reason=f"文献路径越出 library/：{rel_text!r}")
    if cand.is_file():
        return ResolvedLiteraturePath(path=cand, base=BASE_LIBRARY,
                                      candidates=(cand,), reason="", shape=shape)
    return ResolvedLiteraturePath(path=None, base="", candidates=(cand,), shape=shape,
                                  reason=_missing_reason(text, (cand,)))


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

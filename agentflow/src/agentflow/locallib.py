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
   `unreadable`，不给它编一行"登记成功、内容为空"的记录。2026-11-20 起这一档也是
   判收闸：抽出来是乱码 / 没有文本层 / 全空页的文件不进 `literature`（判据是
   `litread.fulltext_tier`，与 `text.extract` 拒写乱码同一份实现）；进了库的行则带上
   `download.fulltext=ok` —— "这一行有没有可读正文"在行上读得出来，不靠下游再抽一次
   才发现。口径出处：业主 2026-11-20「读内容才能判东西」，落点
   `litavail.ADMITTABLE_TIERS=(readable,)`。

## 边界

- 只认本机文件系统上的目录，不下载、不联网。
- 不做 OCR：扫描版 PDF 不会以"没有文本层"登记（那正是上面第 3 条挡掉的），
  `counts.unreadable` 里能看到它、note 写着 `no_text_layer`；要收它就先 OCR 再登记。
- `--limit` 是给真实跑用的预算闸门（一本书可能几百页、几十万字符），
  不是"只处理前 N 本"的语义糖：超出的书不会被登记，清单里逐本写明为什么。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import dedup as D
from . import interactions as I
from . import litread as LR
from . import schema as S
from . import sysresidue as _SR   # SYSRESIDUE ④：`_keys` / `dedup_key` 只有一处算（与 A、search 同源）
from .extract import extract_text
from .store import Store

__all__ = [
    "BookPlan",
    "DECLARATION_ABSENT",
    "DECLARATION_NAME",
    "DECLARATION_READ",
    "DECLARATION_UNREADABLE",
    "DROP_ZONES",
    "IngestReport",
    "LocalHit",
    "content_duplicates_across_entries",
    "declaration_path",
    "declaration_verdict",
    "excerpt_for",
    "in_drop_zone",
    "ingest_directory",
    "is_declared",
    "keeps_original",
    "land_read_text",
    "library_landing",
    "library_landing_name",
    "library_name_of",
    "list_books",
    "local_fetch_fn",
    "read_declaration",
    "strip_landing_hash",
    "search_fn_for_store",
    "selftest",
    "sha256_file",
    "undeclared_workspace_books",
]

#: 单本默认上限字节数（超过就跳过并说明），避免一次跑把 17 MB 的书整本喂进模型。
DEFAULT_MAX_BYTES = 24 * 1024 * 1024

_SAFE_RE = re.compile(r"[^0-9A-Za-z._\u4e00-\u9fff-]+")

#: 工作区根上那份「用户点名了哪些可靠参考文献」的声明（M 落盘，A 只读）。
#:
#: 形状：`{"paths": ["a.pdf", "b/"], "verbatim": "<用户原话>"}`。它是唯一的入库
#: 白名单：用户提示词里没点名的文件只能是研究参考，不许进 `literature`。
DECLARATION_NAME = "RELIABLE-REFERENCES.json"

#: 声明判据的三态（`declaration_verdict` 的 `state`；唯一词表）。
#:
#: * `DECLARATION_READ` —— 声明在盘上、读得出来：这一档才有 `paths` 可匹配；
#: * `DECLARATION_ABSENT` —— 声明不在盘上：用户没点名（fail-closed，一份都不许入库）；
#: * `DECLARATION_UNREADABLE` —— 声明在盘上但读不出来 / 形状不对：没查成（unchecked），
#:   既不能折成「用户没点名」，也不能折成「用户点名了」。
#:
#: 为什么单列这三个名字：调用方（`search.ingest_local` 与 `search.register`）都要按
#: 三态给不同的读数与拒因；各写一份字面量迟早会漂，而漂了不会报错。
DECLARATION_READ = "read"
DECLARATION_ABSENT = "absent"
DECLARATION_UNREADABLE = "unreadable"


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


# --------------------------------------------------------------------------- #
# 唯一落点：`library/<文献号>/<清洗过的原名>`（2026-11-25 业主裁定；推翻 B2a）
# --------------------------------------------------------------------------- #
#
# ## 现行规范（业主 2026-11-25 原话：「<6位号>/<名> 回归正确形态」）
#
# 一个文献一条目录，目录名就是文献号；原件与抽出的正文都住在这条目录里：
#
#     library/000003/critical-central-sections-of-the-cube.pdf    ← 原件（path 指它）
#     library/000003/critical-central-sections-of-the-cube.txt    ← 抽出的正文（同 stem）
#
# `literature.path` 存的是「相对 `library/` 的相对名」：`<6位号>/<文件名>`（恰好一段斜杠）。
#
# ## 被推翻的旧裁定（B2a，2026-11-22：扁平 `<内容 hash 前缀>-<名>`）
#
# 旧裁定的理由是「每个 lit_id 一个目录会在库里留下空目录」（`draft/28` R-49：真机 98 行
# 留下 60 个空目录）。2026-11-25 复核：R-49 判的是「登记时无条件 mkdir」，不是「分目录」
# 本身 —— 空目录的根因是建目录与搬字节分离（`agent_a.py:516-518` 在还没有字节时就 mkdir）。
# 新规范里建目录的唯一责仍归「真有字节要落」的那一步（`library_landing` 的调用方），
# 所以「98 行 60 个空目录」不会随分目录回来。
#
# 旧形态的处置（读侧三态，见 `wellformed/literature.py` 的 `literature.layout`）：
#   * `<6位号>/<名>` ⇒ ok；
#   * `<4位号>/<名>` ⇒ legacy（p9 那批老盘是 4 位号时代）；
#   * 扁平一段       ⇒ legacy（lp-ball-15/22 的历史数据；自 2026-11-25 起退役，新写不产出）。
#
# 写侧只有一处落点实现（本节的 `library_landing_name` / `library_landing`），三个写者
# （`search_tools._adopt_file`、`locallib.ingest_directory`、`agent_a.core._attach_staged`）
# 都调它，且都必须把已经分配好的 `lit_id` 交进来 —— 不许先落一个临时名再改名。

#: 落点目录名：4 位（p9 那批老盘，legacy）或 6 位（新发号）。
_ENTRY_ID_RE = re.compile(r"^\d{4}$|^\d{6}$")


#: 内容 sha256 的合法形态（64 位小写十六进制）。
#:
#: 落点身份的第一判据是内容，所以这个形态必须是判据而不是"调用方大概会传对"：
#: 传一个 12 位短哈希进来，`_same_content_in_entry` 会拿它去比 64 位全哈希、
#: 永远不相等 ⇒ "内容优先"静默退化成"按名字落"，而盘上照样成功、没有任何读数报出来。
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _size_or_none(path: Path | str) -> int | None:
    """`path` 的字节数（读不到 ⇒ None）。只用作哈希预筛，不参与任何判定。"""
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


def _same_content_in_entry(entry_dir: Path, want: str, size: int | None = None) -> Path | None:
    """`entry_dir` 里内容就是 `want` 的那一份（按名字排序取第一份；没有 ⇒ None）。

    "内容 sha 优先"的唯一实现：落点身份先问内容、再问名字。`size` 只是省哈希的预筛
    —— 同内容必同字节数，所以它不改变判据、只少读盘（`library/` 里一条文献目录通常
    只有 `<stem>.pdf` + `<stem>.txt` 两份，但历史目录可能有十几份）。
    """
    if not entry_dir.is_dir():
        return None
    try:
        files = sorted((p for p in entry_dir.iterdir() if p.is_file()), key=lambda p: p.name)
    except OSError:  # 目录读不了 ⇒ 当作"没有同内容"，由调用方按名字落（fail-open 只影响去重，不影响写入）
        return None
    for p in files:
        if size is not None and _size_or_none(p) != size:
            continue
        try:
            if sha256_file(p) == want:
                return p
        except OSError:
            continue
    return None


def content_duplicates_across_entries(library: Path | str, sha256_hex: str, *, lit_id: str,
                                      source_size: int | None = None) -> list[str]:
    """同一份字节在别的文献号目录里的落点（跨号重复读数；只读，不判错）。

    ## 为什么这是"读数"而不是"拒绝"

    同一份字节落两个文献号，可能是两条真实不同的题录：预印本与期刊版、会议版与
    期刊版、或者一条按题名收、一条按 DOI 收的同一篇。本路不改"可引/不可引"，也不
    替人判"这两行该不该并"，所以允许它发生。但允许不等于静默：落点函数把这个
    读数交给调用方，写者把它记进回执（`agent_a.run_once` 的 `download.same_bytes_other_entry`
    事件）。没有这条读数时，盘上"同一份字节两份文件"与"两份不同的文献"长得一模一样
    —— 真机 2026-11-25 21:23 的事故就是从这种同形里长出来的。

    返回相对 `library/` 的名字（排好序）；`lit_id` 自己那一条不算。
    `source_size` 是哈希预筛（同内容必同字节数）。
    """
    want = str(sha256_hex or "").strip().lower()
    if not _SHA256_RE.fullmatch(want):
        raise ValueError(
            f"内容 hash 必须是 64 位小写十六进制（收到 {sha256_hex!r}）—— "
            "跨号重复的判据要靠它")
    base = Path(library)
    own = str(lit_id or "").strip()
    if not base.is_dir():
        return []
    out: list[str] = []
    try:
        entries = sorted((p for p in base.iterdir()
                          if p.is_dir() and _ENTRY_ID_RE.match(p.name)),
                         key=lambda p: p.name)
    except OSError:
        return []
    for entry in entries:
        if entry.name == own:
            continue
        hit = _same_content_in_entry(entry, want, source_size)
        if hit is not None:
            out.append(hit.relative_to(base).as_posix())
    return out


def library_landing_name(source: Path | str, lit_id: str, *,
                         library: Path | str | None = None,
                         sha256_hex: str | None = None) -> str:
    """新收编的一份字节在 `library/` 下的相对名：内容 sha 优先，名字只是第二判据。

    ## 判定顺序（"落点身份"的全部）

    ① 内容（传了 `library` + `sha256_hex` 才判这一档）：`library/<文献号>/` 下已经
       有同 sha 的一份 ⇒ 返回那一份的名字。⇒ 同一份字节在同一个文献号目录里
       只能有一个名字；名字差异（两个写者各给一个 `hint`）不得产生第二份文件。
    ② 名字：没有同内容的 ⇒ `<文献号>/<清洗过的原名>`（`_safe_name`：保留扩展名、
       把 Windows 非法字符换成 `_`）。
    ③ 撞名：②那个名字已被另一份不同内容占着 ⇒ 由 `library_landing` 追加内容
       短哈希（绝不覆盖既有文件）。

    为什么 ①先于②、而不是"按名字找到再看内容"：落点的身份是"这条文献的那一份字节"，
    不是"谁先给它起了什么名"。同一份 arXiv PDF 会被两个写者用两个 `hint` 各下一次
    （`search.download` 用模型给的 `hint`、`run_once` 补下载用 `slugify(title)`），
    按名字判就必然落成两份，且第二份没有任何 `literature` 行指到它（真机 2026-11-25
    21:23:46 现场：两份 217352 B、sha256 全等 `62DC8BA5…` 的 PDF 同住 `library/000001/`，
    行上 `path` 只指其中一份）。①落地之后，任何写者、任何名字、任何次数的重复
    写入都收敛到同一份文件。

    `lit_id` 必须是已经分配好的文献号（4 位老号 / 6 位新号）：落点与登记行用同一个号，
    否则盘上会出现「目录叫 A、行上号是 B」的第二套名字。三个写者都在事务里先
    `tx.alloc_id("lit")` 再调本函数。

    不给 `library` / `sha256_hex` 的调用（读侧、以及 B 给抽读件起名的那一处
    `agent_b/core.py`）走 ②，形态与 2026-11-25 裁定逐字相同：`<文献号>/<清洗名>`。
    """
    lid = str(lit_id or "").strip()
    if not _ENTRY_ID_RE.match(lid):
        raise ValueError(
            f"落点目录名必须是文献号（4 位老号 / 6 位新号），收到 {lit_id!r} —— "
            "`library/<文献号>/<名>` 是现行规范（2026-11-25），没有号就没有目录名")
    want = str(sha256_hex or "").strip().lower()
    if library is not None and want:
        if not _SHA256_RE.fullmatch(want):
            raise ValueError(
                f"内容 hash 必须是 64 位小写十六进制（收到 {sha256_hex!r}）—— "
                "内容优先的判据要靠它")
        base = Path(library)
        hit = _same_content_in_entry(base / lid, want, _size_or_none(source))
        if hit is not None:
            return hit.relative_to(base).as_posix()
    return f"{lid}/{_safe_name(Path(source))}"


#: 历史扁平落点里的内容 hash 前缀（8..64 位十六进制；`strip_landing_hash` 认它）。
#:
#: 新布局（`<文献号>/<清洗名>`）不再往名字里拼 hash，所以这条正则只服务两件事：
#: ① 读旧工作区（lp-ball-15/22 那批扁平文件）时把 hash 前缀剥掉，与源文件名对齐；
#: ② `agent_prompts._local_material_key` 判"这份材料入编了没有"时两边的形态能对上。
#: 它不再参与任何写侧决定 —— 写侧落点名只有 `library_landing_name` 一处。
_LANDING_PREFIX_RE = re.compile(r"^[0-9a-f]{8,64}$")


def library_name_of(source: Path | str) -> str:
    """源文件名 → 它在 library/ 落点里的「名」部分（清洗过、不含内容 hash 前缀）。

    落点名是 `<内容 hash 前缀>-<这个名>`。读侧要拿盘上的源文件名去比 `literature.path`
    （`agent_prompts._pending_local_materials` 判"这份材料入编了没有"），而清洗规则
    必须与写侧同一处 —— 所以它是本模块的公开面，不是给调用方再抄一份正则。
    """
    return _safe_name(Path(source))


def strip_landing_hash(landing: str) -> str:
    """把历史扁平落点的内容 hash 前缀剥掉：`<8..64 位 hex>-<名>` ⇒ `<名>`；否则原样返回。

    只服务读旧工作区（lp-ball-15/22 那批 B2a 扁平文件）与"这份材料入编了没有"那条读数：
    新布局 `<文献号>/<清洗名>` 不再往名字里拼 hash，所以本函数对新数据是恒等变换。
    碰上 `library_landing` 最后"内容短哈希 + 同名"那一档（`<名>-<8 位 hex>` 在后面）
    时这里不剥 —— 那种名字在磁盘上仍然是一份可读文件，读侧认不出它的"源名"是可接受的。
    """
    text = str(landing or "")
    head, sep, rest = text.partition("-")
    if sep and rest and _LANDING_PREFIX_RE.match(head):
        return rest
    return text


def library_landing(library: Path | str, source: Path | str,
                    sha256_hex: str, *, lit_id: str,
                    reading: dict | None = None) -> tuple[str, Path]:
    """一条新收编的字节的落点：`(library 相对名, 绝对落点)`，内容 sha 优先、绝不覆盖。

    三个写者共用这一个函数（`search_tools._adopt_file`、`ingest_directory`、
    `agent_a.core._attach_staged`）：身份顺序与名字形态由 `library_landing_name` 一处给，
    本函数只多做两件事 ——
    ① 目标（无论是"同内容既有的那一份"还是"按名字该落的那一份"）已存在且内容相同
       ⇒ 直接复用它（同一份字节不搬第二份）。这一条就是"同一份字节、两次不同 `name`、
       同一个 `lit_id` ⇒ 只有一个文件"的实现：内容先命中时 `library_landing_name`
       已经把名字换回既有那一份的名字，本函数只把 `reused=True` 记进回执；
    ② 名字撞上而内容不同 ⇒ 追加内容短哈希（8 → 16 → 32 → 64 位），最后带
       「源文件 + 内容」的短哈希，一个既有文件都不覆盖（覆盖会毁掉已建立的引文定位）。

    ## `reading` 是落点回执（可选出参，不参与判定）

    `{"rel": str, "sha256": str, "reused": bool, "duplicate_in": [<别的文献号>/<名>, …]}`。
    `reused=True` = "这份字节已经在库里，本次零写入"；`duplicate_in` = 同一份字节在
    别的文献号目录里的落点（跨号重复读数，判据见 `content_duplicates_across_entries`
    —— 允许、但不许静默）。写者拿它落事件/回执：真机 2026-11-25 21:23 的事故形态正是
    "盘上多两份、行上不留痕"，回执要回答"谁、什么 URL、写到哪、为什么"。

    它不建目录、也不搬字节：谁写（`copy2` / `move`）谁负责 `dest.parent.mkdir(...)`。
    """
    want = str(sha256_hex or "").strip().lower()
    if not _SHA256_RE.fullmatch(want):
        raise ValueError(
            f"内容 hash 必须是 64 位小写十六进制（收到 {sha256_hex!r}）—— "
            "同名不同内容的判据要靠它")
    base = Path(library)
    src = Path(source)
    lid = str(lit_id or "").strip()
    size = _size_or_none(src)
    # ① 内容优先：`library_landing_name` 先看 `<lid>/` 下有没有同 sha 的一份。
    rel = library_landing_name(src, lid, library=base, sha256_hex=want)
    dest = base / rel
    reused = dest.is_file() and sha256_file(dest) == want
    if not reused and dest.exists():
        # ② 名字被另一份不同内容占着 ⇒ 追加内容短哈希，既有文件一个字节都不动。
        stem = Path(_safe_name(src))
        for chars in (8, 16, 32, 64):
            alt = f"{lid}/{stem.stem}-{want[:chars]}{stem.suffix}"
            cand = base / alt
            if not cand.exists():
                rel, dest, reused = alt, cand, False
                break
            if cand.is_file() and sha256_file(cand) == want:
                rel, dest, reused = alt, cand, True
                break
        else:
            tail = hashlib.sha256(f"{src}|{want}".encode("utf-8")).hexdigest()[:8]
            alt = f"{lid}/{stem.stem}-{tail}{stem.suffix}"
            rel, dest, reused = alt, base / alt, False
    if reading is not None:
        reading.update({
            "rel": rel,
            "sha256": want,
            "reused": bool(reused),
            "duplicate_in": content_duplicates_across_entries(
                base, want, lit_id=lid, source_size=size),
        })
    return rel, dest


# --------------------------------------------------------------------------- #
# 抽读件归位：候选期 `out/texts/<候选名>.txt` ⇒ `library/<文献号>/<stem>.txt`
# --------------------------------------------------------------------------- #
#
# ## 为什么需要这一环（真机 sunflower-digest-2/3 的现场）
#
# `text.extract` 在候选期（`lit_id="cand:<槽位>"`）把正文落进 `out/texts/`：那时还没有
# 文献号，写进 `library/` 会把候选冒充成已收编。`text_tools._text_dir` 的注释逐字许诺
# 「等登记之后再按号归位」—— 而在本函数之前，全仓没有这一环：登记只收编原件（PDF），
# 抽出的正文永远留在 `out/texts/`，于是 `literature.download.fulltext=ok` 在书架上
# 查不到那一份正文（真机 sunflower-digest-2：5 行全部如此；sunflower-digest-3：
# 000008/000011 两行如此，000006 那一份在号目录里是后来又一次 `text.extract` 的偶然）。
#
# ## 不变量（一条）
#
# 一条 `literature` 行的盘上资产 = 原件 + 与它同目录同 stem 的抽读件。
# 目标名只由 `litread.text_rel` 决定（同一条判据：写侧这一处、`wellformed` 那一处、
# `fs.read` 的路由那一处都读它），本函数不另拼一份。
#
# 规范形态下它们的目录就是文献号（`library/<6位号>/`）；存量里也有 `path` 首段是
# 候选槽位号的行（真机 sunflower-digest-3：`000000` 的 path 是 `000006/…pdf`）。那一档
# 抽读件仍跟着原件走，并把 `dir_matches_lit_id=False` 记进回执 —— 目录名不是文献号是
# 另一条缺陷，不在这里用一次静默改名盖掉（详见 `land_read_text` 的 docstring）。

#: 抽读件归位的七档结局（`land_read_text` 的 `reading["status"]`）。
#:
#: 三态纪律：这七档互斥且都能读出来 —— "写成了 / 早就同内容 / 撞了不同内容 /
#: 源变了 / 没有源 / 行上没有 path / 行上的 path 形态非法"。把后几档折成"没做成"会让
#: "候选没抽过"（正常）与"抽过但落不进去"（要人看）同形，而这两种的处置相反。
TEXT_LAND_WRITTEN = "written"            # 这次真的写下了（目标原本不在）
TEXT_LAND_REUSED = "reused"              # 目标已存在且内容相同：零写入
TEXT_LAND_CONFLICT = "conflict"          # 目标已有另一份不同内容：不覆盖，报冲突
TEXT_LAND_TEXT_CHANGED = "text_changed"  # 源文件与抽读回执的 sha 不符：不写
TEXT_LAND_NO_SOURCE = "no_source"        # 候选期没抽过 / 抽读件已不在盘上：什么都不做
TEXT_LAND_NO_PATH = "no_path"            # 行上没有 `literature.path`：算不出目标名
TEXT_LAND_BAD_PATH = "bad_path"          # 行上的 path 形态非法（`library/` 前缀 / 越界）：不猜


def _land_reading(reading: dict | None, **cells: Any) -> None:
    """把一档结局写进可选出参 `reading`（`None` ⇒ 不写；与 `library_landing` 同形）。"""
    if reading is not None:
        reading.update(cells)


def land_read_text(library: Path | str, lit_id: str, *,
                   literature_path: str | None, source: Path | str | None,
                   sha256_hex: str = "",
                   reading: dict | None = None) -> tuple[str, Path | None]:
    """候选期抽出的正文 ⇒ 这一条文献号目录下的正式抽读件（唯一实现）。

    ## 签名里每一格回答什么

    * `library`：书架根（`Store.library`）；
    * `lit_id`：已经发出的文献号（4 位老号 / 6 位新号）—— 它的用处是①校验目标目录名
      是合法号、②在回执里点明"归位的是哪一条"；目标目录以 `literature_path` 为准
      （理由见下一条）；
    * `literature_path`：登记之后那一行上的 `path`（规范形态 `<6位号>/<原件名>`）。
      目标名由 `litread.text_rel(literature_path)` 现算 = 同目录、同 stem、`.txt`；本函数
      不接受"调用方自己拼一个抽读件名"，否则写侧与 `wellformed` / `fs.read` 会各判一份。

      为什么目标目录跟 `path` 走、而不是硬拼 `library/<lit_id>/`：抽读件必须与原件
      同目录（`wellformed` 与 `fs.read` 都只按 `text_rel(path)` 找它）。真机上确实存在
      `path` 首段 ≠ `lit_id` 的存量行（`sunflower-digest-3`：`000000` 的行 `path` 是
      `000006/…pdf` —— A 在登记前自己 `fs.move` 到 `library/<候选槽位>/`，登记路径
      `_adopt_file` 见"已在库里"就直接采用那个相对名）。硬拼 `library/<lit_id>/` 会让
      抽读件与原件分居两条目录，`wellformed` 永远报 `literature_fulltext_missing`。
      所以这一档照原件的目录落，并把 `dir_matches_lit_id=False` 如实记进回执 ——
      "目录名不是文献号"是另一条缺陷（归 layout / `_adopt_file` 那一处），不在这里
      用一次静默改名把它盖掉；
    * `source`：候选期那份 `.txt`（抽读回执的 `text_abs`）；它不在盘上就不写、也不建目录
      （"候选期没抽读过"是正常态，不许造一个空文件把它冒充成"有正文"）；
    * `sha256_hex`：抽读回执记的正文指纹。给了就核：与 `source` 现算不符 ⇒
      `text_changed`，不写（三态：不是"没查"也不是"写了"）；
    * `reading`：可选出参，`{"status", "rel", "sha256", "source", "expected_sha256",
      "target_sha256", "lit_id", "dir", "dir_matches_lit_id"}`。

    ## 幂等与冲突（这是本函数存在的两条判据）

    * 目标已存在且内容与源相同 ⇒ `reused`，一个字节都不写（重跑 `lit.admit_all`、
      或后来又一次 `text.extract` 已经在号目录里落过同一份，都走这一档）；
    * 目标已存在且内容是另一份 ⇒ `conflict`，不覆盖（覆盖会毁掉已建立的引文
      定位，而且"同一篇文献两份正文"这件事必须被人看见，不许由后到者静默取胜）；
    * 内容是复制过去的，不是搬走：`out/texts/` 那一份是 `data/lit_reads.jsonl`
      回执的锚（`litavail` 读侧要用 `text_abs + text_version` 核"读的是不是同一份"），
      搬走会让回执指向一个不存在的文件。

    返回 `(library 相对名, 绝对落点)`；没有目标名（`literature_path` 空 / 形态非法）时
    返回 `("", None)` 或 `(算不出的名字, None)`，其它"没写成"的档返回 `(相对名, None)`
    —— `None` 明确表示"这次没有写出来的那份文件"。
    """
    base = Path(library)
    lid = str(lit_id or "").strip()
    if not _ENTRY_ID_RE.match(lid):
        raise ValueError(
            f"抽读件的目录名必须是文献号（4 位老号 / 6 位新号），收到 {lit_id!r} —— "
            "`library/<文献号>/<stem>.txt` 是现行规范（2026-11-25）")
    row_path = str(literature_path or "").replace("\\", "/").strip()
    target_rel = LR.text_rel(row_path) if row_path else ""
    if not target_rel:
        _land_reading(reading, status=TEXT_LAND_NO_PATH, rel="", lit_id=lid,
                      source=str(source or ""), sha256="")
        return "", None
    if LR.path_shape(row_path) in (LR.SHAPE_BAD, LR.SHAPE_UNJUDGED):
        _land_reading(reading, status=TEXT_LAND_BAD_PATH, rel=target_rel, lit_id=lid,
                      source=str(source or ""), sha256="",
                      why=(f"literature.path={row_path!r} 的形态非法（{LR.path_shape(row_path)}）"
                           "⇒ 不猜目标名"))
        return target_rel, None
    head, _sep, tail = target_rel.partition("/")
    dir_name = head if tail else ""
    dest = base / target_rel
    want = str(sha256_hex or "").strip().lower()
    if want and not _SHA256_RE.fullmatch(want):
        raise ValueError(
            f"抽读回执的内容 hash 必须是 64 位小写十六进制（收到 {sha256_hex!r}）—— "
            "`text_changed` 的判据要靠它")
    cells: dict[str, Any] = {"dir": dir_name, "dir_matches_lit_id": bool(dir_name == lid)}
    src_text = str(source or "").strip()
    src = Path(src_text) if src_text else None
    if src is None or not src.is_file():
        _land_reading(reading, status=TEXT_LAND_NO_SOURCE, rel=target_rel, lit_id=lid,
                      source=src_text, sha256="", expected_sha256=want, **cells)
        return target_rel, None
    got = sha256_file(src)
    if want and got != want:
        _land_reading(reading, status=TEXT_LAND_TEXT_CHANGED, rel=target_rel, lit_id=lid,
                      source=src_text, sha256=got, expected_sha256=want, **cells)
        return target_rel, None
    if dest.exists():
        have = sha256_file(dest) if dest.is_file() else ""
        if have == got:
            _land_reading(reading, status=TEXT_LAND_REUSED, rel=target_rel, lit_id=lid,
                          source=src_text, sha256=got, target_sha256=have, **cells)
            return target_rel, dest
        _land_reading(reading, status=TEXT_LAND_CONFLICT, rel=target_rel, lit_id=lid,
                      source=src_text, sha256=got, target_sha256=have, **cells)
        return target_rel, dest
    # 谁写谁 mkdir：目录只在"真的有字节要落"这一刻建（历史教训：先建目录再搬字节
    # 会在库里留下 60 个空目录）。
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    _land_reading(reading, status=TEXT_LAND_WRITTEN, rel=target_rel, lit_id=lid,
                  source=src_text, sha256=got, target_sha256=got, **cells)
    return target_rel, dest


# --------------------------------------------------------------------------- #
# 原件搬迁：`library/<槽位号>/<名>` ⇒ `library/<文献号>/<名>`
# --------------------------------------------------------------------------- #
#
# ## 为什么需要这一环（真机 sunflower-digest-3 的现场）
#
# 候选期模型的合法动作里没有"持有一个文献号"，却有"必须让 `text.extract` 抽得到正文"
# 这条硬约束 —— 而 `text.extract` 的相对路径基准只有 `library/`，且首段要是 6 位号。
# 于是模型把下载件 `fs.move` 进 `library/<候选槽位号>/`（会话 2026-11-26T06:13:27 /
# 08:14:59 / 08:16:05 / 08:49:46 四笔，`dst` 分别是 `library/000006|000008|000011|
# 000015/…pdf`），抽完正文再 `lit.admit` / `lit.admit_all`。登记路径
# `search_tools._adopt_file` 见"已在 `library/` 内"就把那个相对名原样返回 ⇒
# `literature.path` 记成了 `000006/…pdf`（`000006` 是候选槽位号，不是文献号），
# 盘上也就一直是 `library/000006/…pdf`。四行四条，一条都没搬。
#
# ## 不变量（一条）
#
# `library/` 下只住文献号目录，且一条 `literature` 行的 `path` 首段 == 它的 `lit_id`。
# 落点的身份仍然只由 `library_landing` 一处给（内容 sha 优先、同名不同内容追加短哈希、
# 绝不覆盖）—— 本函数只做"从哪个目录搬到哪个文献号"，不自己拼落点名。
#
# ## 主人 = 结算点，但搬运动作只有这一处实现
#
# 两个调用点共用本函数：
#   * `litstage.admit_all`（结算点，三样齐：`slot → lit_id`、`store`、行上的
#     `path`/登记回执）—— 它给得出 `slot`，所以留痕里五格（from/to/slot/lit_id/sha）
#     都全；
#   * `search_tools._adopt_file`（登记那一刻就已经在 `library/` 里的那一支）—— 它没有
#     `slot`，但把"不再把槽位目录当文献目录"这件事就地做掉，坏 `path` 活不过登记。
# 结算点是兜底的那一道：登记那一刻搬失败的（跨盘/权限/历史行）在这里再搬一次。

#: 原件搬迁的七档结局（`reading["status"]`）。
RELOCATE_MOVED = "moved"                    # 这次真的搬了（from != to，字节已在新目录）
RELOCATE_AT_REGISTRATION = "moved_at_registration"  # 登记那一刻已搬，结算点只采用回执
RELOCATE_ALREADY_IN_ENTRY = "already_in_entry"      # 首段本来就是文献号：一个字节都没动
RELOCATE_REUSED = "reused"                  # 号目录里已有同内容的一份：源是重复，已清掉
RELOCATE_NO_PATH = "no_path"                # 行上没有 path：无对象可搬
RELOCATE_BAD_PATH = "bad_path"              # path 形态非法（带 `library/` 前缀 / 越界）：不猜
RELOCATE_MISSING = "file_missing"           # path 指的文件不在盘上
RELOCATE_CONFLICT = "conflict"              # 落点名被另一份不同内容占着且连短哈希都撞了
RELOCATE_WRITE_FAILED = "write_failed"      # 搬不动（跨盘/权限/占用）：如实记，不静默


def _prune_empty_entry_dir(base: Path, directory: Path, lit_id: str) -> None:
    """搬空之后删掉源目录（`library/` 下只许留文献号目录）。

    只删空的目录，且不碰 `library/` 根本身、也不碰目标文献号目录。删不掉（占用/权限）
    就算了 —— 这一格的失败不该把已经搬成功的字节判成没搬，留下一个空目录也比谎报好。
    """
    try:
        if directory == base or directory.name == lit_id or not directory.is_dir():
            return
        if not any(directory.iterdir()):
            directory.rmdir()
    except OSError:
        return


def relocate_into_entry(library: Path | str, lit_id: str, *,
                        literature_path: str | None,
                        reading: dict | None = None) -> tuple[str, Path | None]:
    """把一条文献的原件搬进 `library/<文献号>/`（原件搬迁的唯一实现）。

    ## 签名里每一格回答什么

    * `library`：书架根（`Store.library`）；
    * `lit_id`：已经发出的文献号 —— 落点目录名只由它决定；不是合法号（4/6 位）就
      抛 `ValueError`（"没有号就没有目录名"是 `library_landing_name` 的老规矩）；
    * `literature_path`：那一行上当前的 `path`（`<槽位号>/<名>` / `<文献号>/<名>` /
      历史扁平名）。目标名不由本函数拼：`library_landing` 按内容 sha 优先给，
      同名不同内容追加内容短哈希，一个既有文件都不覆盖；
    * `reading`：可选出参
      `{"status", "from", "to", "sha256", "bytes", "lit_id", "why"}` ——
      `from`/`to` 是 `library/` 相对名，`reading["slot"]` 由调用方自己塞（本函数不知道槽位）。

    ## 七档结局（为什么不能折成"搬了 / 没搬"两档）

    `already_in_entry`（本来就在号目录里）与 `moved`（这次搬了）处置相反：前者是正控
    "别把正常的再搬一次"，后者是修复；`reused`（号目录里已有同内容）说明源是重复，
    删源不丢信息；`file_missing` / `no_path` / `bad_path` 是"没有可搬的对象"，
    而 `write_failed` / `conflict` 是"有对象但搬不动"。折成一档就会让"这一条不需要搬"
    与"这一条该搬但没搬成"在读数上同形 —— 后者才是下一次审计要抓的。

    返回 `(搬迁后的 library 相对名, 绝对落点或 None)`。`None` 表示这一次没有可确认的
    落点（文件不在 / 搬失败）；`reading["status"]` 说得出是哪一档。
    """
    base = Path(library)
    lid = str(lit_id or "").strip()
    if not _ENTRY_ID_RE.match(lid):
        raise ValueError(
            f"搬迁的目标目录名必须是文献号（4 位老号 / 6 位新号），收到 {lit_id!r} —— "
            "`library/<文献号>/<名>` 是现行规范（2026-11-25），没有号就没有目录名")
    text = str(literature_path or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    cells: dict[str, Any] = {"lit_id": lid, "from": text, "to": text, "sha256": ""}
    # 下面每一档都经 `_land_reading(reading, status=…, **cells)` 落出参；`sha256` 与
    # `bytes` 随档不同 ⇒ 走 `cells` 就地改，不作为关键字重复传（否则 TypeError）。
    if not text:
        _land_reading(reading, status=RELOCATE_NO_PATH, **cells)
        return "", None
    if LR.path_shape(text) in (LR.SHAPE_BAD, LR.SHAPE_UNJUDGED):
        _land_reading(reading, status=RELOCATE_BAD_PATH,
                      why=(f"literature.path={text!r} 的形态非法（{LR.path_shape(text)}）"
                           "⇒ 不猜它该搬去哪"), **cells)
        return text, None
    parts = [p for p in text.split("/") if p]
    head = parts[0] if len(parts) > 1 else ""
    src = base / text
    if head == lid:
        # 正控：已经在自己的号目录里 —— 一个字节都不动（重跑 `admit_all` 走这一档）。
        got = sha256_file(src) if src.is_file() else ""
        cells.update(sha256=got, bytes=_size_or_none(src) or 0)
        _land_reading(reading, status=RELOCATE_ALREADY_IN_ENTRY, **cells)
        return text, (src if src.is_file() else None)
    if not src.is_file():
        _land_reading(reading, status=RELOCATE_MISSING,
                      why=f"path 指的文件不在盘上：{src}", **cells)
        return text, None
    sha = sha256_file(src)
    spread = {"sha256": sha, "bytes": _size_or_none(src) or 0}
    cells.update(spread)
    try:
        landing, target = library_landing(base, src, sha, lit_id=lid)
    except (OSError, ValueError) as exc:
        _land_reading(reading, status=RELOCATE_WRITE_FAILED,
                      why=f"{type(exc).__name__}: {exc}", **cells)
        return text, None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _land_reading(reading, status=RELOCATE_WRITE_FAILED,
                      why=f"{type(exc).__name__}: {exc}", **cells)
        return text, None
    rel = landing
    if target == src:
        # `library_landing` 的内容优先支把落点判回了源自己（号目录 == 源目录）：
        # 这一档只可能是 head == lid，上面已经返回过；留着是防御。
        _land_reading(reading, status=RELOCATE_ALREADY_IN_ENTRY, **cells)
        return rel, src
    if target.exists():
        have = sha256_file(target) if target.is_file() else ""
        if have != sha:
            # 名字占着且内容不同，而 `library_landing` 追加短哈希那几档也没找到空位：
            # 绝不覆盖（覆盖会毁掉已建立的引文定位）。
            _land_reading(reading, status=RELOCATE_CONFLICT,
                          why=(f"落点 {rel} 已被另一份不同内容占着"
                               f"（既有 sha256={have or '读不到'}）⇒ 不覆盖"), **cells)
            return text, None
        # 号目录里已经有同内容的一份 ⇒ 源是重复。搬第二份只会让"同一份字节两份文件"
        # 长回来（`library_landing` 的 ① 就是为这件事）。内容相同，删源不丢信息。
        # 注意：`to` 走 `cells`（`_land_reading(..., **cells)`），不作为关键字重复传 ——
        # 重复传是 `TypeError`，而它会在字节已经搬走之后才抛，把成功的登记判成
        # `registration_failed`（真机读数见 `temp/msreloc/REPORT.md` 的首次跑）。
        cells["to"] = str(target.relative_to(base).as_posix())
        try:
            src.unlink()
        except OSError as exc:
            _land_reading(reading, status=RELOCATE_REUSED,
                          why=f"号目录里已有同内容的一份；源删不掉（{exc}）", **cells)
            return rel, target
        _prune_empty_entry_dir(base, src.parent, lid)
        _land_reading(reading, status=RELOCATE_REUSED, **cells)
        return rel, target
    try:
        shutil.move(str(src), str(target))
    except OSError as exc:
        _land_reading(reading, status=RELOCATE_WRITE_FAILED,
                      why=f"{type(exc).__name__}: {exc}", **cells)
        return text, None
    _prune_empty_entry_dir(base, src.parent, lid)
    cells["to"] = str(target.relative_to(base).as_posix())
    _land_reading(reading, status=RELOCATE_MOVED, **cells)
    return rel, target


def _machine_summary(pages: int, *, name: str = "") -> str:
    """`ingest_directory` 落进 `literature.summary` 的机器题录。

    只写机器看得见的事实：这是一本"本地书架上的专著/教材"、共几页；`name` 是
    可省的文件名回显。

    ## 为什么文件名可省（WRITERESIDUE ③）

    正文闸（`search_tools._content_claim_refusal` → `litavail.content_assertion`）
    是 lexical 判据：它分不出"题名里的 theorem"与"从正文里读出来的定理"，也分不出
    `A=B.pdf` 里的 `=B` 是文件名还是公式。文件名在 `title`（`src.stem`）、
    `path`（library 下的相对名）、`download.source_path`（绝对来源）三处都还在，
    所以被闸判成断言时省掉它不丢任何来路 —— 而它一旦留下，这一行就会带着一句
    "不是读出来的"断言进库。
    """
    who = f"（{name}，{pages} 页）" if name else f"（{pages} 页）"
    return f"本地书架上的专著/教材{who}"


def list_books(root: Path | str, *, pattern: str = "*.pdf") -> list[Path]:
    """列出目录下的候选文件（排序后返回，保证每次跑的次序一样）。"""
    base = Path(root)
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob(pattern) if p.is_file())


# --------------------------------------------------------------------------- #
# 用户声明：哪些文件是本次的「可靠参考文献」（入库白名单）
# --------------------------------------------------------------------------- #
#
# 2026-11-21 业主裁定：M 不自己判断哪份文献可靠。只有用户提示词里明确点名的
# 文件/目录才算可靠参考文献、才可入库；没点名的一律只能当研究参考（可读），不许进
# `literature`。默认 fail-closed：没有声明 ⇒ 一律不许入库。
#
# 声明由 M 读用户提示词后逐字抄下来，落成工作区根的 `RELIABLE-REFERENCES.json`：
# `{"paths": ["a.pdf", "b/"], "verbatim": "<用户原话>"}`。这份文件是唯一的白名单
# 真身；A 不另判，`search.ingest_local` 与 `A.ingest_local` 的非 dry 档都按它核。
#
# 边界（2026-11-21 DGWIDE ④ 收紧）：声明只管工作区内的文件（工作区参考材料的投放处是
# `source/` 与 `library/`）。工作区外的目录不再被当成"调用方自己的书架"放行：
# 声明里的 `paths` 是工作区相对路径、表达不了外部路径，于是"这一批文件被用户点名了吗"
# 这个问题在工作区外答不出来 —— 按 fail-closed 拒，与 `search.register` 对工作区外
# `path` 的口径一致。要收外部书架，先把文件放进工作区并由用户点名（或者在候选链里
# 按候选行 + 读过正文的准入依据走 `lit.admit`）。`dry_run` 是发现档，不受这条影响。


def declaration_path(workspace_root: Path | str) -> Path:
    """声明文件的落点（工作区根）。"""
    return Path(workspace_root) / DECLARATION_NAME


def _norm_rel(path_text: str) -> str:
    """把一条声明/相对路径归一成 `a/b.pdf` 形状（去 `./`、反斜杠与首尾斜杠）。"""
    text = str(path_text).replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def read_declaration(workspace_root: Path | str) -> tuple[tuple[str, ...], str]:
    """读用户声明，返回 `(paths, problem)`。

    三态：文件不在 ⇒ `((), "")`（= 没点名；调用方按 fail-closed 处理）；在盘上但
    读不出来 / 形状不对 ⇒ `((), "一句人话")`（仍按"全未声明"处理，不折成"都声明了"）。
    `verbatim` 只作留痕（用户原话），不参与匹配。
    """
    path = declaration_path(workspace_root)
    if not path.is_file():
        return (), ""
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return (), f"{DECLARATION_NAME} 读不出来：{type(exc).__name__}: {exc}"
    if not isinstance(blob, dict) or not isinstance(blob.get("paths"), list):
        return (), (f"{DECLARATION_NAME} 的形状不对（要 "
                    "{\"paths\": [...], \"verbatim\": \"<用户原话>\"}）")
    out: list[str] = []
    for raw in blob["paths"]:
        if not isinstance(raw, str):
            continue
        entry = _norm_rel(raw)
        if entry:
            out.append(entry)
    return tuple(out), ""


def is_declared(rel_path: str, declarations: Iterable[str]) -> bool:
    """这一份（工作区相对路径）有没有被用户声明覆盖。

    三种声明写法都认：整条路径（`source/a.pdf`）、裸文件名（`a.pdf`，用户只说
    "a.pdf 是可靠参考文献"）、目录（`b/` 或 `b`，用户说 "b/ 里都是"）。大小写不敏感：
    工作区可能在 Windows 上，大小写不该决定一份文献能不能入库。
    """
    rel = _norm_rel(rel_path)
    if not rel:
        return False
    low = rel.casefold()
    base = rel.rsplit("/", 1)[-1].casefold()
    for raw in declarations:
        entry = _norm_rel(raw)
        if not entry:
            continue
        e = entry.casefold()
        if e == low:
            return True
        if "/" not in e and e == base:
            return True
        if low.startswith(e + "/"):
            return True
    return False


def declaration_verdict(workspace_root: Path | str,
                        rel_paths: Iterable[str] = ()) -> dict:
    """把一批工作区相对路径对用户声明核一遍：声明判据的唯一实现。

    ## 为什么要有这一格（DECLAREGATE，2026-11-21）

    声明闸此前只长在 `search.ingest_local` 的非 dry 档（`undeclared_workspace_books`），
    而 `search.register` 是另一条能把工作区文件收编进 `library/` 并写成 `literature`
    行的直写口 —— 它一份声明都不核（真机 lp-ball-12 的 lit:000000 就是这样把
    `downloads/` 里那份 PDF 收编进库的）。两条口要判的是同一条：这份文件被用户点名
    了吗。所以判据只能有一份，放在这里；`undeclared_workspace_books`（ingest_local
    的批量核）与 `search.register`（单份核）都从它上面走。

    ## 三态

    * 声明文件不在盘上 ⇒ `state=DECLARATION_ABSENT`（没点名；调用方按 fail-closed 拒）；
    * 声明在盘上但读不出来 / 形状不对 ⇒ `state=DECLARATION_UNREADABLE`
      （`checked=False`：这是「没查成」，拒信不许说成「你没声明」）；
    * 读出来了 ⇒ `state=DECLARATION_READ`（`checked=True`），`undeclared` 逐条列出
      没被点名的那些（空元组 = 全被点名覆盖）。`paths=[]`（用户这一次没点名）落在
      这一档、`undeclared` 就是全部 —— 不是 `ABSENT`，两者不可折叠。

    `rel_paths` 为空时只回答声明本身的状态（`undeclared=()`）：调用方要的若是
    "声明读得出来吗"这一个问题，不必编一个假路径进来。
    """
    root = Path(workspace_root)
    path = declaration_path(root)
    declared, problem = read_declaration(root)
    rels: list[str] = []
    for raw in rel_paths:
        rel = _norm_rel(raw)
        if rel and rel not in rels:
            rels.append(rel)
    if problem:
        state = DECLARATION_UNREADABLE
    elif path.is_file():
        state = DECLARATION_READ
    else:
        state = DECLARATION_ABSENT
    return {
        "state": state,
        # `checked` 只回答「声明查成了没有」，不回答「这份文件能不能入库」。
        "checked": state == DECLARATION_READ,
        "declaration": str(path),
        "paths": tuple(declared),
        "undeclared": tuple(rel for rel in rels if not is_declared(rel, declared)),
        "problem": problem,
    }


# --------------------------------------------------------------------------- #
# 收编时原件留不留：投放处与被声明的字节只许复制（2026-11-24 裁定）
# --------------------------------------------------------------------------- #
#
# ## 裁定（SEED-LANDING-FIX ①）
#
# 收编（`search.register` / 候选链 `lit.admit_all`）不许把投放处里的字节搬走：
# 用户的声明（`RELIABLE-REFERENCES.json`）说的是"投放处里那几份文件是可靠参考文献"，
# 这些话是 M 逐字抄下来的用户原话 —— 唯一有权改它的是 M（按用户原话），A 不能改。
# 所以只要收编会把文件从投放处搬走，"声明里那些路径还在不在盘上"这条判据就必然变红
# （`scripts/check_declaration.py` 的 `declared_empty` / `reference_count`），
# 而唯一的"修法"只能是让声明跟着搬 —— 那是让系统的动作去改写用户的话。
#
# 代价对比：复制多占一份字节（种子批 892 979 字节，25 份种子包 17 MB），换来
# `reference/` 与 `library/` 各留一份、声明面永远可核；而"移动 + 声明跟着变"要
# 改 user 声明、还要把 gate 从"盘上在不在"改成"台账记没记"（弱判据，台账可手写）。
# 兄弟路径 `ingest_directory` 本来就是 `shutil.copy2` —— 两条收编路的语义由此统一。
#
# 不搬的范围（两条，缺一条就有绕行口）：
#   * 投放处里的（`DROP_ZONES`）—— 连候选链也照此办（候选链不核声明）；
#   * 被用户声明覆盖的（`is_declared`）—— 声明可以点名任何位置，不只是投放处。
# 之外（框架自己的下载暂存 `downloads/` 等）仍按"收编即搬"处理：那些字节是这一趟
# 自己写的中间产物，留在原处会变成"既不在书架、也不在投放处"的游离文件。

#: 投放处的名字：`reference/` 是新落点（`seedinject.SEED_SUBDIR`），`source/` 是旧名
#: （也是审阅型工作区的只读基线）。与 `scripts/check_declaration.py` 的 `DROP_ZONES`
#: 是同一份口径，由 `tests/test_the_declared_seed_stays_in_its_drop_zone.py` 钉住。
DROP_ZONES: tuple[str, ...] = ("reference", "source")


def _workspace_rel(workspace_root: Path | str, path: Path | str) -> str:
    """`path` 的工作区相对 posix 路径；不在工作区内 / 解析不了 ⇒ 空串。"""
    try:
        root = Path(workspace_root).resolve()
        rel = Path(path).resolve().relative_to(root)
    except (OSError, ValueError):
        return ""
    return rel.as_posix()


def in_drop_zone(workspace_root: Path | str, path: Path | str) -> bool:
    """`path` 在不在工作区的投放处（`DROP_ZONES` 的某一格）里。"""
    rel = _workspace_rel(workspace_root, path)
    if not rel or "/" not in rel:
        return False
    top = rel.split("/", 1)[0].casefold()
    return top in {zone.casefold() for zone in DROP_ZONES}


def keeps_original(workspace_root: Path | str, source: Path | str) -> bool:
    """收编这份字节时，原件要不要留在原处（`True` ⇒ 复制；`False` ⇒ 搬走）。

    唯一实现：`search_tools._adopt_file` 按它选 `copy2` / `move`。两种 `True` 的由来
    （投放处 / 被声明覆盖）与"为什么不是移动"写在上面那节注释里；本函数只回答这一格，
    不判"许不许入库"（那是 `declaration_verdict` 的事，两者不可互相替代：
    一份未声明、但落在投放处的字节也不许被搬走）。
    """
    rel = _workspace_rel(workspace_root, source)
    if not rel:
        return False
    declared, _problem = read_declaration(workspace_root)
    if declared and is_declared(rel, declared):
        return True
    return in_drop_zone(workspace_root, source)


def _workspace_pairs(workspace_root: Path | str, root: Path | str,
                     *, pattern: str = "*.pdf") -> list[tuple[str, Path]]:
    """`root` 下、确实位于工作区内的文件：`[(工作区相对 posix 路径, 绝对路径)]`。

    工作区外的文件不在这里被跳过了（2026-11-21 DGWIDE ④）：`undeclared_workspace_books`
    先单独把它们捞出来、按 fail-closed 拒（声明表达不了工作区外的路径）；本函数只负责
    "工作区内那一批"的路径换算，于是两个调用方（工具与动作）拿到的是同一份判据。
    """
    workspace = Path(workspace_root).resolve()
    out: list[tuple[str, Path]] = []
    for src in list_books(root, pattern=pattern):
        try:
            rel = src.resolve().relative_to(workspace).as_posix()
        except (OSError, ValueError):
            continue                       # 工作区外：由 `_outside_workspace_books` 单独判
        out.append((rel, src))
    return out


def _outside_workspace_books(workspace_root: Path | str, root: Path | str,
                             *, pattern: str = "*.pdf") -> list[Path]:
    """`root` 下那些解析之后落不到工作区里的文件（含软链逃逸）。"""
    workspace = Path(workspace_root).resolve()
    out: list[Path] = []
    for src in list_books(root, pattern=pattern):
        try:
            src.resolve().relative_to(workspace)
        except (OSError, ValueError):
            out.append(src)
    return out


def undeclared_workspace_books(workspace_root: Path | str, root: Path | str,
                               *, pattern: str = "*.pdf") -> tuple[list[str], str]:
    """`root` 下那些没被用户声明的文件 + 声明本身的问题。

    空列表 = 这一批可以入库（这些文件全被声明覆盖）。
    `problem` 非空时声明读不出来 ⇒ 调用方仍应拒绝（fail-closed），只是拒信能说清
    "是声明坏了"而不是"你没声明"。

    ## 工作区外的文件按 fail-closed 拒（2026-11-21 DGWIDE ④）

    改前这一档是"跳过"：`_workspace_pairs` 把工作区外的文件扔掉 ⇒ `undeclared` 为空
    ⇒ 调用方读成"全被声明覆盖" ⇒ `search.ingest_local` / `A.ingest_local` 能把任意
    外部目录整批收编进 `literature`。那是 DECLAREGATE 列出的第 ④ 条绕行口。
    声明里的 `paths` 是工作区相对路径，表达不了工作区外的文件 ⇒ 与 `search.register`
    的工作区外路径同口径：拒（不是"跳过"）。`dry_run`（发现档）不经过本函数，
    所以"先发现、再定声明"的用法不受影响。

    判据本体是 `declaration_verdict`（与 `search.register` 共用）；本函数只负责
    "把目录里的文件分成工作区内/外两批"这一件事。
    """
    outside = _outside_workspace_books(workspace_root, root, pattern=pattern)
    if outside:
        # 绝对路径原样点名：声明是工作区相对的，这些路径一条都表达不了。
        return [str(p) for p in outside], ""
    pairs = _workspace_pairs(workspace_root, root, pattern=pattern)
    if not pairs:
        return [], ""
    verdict = declaration_verdict(workspace_root, [rel for rel, _src in pairs])
    return list(verdict["undeclared"]), str(verdict["problem"] or "")


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

    #: 固定五档，零值在场：把"没扫到"与"扫到了但跳过"分开。
    #:
    #: `no_dedup_key`（SYSRESIDUE ④）：题名规范化之后没有可判重的内容 ⇒ 这一本
    #: 不进 `literature`。它不是 `unreadable`（正文读不出来）也不是
    #: `skipped_limit`（配额）—— 处置是"补一个能归一化的题名/DOI 再来"。
    STATUSES: tuple[str, ...] = ("ingested", "already_present", "skipped_limit",
                                 "skipped_too_large", "unreadable", "no_dedup_key")

    def counts(self) -> dict[str, int]:
        """按固定五档数一遍（零值也在场："没扫到"与"扫到了但跳过"分得开）。"""
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


def _read_body(src: Path, size: int) -> tuple[Any, str]:
    """抽一次正文并判"这一份有没有可读正文"：返回 `(doc, 拒因)`，拒因为空串 = 可登记。

    判据只有一份：`litread.fulltext_tier` 是 `download.fulltext` 的四档真身，它判乱码
    读的又是 `litread.garbled_text`（`text.extract` 拒写乱码读同一个函数）。所以这里不
    另写"能不能读"的判据，只按它决定"这一份有没有可读正文"。

    改前这一档照样登记（只在 note 里写一句"没有可引用的正文"）：乱码 PDF 于是进了库、
    而 `download.fulltext` 一个键都没有 —— `litavail.tier_of_literature` 把它读成
    `unknown`，下游拿不到正文，而"入库"这件事已经发生了。那是本地登记这条路唯一绕过
    判收的地方。

    抽不出来 / 没有可读正文时也把 `doc` 交回去（可能为 `None`）：`pages` 是这一本的机器
    读数，`unreadable` 那一档的清单里也要看得见"抽到了几页" —— 读不了不是没抽过。
    """
    try:
        doc = extract_text(str(src))
    except Exception as exc:  # noqa: BLE001 —— 读不了就是读不了，如实记一档
        return None, f"{type(exc).__name__}: {exc}"
    tier = LR.fulltext_tier(bytes_on_disk=size,
                            pages=getattr(doc, "pages", None),
                            text=str(getattr(doc, "text", "") or ""))
    if tier != LR.FULLTEXT_OK:
        return doc, (f"{tier}: 这一份没有可读正文，不进 literature"
                     "（乱码要换来源；无文本层的扫描件要先 OCR）")
    return doc, ""


def _summary_for_row(pages: int, name: str, note: str) -> tuple[str, str]:
    """机器题录过一次正文闸：返回 `(summary, 追加后的 note)`（WRITERESIDUE ③）。

    判据只有一份：`search_tools._content_claim_refusal`（它自己判
    `litavail.content_assertion`，受控码 `litstage.CONTENT_CLAIM_WITHOUT_READ`），
    与 `search.register` / `table.create|update` 用的是同一处实现。

    为什么 `read_ok=False`：这条路只有"抽过"（`fulltext_tier == ok`），没有
    `litavail.content_read` 要的那份证据（抽读回执 + 版本 + `fs.read` 观察台账 +
    不只摘要）；按三态纪律不能把"抽过"冒充成"读过"。

    判成断言时不是拒这本书（它有可读正文、必须能登记），而是按同一道闸的第一条改法办：
    题录只写机器事实，不回显文件名（见 `_machine_summary`）。
    """
    from .tools import search_tools as _ST
    summary = _machine_summary(pages, name=name)
    if _ST._content_claim_refusal(summary, read_ok=False,
                                  port="search.ingest_local") is not None:
        summary = _machine_summary(pages)
        note = (f"{note}；" if note else "") + (
            f"机器题录未回显文件名 {name!r}：它会被正文闸判成内容性断言")
    return summary, note


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

    ## 为什么 provenance 要三个参数

    这里曾把请求行写死成 `submitted_by="human"` + 正文里那句"人直接提供的一本本地藏书"。
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
        sha = sha256_file(src)
        # 文件名只清洗、不再带内容 hash 前缀（2026-11-25：落点 `<文献号>/<清洗名>`）。
        # 这里是"还没有号"的阶段：真落点名（含文献号目录）要等事务里 `alloc_id` 之后
        # 由 `library_landing` 一处给 —— 先落一个临时名再改名会留下两套名字。
        name = _safe_name(src)
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
            plan.library_name = f"{plan.lit_id}/{name}"
            plan.note = "同一内容 hash 已在库里（热启动的判据是内容，不是文件名）"
            report.books.append(plan)
            continue

        # 先解析一次正文：没有文本层的书仍然登记，但要把这件事写在行上，
        # 而不是等 B 去发现（B 发现时它记的是 last_mine_error，那是运行记录）。
        # 判据（抽不出 / 乱码 / 无文本层 / 全空页）在 `_read_body` 一处，这里只处置。
        doc, body_problem = _read_body(src, size)
        if doc is not None:
            plan.pages = len(getattr(doc, "pages", []) or [])
            plan.has_text_layer = bool(getattr(doc, "has_text_layer", False))
        if body_problem:
            plan.status = "unreadable"
            plan.note = body_problem
            report.books.append(plan)
            continue

        # ---- 正文闸（WRITERESIDUE ③）：机器题录也不许带"不是读出来的"内容性断言。
        # 判据与改法都在 `_summary_for_row` 一处（与 `search.register` 同一实现）。
        summary, plan.note = _summary_for_row(plan.pages, name, plan.note)

        if dry_run:
            plan.note = (f"{plan.note}；" if plan.note else "") + (
                "dry_run 不分配号，真落点将是 `<新号>/{name}`")
            report.books.append(plan)
            continue

        # ---- SYSRESIDUE ④：两个去重格（`_keys` / `dedup_key`）与 A、`search.register`
        # 同一处算（`sysresidue.literature_dedup_cells`），而且先判再搬文件 ——
        # 改前这一支在键集为空时写空串、`search.register` 那一支写
        # `title:<norm>|*`，两个口径各自自洽，读侧 `dedup._row_keys` 两处都收，
        # 于是"同一本书两个主键"永远不会报错。没有主键的书现在不登记，
        # 也一个字节都不搬进 `library/`（受控拒要在写任何东西之前）。
        title = src.stem.replace("_", " ").strip() or name
        keys, dedup_key = _SR.literature_dedup_cells(title, None, None)
        cell_problems = _SR.dedup_cells_problems(
            {"title": title, "year": None, "doi": None,
             "dedup_key": dedup_key, "_keys": keys}, keys=keys)
        if cell_problems:
            plan.status = "no_dedup_key"
            plan.note = ("dedup_key 是空串：题名规范化之后没有可判重的内容，"
                         "这一本不进 literature（补一个能归一化的题名或 DOI 再来）")
            _SR.note_dedup_refusal(store.root, where=name, problems=cell_problems)
            report.books.append(plan)
            continue

        lib.mkdir(parents=True, exist_ok=True)

        with store.tx("search_requests", "literature", "counters",
                      actor=actor, note=note or "ingest local books") as tx:
            lit_id = tx.alloc_id("lit")
            # 落点由 `library_landing` 一处给（`<lit_id>/<清洗名>`；同名不同内容会追加
            # 内容短哈希、绝不覆盖）。位置在 `alloc_id` 之后：目录名就是这一行的号，
            # 不许先落临时名再改名。
            landing, dest = library_landing(lib, src, sha, lit_id=lit_id)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or sha256_file(dest) != sha:
                shutil.copy2(src, dest)
            plan.library_name = landing
            req_id = I.next_prefixed_id(tx.rows("search_requests"), "request_id", "r")
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
            # 落库键：与 `dedup._row_keys` 读的是同一族（它读 `dedup_key` 与 `_keys`
            # 两处），而算法只有 `sysresidue.literature_dedup_cells` 一处
            # （上面已经算好，判据也在上面过了一遍）。
            lit_row = S.Literature(
                lit_id=lit_id,
                title=title,
                type="M",
                summary=summary,
                path=landing,
                processed=False,
                source_request_ids=[req_id],
                dedup_key=dedup_key,
                added_at=S.now_iso(),
                download=LR.with_fulltext({
                    "status": "ok",
                    "note": "本地文件（不是网络下载）；内容类型按扩展名与解析结果判定",
                    "pages": plan.pages,
                    "has_text_layer": plan.has_text_layer,
                    "bytes": size,
                    "sha256": sha,
                    "source_path": str(src),
                }, LR.FULLTEXT_OK),
            ).to_dict()
            # `_keys` 是"这一行携带的全部去重键"（与 agent_a 写 literature 行时
            # 同一个诊断字段）；不落它，`dedup._row_keys` 就只能看到一个主键。
            lit_row["_keys"] = keys
            tx.upsert("literature", lit_row)
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
#: 而胜出（于是交给模型的材料可能是"Chapter 1. Basic calculus…"，模型只能如实回答
#: "材料中没有"）。
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
#: 目录与索引的行末多半是页码，散文页几乎没有这种行。目录页该比例远高于正文页；
#: 用 0.35 当阈值留了余量，并把"命中 Contents/Index"也算进去。
_NAV_PENALTY = 0.15

#: 页级打分的主键单位：命中多少个不同主题词，权重远大于稀有度之和。
#: 为什么必须这样：原来只用 `Σ 1/df(t)`，于是
#:   命中一个稀有词（df=4 ⇒ 0.25）的页，压过命中三个常见词（0.043+0.011+…）的页。
#: 代价：题目 `cosets and quotient groups` 下选中的页只命中 `cosets` 一个词，
#: 而书里明明有同时讲 quotient 与 groups 的页。覆盖率优先把"命中几个不同词"放成主键。
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

    为什么不是"从页首截 max_chars 个字符"（从页首硬截会踩的坑）：
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

    best_score, best_lo = -1.0, occurrences[0][0]
    for a in range(len(occurrences)):
        seen: set[str] = set()
        for b in range(a, len(occurrences)):
            if occurrences[b][0] - occurrences[a][0] > max_chars:
                break
            seen.add(occurrences[b][1])
            score = sum(weight.get(t, 0.0) for t in seen)
            # 并列时取更早的那个窗口（结果与页序无关、可复现）。
            if score > best_score:
                best_score, best_lo = score, occurrences[a][0]

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
    return text


def _token_weights(pages: list[str], toks: list[str]) -> dict[str, float]:
    df: dict[str, int] = {t: 0 for t in set(toks)}
    for page in pages:
        low = page.lower()
        for t in df:
            if t in low:
                df[t] += 1
    return {t: 1.0 / max(1, n) for t, n in df.items()}


def _page_scores(pages: list[str], weight: dict[str, float]) -> list[float]:
    out: list[float] = []
    for page in pages:
        low = page.lower()
        present = {t for t in weight if t in low}
        # 主键是覆盖率（这一页到底谈了几个主题词），稀有度只当次键。
        # 只用 `Σ 1/df(t)` 会让"命中一个稀有词"的页压过"命中三个常见词"的页 ——
        # 代价见 `_COVERAGE_FIRST` 的说明（cosets 那道题就是这么选错的）。
        score = len(present) * _COVERAGE_FIRST + sum(weight[t] for t in present)
        if score > 0 and _looks_like_navigation(page):
            score *= _NAV_PENALTY
        out.append(score)
    return out


def page_scores(pages: list[str], query: str) -> list[float]:
    """每一页与 `query` 的相关度（主键=命中多少个不同主题词，次键=稀有度加权和）。

    ## 为什么把它单独抽出来

    原先这套打分只活在 `excerpt_for` 内部，于是任何"要按相关度给「书」排序"的调用方
    都拿不到分数 —— 我第一版 `search.local` 就因此拿"摘录长度"当排序键，而
    长度在窗口取满时恒等于 `max_chars`：排序退化成按 `lit_id` 字母序，
    曾经"martingale central limit theorem"的第三名是一篇讲
    「伊朗城市」的论文（它命中的是 `central`）。判据只有一份实现才不会这样脱节。

    导航页（目录/索引）按住 `_NAV_PENALTY` 压分，理由见 `_looks_like_navigation`。
    """
    toks = _tokens(query)
    if not toks or not pages:
        return [0.0 for _ in pages]
    return _page_scores(pages, _token_weights(pages, toks))


def excerpt_for(pages: list[str], query: str, *, max_chars: int = 1200) -> tuple[int, str]:
    """挑出与 `query` 最相关的一页并截一段。返回 `(页码 1-based, 摘录)`。

    ## 为什么是"整页里截一段"而不是"拼几句最像的话"

    `evidence.materials_block` 只把 `abstract` 塞进 prompt（默认截到 1200 字符），
    而 prompt 要求模型"从上面摘要里逐字复制"引文。所以这段文本必须满足两件事：
    它是原文的连续子串（模型抄得下来），且它来自一页（页码才说得出出处）。
    把不连续的高分句子拼起来会让"逐字复制"变成"逐字拼接"—— 而框架的回验
    只认前者，结果是每一条都落 `not_found`，看上去像模型在编，其实是材料被拼过。

    ## 排序口径（打分本体已抽到 `page_scores`）

    原来按"整页里主题词的原始出现次数"排序，真跑时发现：主题
    `convex optimization duality and Lagrange multipliers` 选中的那一页讲的是
    "凸集的定义"（`convex` 满页都是），而 `duality` / `Lagrange` 一次都没进窗口 ——
    模型于是如实回答"材料中没有对偶的内容"。改成按不同主题词的稀有度加权和
    排序（在某页出现的词取"出现该词的页数"的倒数），稀有词才推得动排序。
    """
    toks = _tokens(query)
    if not toks:
        return (1, pages[0][:max_chars].strip()) if pages else (0, "")
    weight = _token_weights(pages, toks)
    scores = _page_scores(pages, weight)
    best_idx = max(range(len(scores)), key=lambda i: (scores[i], -i))
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
            download = row.get("download") or {}
            hits.append((
                score,
                LocalHit(
                    lit_id=str(row.get("lit_id") or ""),
                    title=str(row.get("title") or ""),
                    page=page,
                    excerpt=excerpt,
                    pdf_path=path_text,
                    bytes=int(download.get("bytes") or 0),
                    sha256=str(download.get("sha256") or ""),
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
        # 且稀有词要能推动选页与选窗口 —— 这一条是真跑踩出来的：
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

"""把历史真机下载的文献种子投进新工作区的输入区：只放文件，不写台账。

## 为什么落点是 `reference/` 而不是 `library/`（2026-11-22 业主裁定）

`library/` 是已登记书架：`literature.path` 就是 `library/` 下的相对名
（`store.library_path` 把一切路径强制解析在 `library/` 内）。
把未登记的种子 PDF 直接铺在 `library/` 根，等于让 25 份没有 `literature` 行的文件
占住已登记书架的位置 —— A 侧维护的文献库结构因此异常。业主逐字：
「为什么你直接往library里塞文献？这会导致A侧维护的文献库结构异常」。

所以种子落在工作区根的输入区 `reference/`（用户提供的参考材料投放处），
`SEED-README.md` 也落在 `reference/` 里 —— 它不是工作区根的条目（根上的条目要过
`store._WORKSPACE_ROOT_ENTRIES` 白名单，`reference` 已登记为"用户输入落点"）。
"允许入库"由用户声明回答，不由投放动作回答：用户（或 M 按用户原话）把
`{"paths": ["reference/"]}` 记进工作区根的 `RELIABLE-REFERENCES.json`，
再由 A 逐份判收进 `library/`。投放、声明、判收是三件事，各有各的落点。

## 三条硬边界（每一条都有判据）

1. 只写文件，不写台账：`seed_workspace` 只碰 `reference/`（含其中的
   `SEED-README.md`），不打开、不创建 `data/literature.json`，也不碰任何 `data/*.json`。
   理由：业主明令「不直接入库」。直接写台账等于替 A 判收，而 A 的收录判据是
   这条流水线里唯一该判收的地方。
2. 不写已登记书架：`library/` 里只能有被 `literature` 行的 `path` 引用的文件。
   投放落点在 `reference/`；判据 `unregistered_library_files` 会把"书架上的游离文件"
   读出来（含反真空：把落点打桩回 `library/` ⇒ 判据必红）。
3. 默认关：`projects.create_project` / CLI 的 `--seed-literature` 缺省都是关，
   普通建工作区一个字节都不多投。幂等：`reference/SEED-README.md` 在就是投过了。

## 种子包在哪、长什么样

默认落点由工程根推出来（`settings.PROJECT_ROOT / seed / literature`），也可以用环境变量
`AGENTFLOW_SEED_LITERATURE_DIR` 指到别处（判据用这个换临时种子）。种子包由
`scripts/seed_corpus.py --build` 生成，`--verify` 按 `MANIFEST.json` 逐份复算 sha256
与抽读字数。本模块只按 manifest 读，不自己判"哪份算好文献"。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import settings as SET

__all__ = [
    "DECLARATION_NAME",
    "DECLARATION_VERBATIM",
    "ENV_SEED_DIR",
    "FILES_DIR",
    "FORMAT",
    "MANIFEST_NAME",
    "MARKER_NAME",
    "MARKER_REL",
    "SEED_REL",
    "SEED_SUBDIR",
    "VERSION",
    "candidate_chain_lines",
    "candidate_chain_warning",
    "declaration_text",
    "default_seed_dir",
    "read_manifest",
    "read_seed_reading",
    "seed_workspace",
    "unregistered_library_files",
]

#: 种子包落点（相对工程根）。
SEED_REL = "seed/literature"

#: 指到别处的环境变量（判据与打包后的机器都靠它换落点）。
ENV_SEED_DIR = "AGENTFLOW_SEED_LITERATURE_DIR"

MANIFEST_NAME = "MANIFEST.json"
FILES_DIR = "files"
MARKER_NAME = "SEED-README.md"

#: 投到工作区里的位置：输入区（不是已登记书架 `library/`）。
#:
#: 为什么是 `reference/` 而不是 `library/`：见模块 docstring。为什么不是 `source/`：
#: `source/` 在代码与提示词里是审阅型工作区的只读基线（`source/main.tex`，
#: `agent_prompts.PAPER_PACK` / `closing._leg_reading`），把研究型工作区的输入也叫
#: `source/` 会让"只读基线"与"待判收的参考材料"同名；`reference/` 只表达"用户提供的
#: 参考材料"，与审阅基线不撞名。
SEED_SUBDIR = "reference"

#: 标记文件的工作区相对路径（`reference/SEED-README.md`）。
MARKER_REL = f"{SEED_SUBDIR}/{MARKER_NAME}"

#: 用户声明的真身文件名（与 `locallib.DECLARATION_NAME` 同一个名字；判据对拍两处）。
DECLARATION_NAME = "RELIABLE-REFERENCES.json"

#: 给种子写声明时用的用户原话（业主 2026-11-22 口径：信任这个文件夹里的都是可用参考）。
DECLARATION_VERBATIM = (
    "reference/ 里的文件都是用户提供的可靠参考文献，可入库；"
    "其它地方的文件只作参考、不可入库"
)

FORMAT = "agentflow-seed-literature"
VERSION = 1

_SHA_LEN = 64

#: `library/` 里允许存在、但不由 `literature` 行引用的瞬态目录前缀（A 的下载 staging）。
#: 它由 `agent_a.run_once` 在 `library/` 下建、跑完就删；崩溃时可能留下 —— 那是残留，
#: 不是"书架上多了一本书"，所以判据把它单独放过（不放进"游离文件"里报）。
_TRANSIENT_LIBRARY_PREFIXES: tuple[str, ...] = ("agentflow-stage-",)

#: 投放中途崩掉留下的半份文件（先写临时名、改名落地；见 `seed_workspace`）。
_TEMP_SUFFIX = ".seedtmp"


def default_seed_dir() -> Path:
    """种子包的默认落点：环境变量优先，否则工程根（`agentflow/`）下的 `seed/literature`。"""
    raw = os.environ.get(ENV_SEED_DIR, "").strip()
    if raw:
        return Path(raw)
    return SET.PROJECT_ROOT / SEED_REL


def declaration_text() -> str:
    """给这批种子落用户声明时的默认模板（`RELIABLE-REFERENCES.json` 的全文）。

    只生成文本、不写盘：声明是用户的话，由用户（或 M 逐字抄用户原话）落到工作区根。
    投放替用户写声明 = 把"用户点名过"这件事冒充成投放的副作用，所以这里只给模板。
    """
    return json.dumps({"paths": [f"{SEED_SUBDIR}/"], "verbatim": DECLARATION_VERBATIM},
                      ensure_ascii=False, indent=1, default=str) + "\n"


def _is_sha256(text: Any) -> bool:
    """是不是一个小写十六进制 sha256（长度 64）。"""
    if not isinstance(text, str) or len(text) != _SHA_LEN:
        return False
    return all(ch in "0123456789abcdef" for ch in text)


def _safe_relpath(raw: Any) -> Path | None:
    """manifest 里的 `path` 必须是 `files/` 下的相对路径，不许逃出种子包。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    p = Path(raw.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts:
        return None
    if not p.parts or p.parts[0] != FILES_DIR:
        return None
    return p


def read_manifest(seed_dir: Path | str | None = None) -> tuple[dict[str, Any] | None, str]:
    """读并校验种子包的 `MANIFEST.json`。

    返回 `(manifest, problem)`：读到并校验通过时 problem 是空串；否则 manifest 为 None、
    problem 是一句人话（缺哪一格、哪一格不合法）。三态纪律：坏 manifest 不折成"没有种子"。
    """
    root = Path(seed_dir) if seed_dir else default_seed_dir()
    path = root / MANIFEST_NAME
    if not path.is_file():
        return None, f"种子清单不在盘上：{path}（先跑 scripts/seed_corpus.py --build）"
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"种子清单读不了：{path}（{type(exc).__name__}: {exc}）"
    if not isinstance(blob, dict):
        return None, f"种子清单不是一个对象：{path}"
    if blob.get("format") != FORMAT:
        return None, f"种子清单 format={blob.get('format')!r}，期望 {FORMAT!r}"
    if blob.get("version") != VERSION:
        return None, f"种子清单 version={blob.get('version')!r}，期望 {VERSION}"
    files = blob.get("files")
    if not isinstance(files, list):
        return None, f"种子清单没有 files 列表：{path}"
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            return None, f"种子清单 files[{index}] 不是对象"
        rel = _safe_relpath(entry.get("path"))
        if rel is None:
            return None, f"种子清单 files[{index}].path 不合法（必须是 {FILES_DIR}/ 下的相对路径）"
        if not _is_sha256(entry.get("sha256")):
            return None, f"种子清单 files[{index}].sha256 不是 64 位小写十六进制"
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] <= 0:
            return None, f"种子清单 files[{index}].bytes 不是正整数"
        extract = entry.get("extract") or {}
        if not isinstance(extract, dict) or not isinstance(extract.get("chars"), int):
            return None, f"种子清单 files[{index}].extract.chars 缺失"
    return blob, ""


def _sha256_of(path: Path) -> str:
    """按 1 MiB 分块算文件 sha256。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_chain_lines(books_dir: str = SEED_SUBDIR) -> tuple[str, ...]:
    """种子文件收编成文献行的正确链（两处 README 的唯一真身）。

    改前的文案把第一步写成「把盘上文件登记成候选」—— 那对应的是非 dry 档：它直接
    写 `literature` 行、跳过判收，等于把「下载成功」冒充成「判收过了」。正确链的第一
    步只发现、零写入，候选由 `lit.stage_add` 建；判收与提交在 `lit.admit` /
    `lit.admit_all` 上。

    为什么返回逐行文本：工作区里的 `reference/SEED-README.md` 与种子包自己的 README
    必须是同一句。一处说「登记成候选」、另一处说「走候选链」，模型照哪一处做取决于它
    先读到哪一份 —— 所以生成器这里是唯一真身，`seed/literature/README.md` 逐字含同样
    四行（判据 `tests/test_seed_readme_says_the_chain.py` 按本函数的返回值比对）。
    """
    return (
        "1. **发现（只发现、零写入）**：`search.ingest_local(books_dir=\"" + books_dir + "\", "
        "dry_run=True)` —— dry_run=True 只发现、零写入：它只读盘上文件、算同一个 sha256 / "
        "页数 / 文本层，`lit_candidates` / `literature` / 两个台账一个字节都不写；"
        "读数里的 `count` / `books[]` 就是候选清单（`ingested` 是「会登记」的预告，不是入库）。",
        "2. **建候选（只对用户点名的那些）**：用户提示词里点名的文件/目录由 M 逐字记在工作区"
        "根的 `RELIABLE-REFERENCES.json`（种子这一批的模板是 `{\"paths\": [\"" + books_dir +
        "/\"], \"verbatim\": \"…\"}`）；**只有清单里的才可入库**，清单外的只能当研究参考。"
        "逐份 `lit.stage_add(request_id=<委托号>, entries=[{title: …, "
        "url: <发现读数里那一份的盘上路径>, relevance: \"工作区里已有的本地文献，不是检索来的\"}])` "
        "—— 这一步只写候选表，`literature` 仍是 0 行。",
        "3. **判收**：`lit.stage_list` 回读 → `text.extract(lit_id=\"cand:<槽位>\")` 抽正文 → "
        "`fs.read` 读到那份 `.txt`（读到同一版抽出来的正文）→ "
        "`lit.admit(items=[{slot, availability: \"readable\"}])`（**`content_read` 才算过**，"
        "机器现算不是自报）→ 逐委托 `lit.admit_all`（提交、回填号、清表）。",
        "4. **收进 `literature` 之后**：下一步派 B 的 `run_once` 整理"
        "（抽概念、建关系、落命题线索）。",
    )


def candidate_chain_warning() -> str:
    """那条兜底路的禁令（与上面四行同一真身，两处 README 逐字相同）。"""
    return ("⚠️ **非 dry 档跳过判收、不要用**：`search.ingest_local` 不带 `dry_run=True` 时，"
            "它把盘上文件直接写成 `literature` 行、跳过了判收 —— 那等于把「下载成功」"
            "冒充成「判收过了」，收进来的是一批没有判据的文献。何况未在 "
            "`RELIABLE-REFERENCES.json` 里点名的文件会被它按 `not_declared_reference` 受控拒"
            "（零写入）：未点名的只能当研究参考，不入库。")


def _readme_text(manifest: dict[str, Any], seeded: list[dict[str, Any]]) -> str:
    """生成 `reference/SEED-README.md`：说清是什么、不是什么、谁判收、怎么复算。"""
    total = sum(int(item["bytes"]) for item in seeded)
    lines = [
        "# SEED-README",
        "",
        "这个工作区在建立时被投放了一批历史真机下载的文献种子。",
        "",
        "## 它们是什么",
        "",
        f"- {len(seeded)} 份 PDF，共 {total} 字节，落在 `{SEED_SUBDIR}/`（工作区的**输入区**）。",
        "- 来源：`agentflow/seed/literature/`（清单 `MANIFEST.json`）。",
        "- 每份都满足种子口径：`download.status == \"ok\"`、`bytes > 0`、盘上文件存在、",
        "  台账 sha256 与盘上 sha256 一致、内容确实是 PDF、`extract.extract_text`",
        "  抽出的正文非空、无 U+FFFD 替换字符、含足够多的完整英文词。",
        "  （逐份读数在清单里。）",
        "- 原样字节，没有改名，没有改写内容。",
        "",
        "## 它们不是什么（重要）",
        "",
        "- **未入库、也不在已登记书架上**：`library/` 是已登记书架（`literature.path` 就指向它），",
        "  本批文件一份都没有进去；`data/literature.json` 仍是 0 行，没有 lit_id、摘要或处置。",
        "- 未判收：种子口径只证明「下载成功且抽得出来」，不证明「与本研究相关、可收录」。",
        "- 不是已验证全文：清单里的抽读字数只是筛选读数，不是收录判据。",
        "",
        "## 怎么声明（用户信任这个文件夹）",
        "",
        "只有用户点名过的文件才可入库。这一批的默认声明模板（落成工作区根的 "
        f"`{DECLARATION_NAME}`，`verbatim` 用用户原话）：",
        "",
        "```json",
        declaration_text().rstrip("\n"),
        "```",
        "",
        f"声明里写 `{SEED_SUBDIR}/` 就是把整个输入区点名；**没有声明 ⇒ 一份都不许入库**",
        "（非 dry 档会以 `not_declared_reference` 受控拒，零写入）。",
        "",
        "## 怎么用",
        "",
        "这批文件不是已入库的文献，A 必须走候选链（顺序与工具名如下，一步都不能省）：",
        "",
        *candidate_chain_lines(SEED_SUBDIR),
        "",
        candidate_chain_warning(),
        "",
        "收进 `literature` 之后才有 lit_id，B 的 `run_once` 才处理得到它们。",
        "",
        "谁判收：A（收录判据的唯一入口）。本投放动作不替 A 判收，也不替 A 建候选。",
        "收编进 `library/` 是 A 判收之后的事（登记行上才有 `path`）；本批文件不会以",
        "未登记的身份留在书架上。",
        "",
        "## 怎么复算",
        "",
        "在 `agentflow/` 下跑：",
        "",
        "```",
        "python scripts/seed_corpus.py --verify",
        "```",
        "",
        "（或在仓库根跑 `python agentflow/scripts/seed_corpus.py --verify`。）",
        "它按 `agentflow/seed/literature/MANIFEST.json` 逐份重算 sha256 与抽读字数；",
        "任何一份字节被改动、缺失或抽读字数对不上，都以退出码 1 结束。",
        "",
        "## 这一批的清单",
        "",
    ]
    for entry in seeded:
        title = str(entry.get("title") or "").strip()
        doi = str(entry.get("doi") or "").strip()
        tail = f" doi={doi}" if doi else ""
        lines.append(f"- `{SEED_SUBDIR}/{Path(str(entry['path'])).name}` — {title}{tail}")
    lines.append("")
    return "\n".join(lines)


def _read_literature_rows(workspace: Path) -> list[dict[str, Any]] | None:
    """只读地读 `library/` 的登记面：`literature` 行的 `path` 集合来源。

    `None` = 没查成（表在盘上但读不出来 / 形状不对），与"0 行"分得开 —— 判据不许把
    "没查"折成"书架是空的"。
    """
    path = workspace / "data" / "literature.json"
    if not path.is_file():
        # 没这张表的工作区：登记面是 0 行（不是"没查成"）。判据据此把盘上文件全算游离
        # —— fail-closed 的方向。
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return None
    return rows


def _norm_library_rel(raw: Any) -> str:
    """把一行 `literature.path` 归一成 `library/` 内的相对名（去 `library/` 前缀与 `./`）。"""
    text = str(raw or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    text = text.strip("/")
    if text.startswith("library/"):
        text = text[len("library/"):]
    return text


#: 书架上的"书"只认这一族后缀。`.txt` 不是书：`text.extract` 的声明
#: （`src/agentflow/tools/text_tools.py` 的 `text.extract`）就写着「把 PDF 自带的
#: 文字层转成同名 `.txt` 写进 `library/`」—— 那些 `.txt` 是设计产物，不是"没登记"。
#: 这一格只报"该有 `literature` 行却没有的 PDF"；把抽取产物列成未登记，等于把
#: "设计允许的东西"读成"结构异常"（真机 lp-ball-22：3 个 `.txt` 被误报）。
_LIBRARY_BOOK_SUFFIXES: tuple[str, ...] = (".pdf",)


def unregistered_library_files(project: Path | str, *,
                               literature_rows: list[dict[str, Any]] | None = None
                               ) -> list[str] | None:
    """`library/` 里没有任何 `literature` 行引用的 PDF（工作区相对路径，排序）。

    这是"已登记书架只放已登记的"这条不变量的唯一实现：`library/` 是 A 侧维护的文献库，
    盘上多出一份没有登记行的 PDF，就等于书架结构异常（2026-11-22 业主指出的那次事故：
    25 份未登记种子直接铺在 `library/` 根）。

    `.txt` 不算：`text.extract` 会把 PDF 文字层转成同名 `.txt` 写进 `library/`
    （工具声明里逐字写着），那是抽取产物、设计允许，不是"未登记的书"。这一格只报
    PDF —— 否则「书架干净」永远为假，读数变成噪音。

    返回 `None` = 没查成（台账读不出来 / 形状不对）。空列表 = 书架干净。
    瞬态文件不报：`library/agentflow-stage-*` 下的下载暂存（跑完即删，崩溃残留不是
    "多了一本书"）与 `.seedtmp` 半份文件。
    """
    workspace = Path(project)
    library = workspace / "library"
    if not library.is_dir():
        return []
    rows = literature_rows if literature_rows is not None else _read_literature_rows(workspace)
    if rows is None:
        return None
    referenced: set[Path] = set()
    for row in rows:
        rel = _norm_library_rel(row.get("path"))
        if not rel:
            continue
        try:
            referenced.add((library / rel).resolve())
        except OSError:
            continue
    out: list[str] = []
    for path in library.rglob("*"):
        if not path.is_file():
            continue
        # 书架上的"书"只认 PDF：`.txt` 是 `text.extract` 的设计产物（见模块常量
        # `_LIBRARY_BOOK_SUFFIXES` 的理由），不是"没登记"。
        if path.suffix.lower() not in _LIBRARY_BOOK_SUFFIXES:
            continue
        rel = path.relative_to(library)
        if rel.parts and rel.parts[0].startswith(_TRANSIENT_LIBRARY_PREFIXES):
            continue
        if path.name.endswith(_TEMP_SUFFIX):
            continue
        try:
            resolved = path.resolve()
        except OSError:
            out.append(rel.as_posix())
            continue
        if resolved not in referenced:
            out.append(rel.as_posix())
    return sorted(out)


def seed_workspace(project: Path | str, *, seed_dir: Path | str | None = None,
                   force: bool = False) -> dict[str, Any]:
    """把种子包投进一个工作区的输入区；只写 `reference/`（含其中的 `SEED-README.md`）。

    返回读数（`enabled` / `copied` / `skipped` / `destination` / `marker` /
    `seed_dir` / `already` / `problem` / `files`）。`problem` 非空时 `copied` 一定为 0：
    清单坏了就不投，也不落 README（否则下次重试会被"已投过"挡住）。

    两条拒投（都返回 `problem`、零写入）：
    - 工作区根上已经有旧的 `SEED-README.md`（改前的形态：README 在根、种子在
      `library/`）⇒ 这是旧工作区，不许在这上面再投一遍（两种形态混在一起，
      读的人分不清哪一批在书架上）。旧工作区按 `docs/USER-GUIDE-CLI.md` 重新建。
    - 种子包清单坏了 ⇒ 不投。
    """
    workspace = Path(project)
    seed = Path(seed_dir) if seed_dir else default_seed_dir()
    destination = workspace / SEED_SUBDIR
    marker = destination / MARKER_NAME
    out: dict[str, Any] = {
        "enabled": True, "copied": 0, "skipped": 0,
        "destination": str(destination), "marker": str(marker),
        "seed_dir": str(seed), "already": False, "problem": "", "files": [],
    }
    legacy_marker = workspace / MARKER_NAME
    if legacy_marker.is_file() and not force:
        out["problem"] = (
            f"这是改前形态的工作区（根上有 `{MARKER_NAME}`，种子在 `library/` 里）："
            "不再往它上面投 —— 两种形态混在一起会污染已登记书架。"
            f"新落点是 `{MARKER_REL}`（输入区）。要重新投放，按 "
            "`docs/USER-GUIDE-CLI.md` 的命令序列在**新工作区**上做。")
        return out
    manifest, problem = read_manifest(seed)
    if manifest is None:
        out["problem"] = problem
        return out
    entries = [entry for entry in manifest["files"] if isinstance(entry, dict)]
    if marker.is_file() and not force:
        out["already"] = True
        out["skipped"] = len(entries)
        return out

    destination.mkdir(parents=True, exist_ok=True)
    seeded: list[dict[str, Any]] = []
    problems: list[str] = []
    for entry in entries:
        source = seed / str(entry["path"]).replace("\\", "/")
        name = Path(str(entry["path"])).name
        target = destination / name
        if not source.is_file():
            problems.append(f"{entry['path']}：种子包里没有这个文件")
            continue
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry["sha256"]:
            problems.append(f"{entry['path']}：种子包内 sha256 与清单不符")
            continue
        if target.is_file() and target.read_bytes() == data:
            out["skipped"] += 1
            seeded.append(entry)
            continue
        # 先写临时名再改名：中途崩掉不会在输入区里留下半份文件。
        temp = target.with_name(target.name + _TEMP_SUFFIX)
        temp.write_bytes(data)
        if _sha256_of(temp) != digest:
            temp.unlink(missing_ok=True)
            problems.append(f"{entry['path']}：写入后 sha256 不符（磁盘问题）")
            continue
        temp.replace(target)
        out["copied"] += 1
        seeded.append(entry)

    if not seeded:
        out["problem"] = "；".join(problems) or "种子清单里一份可用文件都没有"
        return out
    marker.write_text(_readme_text(manifest, seeded), encoding="utf-8", newline="\n")
    out["files"] = [str(Path(SEED_SUBDIR) / Path(str(entry["path"])).name) for entry in seeded]
    if problems:
        out["problem"] = "；".join(problems)
    return out


def read_seed_reading(project: Path | str) -> dict[str, Any]:
    """只读地读一个工作区里有没有种子：不算哈希、不写字节。

    除种子读数外还报两件"书架卫生"的读数：
    - `legacy_root_marker`：根上有没有改前形态的 `SEED-README.md`（旧工作区）；
    - `library_unregistered`：`library/` 里没有 `literature` 行引用的文件
      （`None` = 台账读不出来，没查成）。非空 ⇒ 已登记书架上有多余的东西。
    """
    workspace = Path(project)
    destination = workspace / SEED_SUBDIR
    marker = destination / MARKER_NAME
    files = sorted(p for p in destination.glob("*.pdf") if p.is_file()) if destination.is_dir() else []
    return {
        "landed": bool(files) and marker.is_file(),
        "count": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "marker": str(marker),
        "destination": str(destination),
        "legacy_root_marker": (workspace / MARKER_NAME).is_file(),
        "library_unregistered": unregistered_library_files(workspace),
    }

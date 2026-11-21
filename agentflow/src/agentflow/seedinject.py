"""把历史真机下载的文献种子投进新工作区：只放文件，不写台账。

## 为什么要有这一层

业主 2026-11-21 口径（逐字）：「下一回真机建工作区时，把这十几轮真机所有下载成功且
无乱码的文献都丢进新工作区（不直接入库）」。于是这一层只做一件事：把
`agentflow/seed/literature/` 里那份已经审过字节与可读性的种子包原样复制进新工作区的
`library/`，并在工作区根落一份 `SEED-README.md` 说明它们是什么、不是什么。

## 三条硬边界（每一条都有判据）

1. 只写文件，不写台账：`seed_workspace` 只碰 `library/` 与 `SEED-README.md`，
   不打开、不创建 `data/literature.json`，也不碰任何 `data/*.json`。
   理由：业主明令「不直接入库」。直接写台账等于替 A 判收，而 A 的收录判据是
   这条流水线里唯一该判收的地方。
2. 默认关：`projects.create_project` / CLI 的 `--seed-literature` 缺省都是关，
   普通建工作区一个字节都不多投。
3. 幂等：`SEED-README.md` 在就是投过了；再投只返回读数，不重复复制。

## 种子包在哪、长什么样

默认落点由工程根推出来（`settings.WORKSPACE_ROOT / seed / literature`），
也可以用环境变量 `AGENTFLOW_SEED_LITERATURE_DIR` 指到别处（判据用这个换临时种子）。
种子包由 `scripts/seed_corpus.py --build` 生成，`--verify` 按 `MANIFEST.json`
逐份复算 sha256 与抽读字数。本模块只按 manifest 读，不自己判"哪份算好文献"。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import settings as SET

__all__ = [
    "ENV_SEED_DIR",
    "FILES_DIR",
    "FORMAT",
    "LIB_SUBDIR",
    "MANIFEST_NAME",
    "MARKER_NAME",
    "SEED_REL",
    "VERSION",
    "candidate_chain_lines",
    "candidate_chain_warning",
    "default_seed_dir",
    "read_manifest",
    "read_seed_reading",
    "seed_workspace",
]

#: 种子包落点（相对工程根）。
SEED_REL = "seed/literature"

#: 指到别处的环境变量（判据与打包后的机器都靠它换落点）。
ENV_SEED_DIR = "AGENTFLOW_SEED_LITERATURE_DIR"

MANIFEST_NAME = "MANIFEST.json"
FILES_DIR = "files"
MARKER_NAME = "SEED-README.md"

#: 投到工作区里的位置。放 `library/` 根：工作区是新建的，书架本来就是空的；种子文件名带
#: sha256 前缀，与之后按 lit_id 命名的书天然分得开。
LIB_SUBDIR = "library"

FORMAT = "agentflow-seed-literature"
VERSION = 1

_SHA_LEN = 64


def default_seed_dir() -> Path:
    """种子包的默认落点：环境变量优先，否则工程根（`agentflow/`）下的 `seed/literature`。"""
    raw = os.environ.get(ENV_SEED_DIR, "").strip()
    if raw:
        return Path(raw)
    return SET.PROJECT_ROOT / SEED_REL


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


def candidate_chain_lines(books_dir: str = LIB_SUBDIR) -> tuple[str, ...]:
    """种子文件收编成文献行的正确链（两处 README 的唯一真身）。

    改前的文案把第一步写成「把盘上文件登记成候选」—— 那对应的是非 dry 档：它直接
    写 `literature` 行、跳过判收，等于把「下载成功」冒充成「判收过了」。正确链的第一
    步只发现、零写入，候选由 `lit.stage_add` 建；判收与提交在 `lit.admit` /
    `lit.admit_all` 上。

    为什么返回逐行文本：工作区根的 `SEED-README.md` 与种子包自己的 README 必须是同一句。
    一处说「登记成候选」、另一处说「走候选链」，模型照哪一处做取决于它先读到哪一份 ——
    所以生成器这里是唯一真身，`seed/literature/README.md` 逐字含同样四行（判据
    `tests/test_seed_readme_says_the_chain.py` 按本函数的返回值比对）。
    """
    return (
        "1. **发现（只发现、零写入）**：`search.ingest_local(books_dir=\"" + books_dir + "\", "
        "dry_run=True)` —— dry_run=True 只发现、零写入：它只读盘上文件、算同一个 sha256 / "
        "页数 / 文本层，`lit_candidates` / `literature` / 两个台账一个字节都不写；"
        "读数里的 `count` / `books[]` 就是候选清单（`ingested` 是「会登记」的预告，不是入库）。",
        "2. **建候选（只对用户点名的那些）**：用户提示词里点名的文件/目录由 M 逐字记在工作区"
        "根的 `RELIABLE-REFERENCES.json`（`{\"paths\": [\"a.pdf\", \"b/\"], \"verbatim\": "
        "\"<用户原话>\"}`）；**只有清单里的才可入库**，清单外的只能当研究参考。逐份 "
        "`lit.stage_add(request_id=<委托号>, entries=[{title: …, "
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
    """生成工作区根的 `SEED-README.md`：说清是什么、不是什么、谁判收、怎么复算。"""
    total = sum(int(item["bytes"]) for item in seeded)
    lines = [
        "# SEED-README",
        "",
        "这个工作区在建立时被投放了一批历史真机下载的文献种子。",
        "",
        "## 它们是什么",
        "",
        f"- {len(seeded)} 份 PDF，共 {total} 字节，落在 `{LIB_SUBDIR}/`。",
        "- 来源：`agentflow/seed/literature/`（清单 `MANIFEST.json`）。",
        "- 每份都满足种子口径：`download.status == \"ok\"`、`bytes > 0`、盘上文件存在、",
        "  台账 sha256 与盘上 sha256 一致、内容确实是 PDF、`extract.extract_text`",
        "  抽出的正文非空、无 U+FFFD 替换字符、含足够多的完整英文词。",
        "  （逐份读数在清单里。）",
        "- 原样字节，没有改名，没有改写内容。",
        "",
        "## 它们不是什么（重要）",
        "",
        "- 未入库：`data/literature.json` 仍是 0 行，没有为它们分配 lit_id、摘要或处置。",
        "- 未判收：种子口径只证明「下载成功且抽得出来」，不证明「与本研究相关、可收录」。",
        "- 不是已验证全文：清单里的抽读字数只是筛选读数，不是收录判据。",
        "",
        "## 怎么用",
        "",
        "这批文件不是已入库的文献，A 必须走候选链（顺序与工具名如下，一步都不能省）：",
        "",
        *candidate_chain_lines(LIB_SUBDIR),
        "",
        candidate_chain_warning(),
        "",
        "收进 `literature` 之后才有 lit_id，B 的 `run_once` 才处理得到它们。",
        "",
        "谁判收：A（收录判据的唯一入口）。本投放动作不替 A 判收，也不替 A 建候选。",
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
        lines.append(f"- `{LIB_SUBDIR}/{Path(str(entry['path'])).name}` — {title}{tail}")
    lines.append("")
    return "\n".join(lines)


def seed_workspace(project: Path | str, *, seed_dir: Path | str | None = None,
                   force: bool = False) -> dict[str, Any]:
    """把种子包投进一个工作区；只写 `library/` 与 `SEED-README.md`。

    返回读数（`enabled` / `copied` / `skipped` / `destination` / `marker` /
    `seed_dir` / `already` / `problem` / `files`）。`problem` 非空时 `copied` 一定为 0：
    清单坏了就不投，也不落 README（否则下次重试会被"已投过"挡住）。
    """
    workspace = Path(project)
    seed = Path(seed_dir) if seed_dir else default_seed_dir()
    marker = workspace / MARKER_NAME
    destination = workspace / LIB_SUBDIR
    out: dict[str, Any] = {
        "enabled": True, "copied": 0, "skipped": 0,
        "destination": str(destination), "marker": str(marker),
        "seed_dir": str(seed), "already": False, "problem": "", "files": [],
    }
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
        # 先写临时名再改名：中途崩掉不会在 library 里留下半份文件。
        temp = target.with_name(target.name + ".seedtmp")
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
    out["files"] = [str(Path(LIB_SUBDIR) / Path(str(entry["path"])).name) for entry in seeded]
    if problems:
        out["problem"] = "；".join(problems)
    return out


def read_seed_reading(project: Path | str) -> dict[str, Any]:
    """只读地读一个工作区里有没有种子：不算哈希、不写字节。"""
    workspace = Path(project)
    marker = workspace / MARKER_NAME
    destination = workspace / LIB_SUBDIR
    files = sorted(p for p in destination.glob("*.pdf") if p.is_file()) if destination.is_dir() else []
    return {
        "landed": bool(files) and marker.is_file(),
        "count": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "marker": str(marker),
        "destination": str(destination),
    }

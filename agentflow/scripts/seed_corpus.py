#!/usr/bin/env python3
"""SEEDCORPUS：清点历史真机下载、建种子包、按 manifest 复算。

业主 2026-11-21 口径（逐字）：「下一回真机建工作区时，把这十几轮真机所有下载成功且
无乱码的文献都丢进新工作区（不直接入库）」。本脚本负责"哪些份算种子"与"种子可复算"
这两件事；投放动作在 `agentflow.seedinject`（`--seed-literature` 开关）。

## 三条判据（先红后绿的那一侧）

1. 下载成功：`download.status == "ok"`、`bytes > 0`、文件真在 `library/` 下、
   盘上 sha256 与台账 sha256 一致、盘上字节数与台账 `bytes` 一致。
2. 无乱码：对 PDF 真跑 `agentflow.extract.extract_text`（只读），判定只用
   `agentflow.litread.assess_text` 一份判据 —— 与流水线 `text.extract` 拒写乱码、
   `fulltext_tier` 判 `extract_failed` 是同一处真身（改前本脚本自己一份，于是同一份
   PDF 被这边判 usable、被流水线判 garbled）。四档里 `readable` 才算 usable：
   - 噪声：NUL / U+FFFD / 控制字符按占比判（PDF 文字层里少量 NUL 属正常，
     成片的才是错位解码；阈值与实测见 `litread` 的常量注释）；
   - 正文：长度 >= 200、长度 >= 4 的完整英文词 >= 20、英文字母 / 非空白字符
     >= 0.25（排除符号汤 / 单字母串）；`too_short` 是"干净但不够一篇正文"，
     与 `garbled` 一样不进种子。
   另外核 `source_kind == "pdf"`（HTML 落地页不算）与"有文本层"。
   全部过才算 usable；否则记 garbled / no_text_layer / too_short 并写明是哪一条不过。
3. 去重：`agentflow.dedup.literature_keys(title, year, doi)` 造键（DOI -> 标题+年 ->
   标题|*）。同一组里 sha256 相同优先（字节一致），否则取抽读字数最多的一份；
   理由逐组写进 `MANIFEST.json` 的 `selection` / `duplicates`。

## 血统口径

默认只收真机血统的工作区：`lp-ball*` / `dct-min*` / `abelian-smoke*`。其余
`projects/` 下的审阅 / 演示 / 探针工作区（`p2-review`、`project1` 等）仍然被清点，
但不进种子 —— 它们不是业主说的"这十几轮真机"。要全收就加 `--all`。

## 用法

    python scripts/seed_corpus.py --build              # 建种子包（已存在则要 --force）
    python scripts/seed_corpus.py --verify             # 按 manifest 复算 sha256 与抽读字数
    python scripts/seed_corpus.py --list               # 只看清单摘要
    python scripts/seed_corpus.py --inventory-out x.json  # 另放一份逐份清点表

退出码：0 做成了 / 1 查过了、有问题（verify 抓出坏字节也走这一档）/ 2 没查成。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from typing import Any, Mapping

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import dedup as D  # noqa: E402
from agentflow import extract as E  # noqa: E402
from agentflow import litread as LR  # noqa: E402
from agentflow import seedinject as SI  # noqa: E402
from agentflow import settings as SET  # noqa: E402

EXIT_OK = 0
EXIT_RED = 1
EXIT_UNKNOWN = 2

#: 判据本体（改这里等于改"哪份算种子"；报告里逐条引用）。数值不在这里另写：
#: 可读性那几条从 `agentflow.litread` 取 —— 与 `text.extract` 拒写乱码、判收侧的
#: `fulltext_tier` 是同一份判据（改前这里自己一份 `_reading_of` / `_judge`，
#: 于是同一份 PDF 被种子判 usable、被流水线判 garbled）。
CRITERIA: dict[str, Any] = {
    "download_status": "ok",
    "min_bytes": 1,
    "source_kind": "pdf",
    "min_chars": LR.READABLE_MIN_CHARS,
    "replacement_chars_max": LR.GARBLED_REPLACEMENT_MAX,
    "min_long_words": LR.READABLE_MIN_LONG_WORDS,
    "min_alpha_ratio": LR.READABLE_MIN_ALPHA_RATIO,
    "max_control_ratio": LR.GARBLED_CONTROL_RATIO_MAX,
    "max_nul_ratio": LR.GARBLED_NUL_RATIO_MAX,
}

#: 真机血统（业主原话「这十几轮真机」）：只收这几个前缀的工作区。
REAL_WORKSPACE_RE = re.compile(r"^(lp-ball|dct-min|abelian-smoke)")


def _sha256_of(path: Path) -> str:
    """按 1 MiB 分块算 sha256。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reading_of(text: str) -> dict[str, Any]:
    """一份正文的读数（与 `litread.assess_text` 是同一份判据，这里不另算）。"""
    return LR.assess_text(text)


def _judge(reading: Mapping[str, Any]) -> tuple[str, str]:
    """把读数折成 usable / garbled / no_text_layer + 一句凭什么。

    阈值一个都不在这里：`litread.assess_text` 已经按同一份判据给出 `state` 与
    `why`。这里只做"种子口径"的翻译 —— `readable` 才算种子，`too_short` 是
    "干净但不够一篇正文"，与 `garbled` 一样不可用。
    """
    state = str(reading.get("state") or "")
    if state == "readable":
        return "usable", ""
    if state == "no_text_layer":
        return "no_text_layer", str(reading.get("why") or "抽不到任何正文")
    return "garbled", str(reading.get("why") or "判据判它不可读")

def _resolve_pdf(project: Path, rel: str) -> Path:
    """台账里的 `path` 相对 `library/` 解析（不替它猜别的落点）。"""
    raw = str(rel or "").replace("\\", "/")
    path = Path(raw)
    if path.is_absolute():
        return path
    return project / "library" / raw


def _workspace_rows(project: Path) -> list[dict[str, Any]]:
    """读一个工作区的 `data/literature.json`，逐行给读数与判定。"""
    lit_file = project / "data" / "literature.json"
    if not lit_file.is_file():
        return []
    try:
        blob = json.loads(lit_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [{"workspace": project.name, "state": "unreadable",
                 "reason": f"literature.json 读不了：{type(exc).__name__}: {exc}"}]
    rows = blob.get("rows") if isinstance(blob, dict) else blob
    if not isinstance(rows, list):
        return [{"workspace": project.name, "state": "unreadable",
                 "reason": "literature.json 没有 rows 列表"}]
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dl = row.get("download") if isinstance(row.get("download"), dict) else {}
        status = dl.get("status")
        nbytes = int(dl.get("bytes") or 0)
        rec: dict[str, Any] = {
            "workspace": project.name,
            "lit_id": row.get("lit_id") or "",
            "title": row.get("title") or "",
            "doi": row.get("doi") or "",
            "year": row.get("year"),
            "path": row.get("path") or "",
            "download_status": status,
            "bytes": nbytes,
            "sha256_ledger": dl.get("sha256") or "",
            "download_error": dl.get("error"),
            "state": "",
            "reason": "",
        }
        if status != CRITERIA["download_status"] or nbytes < CRITERIA["min_bytes"]:
            rec["state"] = "not-downloaded"
            rec["reason"] = f"download.status={status!r}, bytes={nbytes}"
            out.append(rec)
            continue
        pdf = _resolve_pdf(project, rec["path"])
        rec["abs_path"] = str(pdf)
        rec["source_path"] = f"library/{str(rec['path']).replace(chr(92), '/')}"
        if not pdf.is_file():
            rec["state"] = "missing"
            rec["reason"] = "盘上没有这个文件"
            out.append(rec)
            continue
        rec["on_disk_bytes"] = pdf.stat().st_size
        rec["sha256_disk"] = _sha256_of(pdf)
        if rec["sha256_ledger"] and rec["sha256_disk"] != rec["sha256_ledger"]:
            rec["state"] = "missing"
            rec["reason"] = "盘上 sha256 与台账不符"
            out.append(rec)
            continue
        if rec["on_disk_bytes"] != nbytes:
            rec["state"] = "missing"
            rec["reason"] = f"盘上字节 {rec['on_disk_bytes']} 与台账 bytes {nbytes} 不符"
            out.append(rec)
            continue
        try:
            document = E.extract_text(pdf)
        except Exception as exc:  # noqa: BLE001 —— 抽不动本身是读数，不许静默丢
            rec["state"] = "skipped"
            rec["skip_reason"] = f"{type(exc).__name__}: {exc}"
            out.append(rec)
            continue
        rec["pages"] = len(document.pages)
        rec["source_kind"] = document.source_kind
        reading = _reading_of(document.text)
        rec["reading"] = reading
        if document.source_kind != "pdf":
            # 种子文件按 `.pdf` 命名、工作区的 search.ingest_local 也按 *.pdf 收编：
            # 一份内容其实是 HTML 的"下载成功"不能进种子，否则投放后一打开就报格式不符
            # （真机 lp-ball-3/000000 的 Springer 落地页就是这一档）。
            rec["state"] = "skipped"
            rec["skip_reason"] = (
                f"内容不是 PDF（走的是 {document.source_kind} 抽取），不能放进 .pdf 种子")
            out.append(rec)
            continue
        if not document.pages or not document.text.strip():
            rec["state"] = "no_text_layer"
            rec["reason"] = "pages 为空（疑似扫描件：每页去空白后都为空）"
            out.append(rec)
            continue
        state, why = _judge(reading)
        rec["state"] = state
        rec["reason"] = why
        out.append(rec)
    return out


def inventory(projects_dir: Path) -> dict[str, Any]:
    """清点 `projects/*/data/literature.json`（全部工作区、全部行）。"""
    rows: list[dict[str, Any]] = []
    for lit_file in sorted(projects_dir.glob("*/data/literature.json")):
        rows.extend(_workspace_rows(lit_file.parent.parent))
    return {
        "projects_dir": str(projects_dir),
        "criteria": dict(CRITERIA),
        "workspaces": sorted({row["workspace"] for row in rows}),
        "rows": rows,
    }


def _in_scope(workspace: str, *, include_all: bool) -> bool:
    """这一行是否属于本批种子的血统。"""
    return include_all or bool(REAL_WORKSPACE_RE.match(workspace))


def _union_groups(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """按 `literature_keys` 把行并成组（并查集，避免键的传递性丢边）。"""
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    first: dict[str, int] = {}
    for index, row in enumerate(rows):
        for key in D.literature_keys(row.get("title") or "", row.get("year"),
                                     row.get("doi") or None):
            if key in first:
                union(index, first[key])
            else:
                first[key] = index
    groups: dict[int, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(find(index), []).append(row)
    return [groups[key] for key in sorted(groups)]


def plan_seed(rows: list[dict[str, Any]], *, include_all: bool) -> list[dict[str, Any]]:
    """从清点表里选出种子，并按判重规则登记"留哪一份、为什么"。"""
    usable = [row for row in rows
              if row.get("state") == "usable" and _in_scope(row["workspace"],
                                                            include_all=include_all)]
    planned: list[dict[str, Any]] = []
    for group in _union_groups(usable):
        # 先按抽读字数降序，再按工作区名 / lit_id 定序：同一输入永远得到同一份。
        ordered = sorted(group, key=lambda row: (
            -int(row.get("reading", {}).get("chars", 0)),
            row["workspace"], row["lit_id"]))
        keep = ordered[0]
        distinct_sha = {row.get("sha256_disk") for row in ordered}
        if len(distinct_sha) == 1 and len(ordered) > 1:
            why = ("同字节（sha256 相同）的多份：留抽读字数最多、工作区名靠前的一份")
        elif len(ordered) > 1:
            why = f"sha256 不同：留抽读字数最多的一份（共 {len(ordered)} 份候选）"
        else:
            why = "唯一一份"
        planned.append({
            "keep": keep,
            "selection": why,
            "duplicates": [
                {
                    "workspace": row["workspace"], "lit_id": row["lit_id"],
                    "sha256": row.get("sha256_disk"),
                    "bytes": row["bytes"],
                    "chars": row.get("reading", {}).get("chars"),
                    "why_not_kept": (
                        "同字节的另一份（判重后只留一份）"
                        if row.get("sha256_disk") == keep.get("sha256_disk")
                        else f"抽读字数较少（{row.get('reading', {}).get('chars')} < "
                             f"{keep.get('reading', {}).get('chars')}）"),
                }
                for row in ordered[1:]
            ],
        })
    planned.sort(key=lambda item: (item["keep"]["title"].lower(),
                                   item["keep"]["sha256_disk"]))
    return planned


def _slugify(title: str) -> str:
    """标题 -> 文件名的可读段（非 ASCII 一律折掉；折空了就用 paper）。"""
    folded = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return (slug[:60].strip("-") or "paper")


def _seed_readme(manifest: dict[str, Any]) -> str:
    """种子包根上的 README：怎么用、为什么不能直接入库、谁判收、怎么复算。"""
    count = int(manifest.get("count") or 0)
    total = int(manifest.get("total_bytes") or 0)
    return "\n".join([
        "# 文献种子包（历史真机下载）",
        "",
        f"这是 {count} 份历史真机工作区里下载成功、且抽读无乱码的 PDF，共 {total} 字节。",
        "它们只是文件，不是入库记录。",
        "",
        "## 为什么不能直接入库",
        "",
        "种子口径只回答两件事：下载真的成功了、正文真的抽得出来。它不回答",
        "「与当前研究相关吗」「该不该收录」。入库（分配 lit_id、写 literature 行）",
        "是 A 的判收动作，业主明令这批种子不直接入库。所以投放只把文件放进",
        "工作区的 library/，绝不写 data/literature.json 或任何台账。",
        "",
        "## 怎么投放",
        "",
        "新建工作区时加显式开关（默认关）：",
        "",
        "    agentflow start --project <名字> --mode cold --task \"...\" --seed-literature",
        "",
        "或：",
        "",
        "    agentflow init --root <新工作区> --seed-literature",
        "",
        "投放只做三件事：把 files/ 里的 PDF 原样复制到 <工作区>/library/、",
        "在工作区根落一份 SEED-README.md、别的什么都不写。已有 data/ 的热启动不投。",
        "",
        "## 谁判收",
        "",
        "A。A 必须走候选链，不许把这批文件当已入库：",
        "",
        "1. `search.ingest_local`（books_dir=\"library\"）把盘上文件登记成候选；",
        "2. `lit.stage_add` → `extract` → `fs.read` → `lit.admit` → `lit.admit_all` 逐条判收。",
        "",
        "判收之后才有 lit_id，B 才处理得到它们。",
        "",
        "## 怎么复算",
        "",
        "在 `agentflow/` 下跑：",
        "",
        "    python scripts/seed_corpus.py --verify",
        "",
        "（或在仓库根跑 `python agentflow/scripts/seed_corpus.py --verify`。）",
        "它按 MANIFEST.json 逐份重算 sha256、字节数、抽读字数与 U+FFFD；",
        "任何一份被改动、缺失或字数对不上都以退出码 1 结束。",
        "",
        "## 口径",
        "",
        "- 下载成功：download.status == \"ok\"、bytes > 0、文件在盘上、sha256 与台账一致。",
        "- 无乱码：extract_text 抽到的内容确实是 PDF；判定与流水线共用"
        "`litread.assess_text` 一处真身（正文 >= 200 字符、完整英文词 >= 20、"
        "字母占比 >= 0.25；NUL / U+FFFD / 控制字符按占比判，少量 NUL 属正常）。",
        "  HTML 落地页 / 扫描件（无文本层）不进种子：投放目录按 *.pdf 收编。",
        "- 去重：dedup.literature_keys（DOI -> 标题+年 -> 标题|*）。",
        "- 血统：默认只收 lp-ball* / dct-min* / abelian-smoke*（这十几轮真机）；",
        "  审阅 / 演示 / 探针工作区不进种子。",
        "",
        "逐份来源、判重理由与读数见 MANIFEST.json。",
        "",
    ])


def build_seed(projects_dir: Path, seed_dir: Path, *, include_all: bool = False,
               force: bool = False) -> dict[str, Any]:
    """清点 -> 判重 -> 落盘 `files/` + `MANIFEST.json` + `README.md`。"""
    manifest_path = seed_dir / SI.MANIFEST_NAME
    if manifest_path.is_file() and not force:
        return {"ok": False, "state": "exists",
                "reason": f"{manifest_path} 已在盘上；重建要显式 --force"}
    data = inventory(projects_dir)
    planned = plan_seed(data["rows"], include_all=include_all)
    files_dir = seed_dir / SI.FILES_DIR
    files_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for item in planned:
        row = item["keep"]
        source = Path(row["abs_path"])
        dest_name = f"{row['sha256_disk'][:12]}-{_slugify(row['title'])}.pdf"
        dest = files_dir / dest_name
        shutil.copyfile(source, dest)
        digest = _sha256_of(dest)
        if digest != row["sha256_disk"]:
            return {"ok": False, "state": "copy-mismatch",
                    "reason": f"{source} -> {dest} 的 sha256 不符"}
        entries.append({
            "path": f"{SI.FILES_DIR}/{dest_name}",
            "sha256": digest,
            "bytes": dest.stat().st_size,
            "title": row["title"],
            "doi": row["doi"],
            "year": row["year"],
            "source": {
                "workspace": row["workspace"],
                "lit_id": row["lit_id"],
                "path": row.get("source_path") or row["path"],
                "abs_path": str(source),
            },
            "extract": dict(row.get("reading") or {},
                            pages=row.get("pages"), source_kind=row.get("source_kind")),
            "selection": item["selection"],
            "duplicates": item["duplicates"],
        })
    manifest = {
        "format": SI.FORMAT,
        "version": SI.VERSION,
        "scope": ("all" if include_all else "real-machine: lp-ball* / dct-min* / abelian-smoke*"),
        "criteria": dict(CRITERIA),
        "count": len(entries),
        "total_bytes": sum(int(entry["bytes"]) for entry in entries),
        "files": entries,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8", newline="\n")
    (seed_dir / "README.md").write_text(_seed_readme(manifest), encoding="utf-8", newline="\n")
    # 清单里不再引用的旧文件会变成孤儿：只报出来，不替人删（删除不可逆）。
    referenced = {Path(entry["path"]).name for entry in entries}
    orphans = sorted(p.name for p in files_dir.glob("*.pdf") if p.name not in referenced)
    return {"ok": True, "state": "built", "manifest": str(manifest_path),
            "count": len(entries), "total_bytes": manifest["total_bytes"],
            "orphans": orphans, "scope": manifest["scope"]}


def verify_seed(seed_dir: Path) -> dict[str, Any]:
    """按 manifest 复算：sha256、字节数、抽读字数、U+FFFD、判定。"""
    manifest, problem = SI.read_manifest(seed_dir)
    if manifest is None:
        return {"ok": False, "state": "unknown", "reason": problem, "files": []}
    rows: list[dict[str, Any]] = []
    referenced: set[str] = set()
    ok = True
    for entry in manifest["files"]:
        rel = str(entry["path"]).replace("\\", "/")
        referenced.add(Path(rel).name)
        source = seed_dir / rel
        rec: dict[str, Any] = {
            "path": rel, "title": entry.get("title") or "",
            "sha256_ok": False, "bytes_ok": False, "chars_ok": False,
            "replacement_ok": False, "usable": False, "problems": [],
            "chars_manifest": int((entry.get("extract") or {}).get("chars") or 0),
        }
        if not source.is_file():
            rec["problems"].append("文件不在盘上")
            ok = False
            rows.append(rec)
            continue
        digest = _sha256_of(source)
        rec["sha256_actual"] = digest
        rec["sha256_ok"] = digest == entry["sha256"]
        if not rec["sha256_ok"]:
            rec["problems"].append("sha256 与清单不符")
        size = source.stat().st_size
        rec["bytes_actual"] = size
        rec["bytes_ok"] = size == int(entry["bytes"])
        if not rec["bytes_ok"]:
            rec["problems"].append(f"字节数不符：{size} != {entry['bytes']}")
        try:
            document = E.extract_text(source)
        except Exception as exc:  # noqa: BLE001 —— 抽取失败是读数
            rec["problems"].append(f"抽取抛异常 {type(exc).__name__}: {exc}")
            ok = False
            rows.append(rec)
            continue
        reading = _reading_of(document.text)
        rec["reading"] = reading
        rec["chars_actual"] = reading["chars"]
        rec["chars_ok"] = reading["chars"] == rec["chars_manifest"]
        if not rec["chars_ok"]:
            rec["problems"].append(
                f"抽读字数不符：{reading['chars']} != {rec['chars_manifest']}")
        rec["replacement_ok"] = (reading["replacement_chars"]
                                 <= LR.GARBLED_REPLACEMENT_MAX)
        if not rec["replacement_ok"]:
            rec["problems"].append(f"含 {reading['replacement_chars']} 个 U+FFFD")
        if document.source_kind != CRITERIA["source_kind"]:
            rec["problems"].append(f"抽到的内容是 {document.source_kind}，不是 PDF")
        if not document.pages or not document.text.strip():
            rec["problems"].append("无文本层（pages 为空）")
        state, why = _judge(reading)
        rec["usable"] = state == "usable"
        if not rec["usable"]:
            rec["problems"].append(f"按判据是 {state}：{why}")
        if rec["problems"]:
            ok = False
        rows.append(rec)
    orphans = sorted(p.name for p in (seed_dir / SI.FILES_DIR).glob("*.pdf")
                     if p.name not in referenced) if (seed_dir / SI.FILES_DIR).is_dir() else []
    if orphans:
        ok = False
    return {"ok": ok, "state": "verified" if ok else "red",
            "seed_dir": str(seed_dir), "count": len(rows),
            "orphans": orphans, "files": rows}


def _print_verify(result: dict[str, Any]) -> None:
    """把 verify 的逐份读数印成一张表。"""
    if result.get("state") == "unknown":
        print(f"[seed] 没查成：{result.get('reason')}", file=sys.stderr)
        return
    print(f"种子包 {result['seed_dir']}：{result['count']} 份")
    print(f"{'清单路径':<58} {'sha256':<8} {'字节':<5} {'字数(清单/实测)':<20} 判定")
    for rec in result["files"]:
        sha = "ok" if rec["sha256_ok"] else "BAD"
        byt = "ok" if rec["bytes_ok"] else "BAD"
        chars = f"{rec['chars_manifest']}/{rec.get('chars_actual', '-')}"
        verdict = "可用" if not rec["problems"] else "；".join(rec["problems"])
        print(f"{rec['path']:<58} {sha:<8} {byt:<5} {chars:<20} {verdict}")
    if result.get("orphans"):
        print("未登记的多余文件：" + "、".join(result["orphans"]))
    print(f"结论：{'绿（逐份可复算）' if result['ok'] else '红（有文件对不上清单）'}")


def _print_list(seed_dir: Path) -> int:
    """只读地列出清单摘要（不跑抽取）。"""
    manifest, problem = SI.read_manifest(seed_dir)
    if manifest is None:
        print(f"[seed] 没查成：{problem}", file=sys.stderr)
        return EXIT_UNKNOWN
    print(f"种子包 {seed_dir}：{manifest['count']} 份 / {manifest['total_bytes']} 字节")
    print(f"口径：{manifest.get('scope')}")
    for entry in manifest["files"]:
        extract = entry.get("extract") or {}
        print(f"  {entry['path']}  {extract.get('chars')} 字  "
              f"{entry.get('title')}  doi={entry.get('doi') or '-'}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """命令行入口：--build / --verify / --list（三态退出码见模块 docstring）。"""
    parser = argparse.ArgumentParser(description="历史真机文献种子包：建 / 验 / 列")
    parser.add_argument("--build", action="store_true", help="清点并重建种子包")
    parser.add_argument("--verify", action="store_true", help="按 manifest 复算 sha256 与抽读字数")
    parser.add_argument("--list", action="store_true", help="只列清单摘要")
    parser.add_argument("--force", action="store_true", help="--build 时覆盖已有清单")
    parser.add_argument("--all", action="store_true",
                        help="--build 时收全部工作区（默认只收 lp-ball*/dct-min*/abelian-smoke*）")
    parser.add_argument("--projects-dir", default=None,
                        help="projects 落点（缺省：工作区根下的 projects/）")
    parser.add_argument("--seed-dir", default=None,
                        help="种子包落点（缺省：agentflow/seed/literature 或 AGENTFLOW_SEED_LITERATURE_DIR）")
    parser.add_argument("--inventory-out", default=None,
                        help="另写一份逐份清点表 JSON（包含未下载 / 缺文件 / 乱码的行）")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args(argv)

    projects_dir = Path(args.projects_dir) if args.projects_dir else (SET.WORKSPACE_ROOT / "projects")
    seed_dir = Path(args.seed_dir) if args.seed_dir else SI.default_seed_dir()

    if args.inventory_out:
        data = inventory(projects_dir)
        inv_path = Path(args.inventory_out)
        inv_path.parent.mkdir(parents=True, exist_ok=True)
        inv_path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8", newline="\n")
        print(f"清点表：{inv_path}（{len(data['rows'])} 行 / {len(data['workspaces'])} 个工作区）")
        if not (args.build or args.verify or args.list):
            return EXIT_OK

    if args.build:
        got = build_seed(projects_dir, seed_dir, include_all=args.all, force=args.force)
        if args.json:
            print(json.dumps(got, ensure_ascii=False, indent=1))
        elif got["ok"]:
            print(f"种子包建好：{seed_dir}")
            print(f"  份数 {got['count']} / 总字节 {got['total_bytes']}")
            print(f"  口径 {got['scope']}")
            print(f"  清单 {got['manifest']}")
            if got["orphans"]:
                print(f"  未登记的多余文件（没删，请人看）：{'、'.join(got['orphans'])}")
        else:
            print(f"[seed] 没建成：{got['reason']}", file=sys.stderr)
        return EXIT_OK if got["ok"] else EXIT_UNKNOWN
    if args.verify:
        result = verify_seed(seed_dir)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=1))
        else:
            _print_verify(result)
        return EXIT_OK if result["ok"] else (
            EXIT_UNKNOWN if result["state"] == "unknown" else EXIT_RED)
    return _print_list(seed_dir)


if __name__ == "__main__":
    raise SystemExit(main())

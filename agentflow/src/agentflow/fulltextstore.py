# -*- coding: utf-8 -*-
#
# ③ 跑 `python scripts/lint_rules.py` 确认 error 0（本模块每个公开函数都写了 docstring，

"""抽取正文的内容寻址库：整本书的正文只存一份，产物里只留引用。

## 它解决什么

`evidence.json` 曾经把每条来源的逐页正文内联两份（`text` 与 `text_pages`），
于是同一批书在每份产物里各存一份完全相同的文本：实测 14 份产物共 112,013,714 字节，
其中 109,101,969 字节（97.4%）是正文，而按内容哈希归并只有 7 份不同正文 / 85 份副本
（读数见 `temp/_ev_store_inventory.py`）。同一次运行里断言级证据其实只有 388 字符。

本模块把正文按内容寻址存进项目根的 `.fulltext/` 目录，产物里只留 `text_ref`
（绝对路径 + 两个哈希 + 页数 + 字符数）。文件名里带内容哈希 ⇒ 追加式：
换一个抽取器只会多出一个新文件，老产物的引用永远仍然有效。

## 为什么哈希有两段，为什么是这个口径

文件名是 `<pdf 哈希前 16>-<正文哈希前 16>.json`：

- 只按 pdf 哈希命名 ⇒ 换个抽取器就覆盖同名文件，历史产物的引用当场失效
  （把已登记的证据弄坏，比浪费字节严重得多）；
- `text_sha256` 的口径逐字沿用被删掉的那个 `text` 字段的构造式
  `sha256("\\n".join(pages))` ⇒ 复核者一行就能重算，不必猜新口径。

## 状态纪律（三态）

`load()` 不抛异常，返回 `(pages, problem)`：只有 `problem == ""` 才是"读到了、核过了"。
坏法各有名字与逐字理由（`store_file_missing` / `store_text_hash_mismatch` /
`store_pages_mismatch` / `store_out_of_store` / `store_not_a_store_file` 等）。
调用方据此把回验降到摘要级时，必须把 `problem` 原样写进理由 ——
"引用坏了 ⇒ 没做成全文级回验"与"这篇没有全文"是两句话，折叠起来就是假陈述。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

#: store 文件的格式版本。改结构必须同时改它（读侧按它拒绝不认识的版本）。
STORE_VERSION = 1

#: 项目根下放抽取正文的目录名（与项目根已有的 `.sequence` 同族：点开头 = 派生数据）。
STORE_DIR_NAME = ".fulltext"

#: 文件名里哈希取前多少位十六进制。16 位 = 64 bit，够区分「同一批书的不同抽取版本」。
HASH_PREFIX = 16


def pages_text_sha256(pages: Sequence[str]) -> str:
    """正文的内容哈希：口径与被删掉的 `text` 字段逐字一致（`"\\n".join(pages)`）。"""
    return hashlib.sha256("\n".join(str(p) for p in pages).encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str:
    """整个文件的 sha256（十六进制小写）。文件不存在时抛 `OSError`，由调用方归类。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def store_dir_for(project_dir: str | Path) -> Path:
    """项目根 → 这个项目的 store 目录（只算路径，不建目录）。"""
    return Path(project_dir) / STORE_DIR_NAME


def ref_name(pdf_sha256: str, pages: Sequence[str]) -> str:
    """算出一份正文在 store 里的文件名（`<pdf8…>-<text8…>.json`）。"""
    pdf = str(pdf_sha256 or "").strip().lower()[:HASH_PREFIX] or "0" * HASH_PREFIX
    return f"{pdf}-{pages_text_sha256(pages)[:HASH_PREFIX]}.json"


def put(pages: Sequence[str], *, store_dir: str | Path, pdf_sha256: str = "",
        pdf_path: str = "", pdf_bytes: int = 0, backend: str = "",
        encoding: str | None = None) -> dict:
    """把一份逐页正文存进 store，返回可写进产物的 `text_ref`。

    幂等：同名文件已存在且自校验通过就直接复用它（不重写、不更新时间戳）；
    校验不过（内容对不上）才重写。写盘是"先写临时文件再 `os.replace`"，
    所以读到半个文件的可能为零。

    返回的引用里两个哈希都要有：`text_sha256` 是正文内容哈希（可由 `text_pages`
    重算），`file_sha256` 是整个 store 文件的字节哈希（防的是文件被截断/被改字段名）。
    """
    text = [str(p) for p in pages]
    if not text:
        raise ValueError("put() 收到空正文：没有内容的 store 文件不是证据，是噪声")
    directory = Path(store_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ref_name(pdf_sha256, text)

    text_hash = pages_text_sha256(text)
    if target.is_file():
        existing, problem = _read_store_file(target)
        if not problem and existing.get("text_sha256") == text_hash:
            return _ref_of(target, existing)

    payload = {
        "store_version": STORE_VERSION,
        "pdf_sha256": str(pdf_sha256 or ""),
        "pdf_path": str(pdf_path or ""),
        "pdf_bytes": int(pdf_bytes or 0),
        "backend": str(backend or ""),
        "encoding": encoding,
        "pages": len(text),
        "chars": sum(len(p) for p in text),
        "text_sha256": text_hash,
        "text_pages": text,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1, default=str)
    tmp = target.with_name(target.name + f".tmp{os.getpid()}")
    tmp.write_text(blob, encoding="utf-8", newline="\n")
    os.replace(tmp, target)

    stored, problem = _read_store_file(target)
    if problem:
        # 写完立刻回读：写盘失败不许"看起来成功"（引用一旦写进产物就会被当成证据）。
        raise OSError(f"store 文件写完回读失败：{problem}（{target}）")
    return _ref_of(target, stored)


def _ref_of(path: Path, stored: Mapping[str, Any]) -> dict:
    """由已落盘的 store 文件造出产物侧要写的 `text_ref`。"""
    return {
        "store": f"fulltext-store@{STORE_VERSION}",
        "path": str(path.resolve()),
        "text_sha256": str(stored.get("text_sha256") or ""),
        "file_sha256": file_sha256(path),
        "pages": int(stored.get("pages") or 0),
        "chars": int(stored.get("chars") or 0),
        "pdf_sha256": str(stored.get("pdf_sha256") or ""),
    }


def _read_store_file(path: Path) -> tuple[dict, str]:
    """读一个 store 文件并做结构自校验；返回 `(内容, 问题)`，问题为空串才算读成。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, f"store_file_missing：{path}"
    except OSError as exc:
        return {}, f"store_file_unreadable：{path}（{type(exc).__name__}: {exc}）"
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return {}, f"store_file_unreadable：{path}（不是 JSON：{exc}）"
    if not isinstance(data, dict) or "text_pages" not in data or "text_sha256" not in data:
        return {}, f"store_not_a_store_file：{path}（缺 text_pages/text_sha256）"
    if int(data.get("store_version") or 0) != STORE_VERSION:
        return {}, (f"store_not_a_store_file：{path}（store_version="
                    f"{data.get('store_version')!r}，本实现只认 {STORE_VERSION}）")
    return data, ""


def _store_allowed(path: Path, allowed_dir: str | Path | None) -> str:
    """引用指向的位置是不是合法 store：返回问题串（空串 = 合法）。

    为什么要有这一层：`text_ref` 是产物里的一行文本。若不加限制，一份被改过的
    evidence.json 可以把 `path` 指到任意文件，于是"逐字回验"会拿一份与文献无关的
    文本当依据 —— 那正是"引文被凭空验成真"的入口。两种放行口径：
    给了 `allowed_dir` 就必须落在它里面；没给则要求父目录名就是 `.fulltext`（结构判据）。
    """
    resolved = path.resolve()
    if allowed_dir is not None:
        base = Path(allowed_dir).resolve()
        if resolved.parent != base:
            return f"store_out_of_store：{resolved} 不在允许的 store 目录 {base} 里"
        return ""
    if resolved.parent.name != STORE_DIR_NAME:
        return (f"store_out_of_store：{resolved} 的父目录不是 {STORE_DIR_NAME}/"
                f"（产物里的引用只许指向 store）")
    return ""


def load(ref: Any, *, allowed_dir: str | Path | None = None,
         verify_file_hash: bool = True) -> tuple[list[str], str]:
    """按 `text_ref` 读出逐页正文；返回 `(pages, 问题)`，问题为空串才算读成。

    校三层，任何一层不过都不返回文本（宁可不核，也不许拿可疑文本去核引文）：
    1. 引用形态与位置（`store_not_a_mapping` / `store_out_of_store`）；
    2. 整个 store 文件的字节哈希（`store_file_hash_mismatch`，防截断/改字段）；
    3. 正文哈希与页数（`store_text_hash_mismatch` / `store_pages_mismatch`）。
    """
    if not isinstance(ref, Mapping):
        return [], f"store_not_a_mapping：text_ref 是 {type(ref).__name__}"
    raw_path = ref.get("path")
    if not raw_path:
        return [], "store_not_a_mapping：text_ref 缺 path"
    path = Path(str(raw_path))
    bad = _store_allowed(path, allowed_dir)
    if bad:
        return [], bad

    want_file = str(ref.get("file_sha256") or "")
    if verify_file_hash and want_file:
        try:
            got_file = file_sha256(path)
        except FileNotFoundError:
            return [], f"store_file_missing：{path}"
        except OSError as exc:
            return [], f"store_file_unreadable：{path}（{type(exc).__name__}: {exc}）"
        if got_file != want_file:
            return [], (f"store_file_hash_mismatch：{path}"
                        f"（引用登记 {want_file[:16]}…，实测 {got_file[:16]}…）")

    data, problem = _read_store_file(path)
    if problem:
        return [], problem

    pages = [str(p) for p in (data.get("text_pages") or [])]
    if not pages:
        return [], f"store_not_a_store_file：{path}（text_pages 是空的）"

    want_text = str(ref.get("text_sha256") or "")
    got_text = pages_text_sha256(pages)
    if want_text and got_text != want_text:
        return [], (f"store_text_hash_mismatch：{path}"
                    f"（引用登记 {want_text[:16]}…，实测 {got_text[:16]}…）")
    want_pages = ref.get("pages")
    if want_pages is not None and int(want_pages) != len(pages):
        return [], (f"store_pages_mismatch：{path}"
                    f"（引用登记 {want_pages} 页，文件里 {len(pages)} 页）")
    return pages, ""


def verify_ref(ref: Any, *, allowed_dir: str | Path | None = None) -> dict:
    """给一条 `text_ref` 出一份体检读数（CLI `evidence verify` 与判据都用它）。

    返回 `{"ok", "problem", "path", "pages", "chars", "text_sha256"}`：
    `ok=True` 表示三层校验全过；`ok=False` 时 `problem` 逐字说明坏在哪一层。
    """
    pages, problem = load(ref, allowed_dir=allowed_dir)
    out = {
        "ok": not problem,
        "problem": problem,
        "path": str((ref or {}).get("path") or "") if isinstance(ref, Mapping) else "",
        "pages": len(pages),
        "chars": sum(len(p) for p in pages),
        "text_sha256": str((ref or {}).get("text_sha256") or "")
        if isinstance(ref, Mapping) else "",
    }
    return out


def inventory(store_dir: str | Path) -> list[dict]:
    """列出 store 里的文件与它们的自校验结论（CLI `evidence store` 用）。

    每个元素是 `{"path", "bytes", "pages", "chars", "text_sha256", "ok", "problem"}`。
    目录不存在时返回空表 —— 调用方必须把"空"与"零字节"分开说，别让空库看起来像通过。
    """
    directory = Path(store_dir)
    if not directory.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        data, problem = _read_store_file(path)
        rows.append({
            "path": str(path),
            "bytes": path.stat().st_size,
            "pages": int(data.get("pages") or 0),
            "chars": int(data.get("chars") or 0),
            "text_sha256": str(data.get("text_sha256") or ""),
            "ok": not problem,
            "problem": problem,
        })
    return rows


def selftest() -> int:
    """自检：正控（存了再读、正文一致）+ 负控（翻一个字节、删文件、越界引用都必须报错）。

    为什么自检要做负控：一个"永远说 ok"的校验器与没有校验器在输出上完全一样，
    而它更坏 —— 它让人以为核过了。负控在这里当场把三种坏法各跑一遍。
    """
    import tempfile

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        pages = ["第一页 alpha", "第二页 beta gamma"]
        ref = put(pages, store_dir=Path(tmp) / STORE_DIR_NAME, pdf_sha256="ab" * 32,
                  pdf_path="x.pdf", pdf_bytes=3, backend="pdf")
        got, why = load(ref, allowed_dir=Path(tmp) / STORE_DIR_NAME)
        if why or got != pages:
            problems.append(f"正控失败：{why or got}")
        if not verify_ref(ref, allowed_dir=Path(tmp) / STORE_DIR_NAME)["ok"]:
            problems.append("正控失败：verify_ref 说坏")

        # 负控 1：改一个字节
        target = Path(ref["path"])
        blob = target.read_text(encoding="utf-8").replace("beta", "BETA")
        target.write_text(blob, encoding="utf-8", newline="\n")
        _pages, why = load(ref, allowed_dir=Path(tmp) / STORE_DIR_NAME)
        if "store_file_hash_mismatch" not in why:
            problems.append(f"负控 1 失败（改字节未被抓）：{why!r}")

        # 负控 2：删文件
        target.unlink()
        _pages, why = load(ref, allowed_dir=Path(tmp) / STORE_DIR_NAME)
        if "store_file_missing" not in why:
            problems.append(f"负控 2 失败（删文件未被抓）：{why!r}")

        # 负控 3：引用指向 store 之外
        outside = Path(tmp) / "elsewhere.json"
        outside.write_text(json.dumps({"store_version": STORE_VERSION, "text_pages": ["x"],
                                       "text_sha256": pages_text_sha256(["x"])}, default=str),
                           encoding="utf-8")
        _pages, why = load({"path": str(outside), "text_sha256": pages_text_sha256(["x"])})
        if "store_out_of_store" not in why:
            problems.append(f"负控 3 失败（越界引用未被抓）：{why!r}")

    if problems:
        for p in problems:
            print(f"[fulltextstore] {p}")
        return 1
    print("[fulltextstore] 正控 + 三个负控都对（存/读/字节哈希/缺文件/越界）")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手工自检入口
    raise SystemExit(selftest())

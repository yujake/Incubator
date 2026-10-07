# -*- coding: utf-8 -*-
"""正文共享度盘点：同一本书的抽取正文到底被存了几份、理论能省多少。

B 案（正文按内容寻址只留一份）要能回答两件事，都在这里出读数：

1. **重复度**：把所有产物的全文正文按 `sha256("\\n".join(pages))` 归并，
   同一哈希出现几次就是「同一本书的同一份文本被存了几份」；
2. **可回收量**：当前内联总量 − 保留一份的量（只算理论值，**不动盘**）。

改后（产物里只有 `text_ref`）同一个脚本仍然跑得通：那时正文在
`projects/<项目>/.fulltext/<pdf8>-<text16>.json` 里，脚本的 store 段
会报「几个 store 文件 / 共多少字节 / 每份被多少产物引用」。

用法：
    python temp/_ev_store_inventory.py                 # 全 D:\\Incubator\\projects
    python temp/_ev_store_inventory.py <根目录>

退出码：0=查过并给出读数（含「本来就是一份」这种正常结论） · 2=没查成（根目录不存在）
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent


def text_hash(pages: list[str]) -> str:
    """正文的内容哈希：口径与被删掉的 `text` 字段完全一致（`"\\n".join(pages)`）。"""
    return hashlib.sha256("\n".join(pages).encode("utf-8")).hexdigest()


def scan_artifacts(root: pathlib.Path) -> tuple[dict[str, list[str]], int, list[str]]:
    """扫所有 `evidence.json`：返回 `(正文哈希 → 引用它的产物路径列表, 内联正文总字节, 问题)`。"""
    by_hash: dict[str, list[str]] = defaultdict(list)
    inline_total = 0
    problems: list[str] = []
    for ev_path in sorted(root.glob("*/out/run-*/evidence.json")):
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
        except Exception as exc:
            problems.append(f"{ev_path}: 读不了（{type(exc).__name__}: {exc}）")
            continue
        rel = str(ev_path.relative_to(root))
        for s in ev.get("sources") or []:
            full = s.get("fulltext") or {}
            pages = [str(x) for x in (full.get("text_pages") or [])]
            if not pages:
                continue
            nb = len(json.dumps(pages, ensure_ascii=False).encode("utf-8"))
            nb += len(str(full.get("text") or "").encode("utf-8"))
            inline_total += nb
            by_hash[text_hash(pages)].append(rel)
    return dict(by_hash), inline_total, problems


def scan_store(root: pathlib.Path) -> tuple[list[tuple[str, int]], list[str], list[str]]:
    """扫 store 文件（`*/\.fulltext/*.json`）：返回 `([(路径, 字节)], 引用了它的产物, 问题)`。"""
    rows: list[tuple[str, int]] = []
    referenced: list[str] = []
    problems: list[str] = []
    for p in sorted(root.glob("*/.fulltext/*.json")):
        rows.append((str(p.relative_to(root)), p.stat().st_size))
    for ev_path in sorted(root.glob("*/out/run-*/evidence.json")):
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
        except Exception as exc:
            problems.append(f"{ev_path}: 读不了（{type(exc).__name__}: {exc}）")
            continue
        for s in ev.get("sources") or []:
            ref = (s.get("fulltext") or {}).get("text_ref")
            if isinstance(ref, dict) and ref.get("path"):
                p = pathlib.Path(str(ref["path"]))
                if not p.is_file():
                    problems.append(f"{ev_path}: text_ref 指向的文件不在（{p}）")
                else:
                    referenced.append(str(p))
    return rows, referenced, problems


def main() -> int:
    root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "projects"
    if not root.is_dir():
        print(f"[没查成] 根目录不存在：{root}")
        return 2

    by_hash, inline_total, problems = scan_artifacts(root)
    print(f"== 产物侧：{root} ==")
    print(f"  内联正文总量            {inline_total:>12,d} 字节")
    print(f"  不同正文（按内容哈希）  {len(by_hash):>12,d} 份")
    dup = sum(len(v) for v in by_hash.values())
    print(f"  正文副本总数            {dup:>12,d} 份")
    if by_hash:
        unique_bytes = 0
        for _h, refs in sorted(by_hash.items(), key=lambda kv: -len(kv[1])):
            first = refs[0]
            ev = json.loads((root / first).read_text(encoding="utf-8"))
            # 单份字节：取该产物里哈希相符的那些来源之和（同一本书在一份产物里出现一次）
            nb = 0
            for s in ev.get("sources") or []:
                full = s.get("fulltext") or {}
                pages = [str(x) for x in (full.get("text_pages") or [])]
                if pages and text_hash(pages) == _h:
                    nb += len(json.dumps(pages, ensure_ascii=False).encode("utf-8"))
                    nb += len(str(full.get("text") or "").encode("utf-8"))
            unique_bytes += nb
            extra = "" if len(refs) == 1 else f"  ← 存了 {len(refs)} 份"
            print(f"    {_h[:12]}…  {nb:>12,d} 字节 × {len(refs)}  {extra}")
        print(f"  保留一份即可的量        {unique_bytes:>12,d} 字节")
        if inline_total:
            print(f"  理论可回收              {inline_total - unique_bytes:>12,d} 字节"
                  f"  （{(inline_total - unique_bytes) / inline_total:.1%}）")

    rows, referenced, store_problems = scan_store(root)
    print(f"\n== store 侧（改后才会有） ==")
    if not rows:
        print("  store 文件 0 个（改前形态，或这个根下还没跑过新版本）")
    else:
        print(f"  store 文件 {len(rows)} 个 / 共 {sum(n for _p, n in rows):,d} 字节")
        for p, n in rows:
            share = sum(1 for r in referenced if pathlib.Path(r).name == pathlib.Path(p).name)
            print(f"    {p}  {n:>12,d} 字节  被 {share} 份产物引用")

    all_problems = problems + store_problems
    for p in all_problems:
        print(f"  [问题] {p}")
    print(f"\n===== 汇总：问题 {len(all_problems)} 条 =====")
    return 1 if all_problems else 0


if __name__ == "__main__":
    sys.exit(main())

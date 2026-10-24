# -*- coding: utf-8 -*-
"""`agentflow evidence migrate` 的实现真身（移植期工具，从 `cli.py` 原样搬来）。

它把历史产物里内联的正文（`fulltext.text_pages`）迁成引用形态（`fulltext.text_ref`），
依据 `draft/30` §T0-7。这是一次性迁移：迁完之后工作区里就没有内联正文了，
所以它不该长期占着 CLI 的一个动词。

为什么默认只 dry-run：这一步改的是历史证据本体（产物里那一段正文），
"改证据"这种事必须由人显式点头（`--apply`），而且每一份都要先备份。

`main(args)` 的入参就是 `cmd_evidence` 收到的那个 namespace（读 `target` 与 `apply`），
与搬走前读的是同样两格 —— 这是"逐字节不变"的前提。
"""
from __future__ import annotations

import json
from pathlib import Path


def main(args) -> int:
    """迁移历史产物里的内联正文（默认 dry-run；`--apply` 才动盘，动盘前逐份备份）。"""
    from agentflow import fulltextstore as FS
    from agentflow import schema as S
    from agentflow import tty

    project_dir = Path(args.target)
    apply = bool(getattr(args, "apply", False))

    store_dir = project_dir / FS.STORE_DIR_NAME
    todo: list[tuple[Path, int, int]] = []
    for ev_path in sorted(project_dir.glob("out/run-*/evidence.json")):
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(tty.bullet(tty.paint(f"跳过（读不了）：{ev_path}", "yellow")))
            continue
        n = 0
        saved = 0
        for src in ev.get("sources") or []:
            full = src.get("fulltext") or {}
            pages = [str(p) for p in (full.get("text_pages") or [])]
            if pages and not full.get("text_ref"):
                n += 1
                saved += len(json.dumps(pages, ensure_ascii=False, default=str).encode("utf-8"))
        if n:
            todo.append((ev_path, n, saved))

    if not todo:
        print(tty.bullet("没有需要迁移的产物（都已经没有内联正文）"))
        return 0
    total = sum(s for _p, _n, s in todo)
    for line in tty.table(("产物", "内联来源数", "可省字节"),
                          [(str(p.relative_to(project_dir)), str(n), str(s)) for p, n, s in todo]):
        print(line)
    if not apply:
        print(tty.bullet(f"dry-run：将写 {total} 字节进 {store_dir}，"
                         f"改写 {len(todo)} 份产物（加 --apply 才动盘；动盘前逐份备份）"))
        return 0

    stamp = S.now_iso().replace(":", "").replace("-", "")[:15]
    backup_dir = Path(str(store_dir.parent / "temp")) / f"evidence-migrate-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    for ev_path, _n, _s in todo:
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
        backup = backup_dir / f"{ev_path.parent.name}-evidence.json"
        backup.write_bytes(ev_path.read_bytes())
        for src in ev.get("sources") or []:
            full = src.get("fulltext") or {}
            pages = [str(p) for p in (full.get("text_pages") or [])]
            if not (pages and not full.get("text_ref")):
                continue
            ref = FS.put(pages, store_dir=store_dir, pdf_sha256=str(full.get("sha256") or ""),
                         pdf_path=str(full.get("path") or ""), pdf_bytes=int(full.get("bytes") or 0),
                         backend=str(full.get("backend") or ""))
            full.pop("text_pages", None)
            full.pop("text", None)
            full["text_ref"] = ref
            full["chars"] = int(ref.get("chars") or 0)
            full["text_store"] = "ref"
        ev_path.write_text(json.dumps(ev, ensure_ascii=False, indent=1, default=str) + "\n",
                           encoding="utf-8", newline="\n")
        done += 1
    print(tty.bullet(f"已迁移 {done} 份产物；备份在 {backup_dir}"))
    return 0

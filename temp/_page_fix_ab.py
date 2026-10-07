"""把"提示词页码口径"那处修复做成可判定的前后对照（真跑，用真 key）。

做法（为什么要另起一个项目）：`project1` 里那本书的关系是**改前**抽的，混在一起数不干净。
所以这里准备一个只放那一本书的目录，灌进一个新项目（project4），只抽它，
然后按"声明页码 vs 实际页码"逐条比：

  改前（project1 的 lit 0004，2026-09-28）：12 条里 12 条页码错，恒定比实际小 5；
  改后（project4 的同一本书）：页码错的条数应当是 0。

用法：python temp\\_page_fix_ab.py [--books-from D:\\books]
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import sys

sys.path.insert(0, r"D:\Incubator\agentflow\src")

ROOT = pathlib.Path(r"D:\Incubator")
ONE = ROOT / "temp" / "one-book"
TARGET = "Math--Bertsekas_Tsitsiklis_Introduction_to_probability.pdf"
NEW_PROJECT = "project4"


def norm(t: str) -> str:
    t = str(t or "").replace("\u00ad", "")
    t = re.sub(r"-\s*\n\s*", "", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def main() -> int:
    from agentflow.extract import extract_text
    from agentflow import projects as P

    ONE.mkdir(parents=True, exist_ok=True)
    src = pathlib.Path(r"D:\books") / TARGET
    if not (ONE / TARGET).is_file():
        shutil.copy2(src, ONE / TARGET)
    print(f"只放一本书的目录：{ONE}（{TARGET}，{src.stat().st_size} 字节）")

    res = P.run_project(P.projects_dir(None), name=NEW_PROJECT, start="auto",
                        topic="probability and statistics inference",
                        books_dir=ONE, extract=True, extract_rounds=2,
                        budget_usd=0.5, max_calls=1)
    ex = res["run"].get("extraction") or {}
    print(f"冷/热：{res['project']['mode']}；抽取读数：读 {ex.get('processed')} / "
          f"失败 {ex.get('failed')} / 概念 {ex.get('concepts_created')} / "
          f"关系 {ex.get('relations_added')} / 引文过验 {ex.get('quotes_verified')} / "
          f"未过 {ex.get('quotes_failed')}")

    root = P.projects_dir(None) / NEW_PROJECT
    lit = json.loads((root / "data" / "literature.json").read_text(encoding="utf-8"))["rows"]
    rels = json.loads((root / "data" / "relations.json").read_text(encoding="utf-8"))["rows"]
    if not rels:
        print("[!!] 没有抽到任何关系，没法做前后对照")
        return 1
    doc = extract_text(str(root / "library" / str(lit[0]["path"])))
    pages = [str(p) for p in (getattr(doc, "pages", []) or [])]

    wrong = right = missing = 0
    for r in rels:
        q = norm(r.get("quote"))
        pr = r.get("page_range") or {}
        d0, d1 = int(pr.get("start") or 1), int(pr.get("end") or pr.get("start") or 1)
        if not q:
            missing += 1
            continue
        declared_hit = any(q in norm(p) for p in pages[max(0, d0 - 1):d1])
        actual = [i + 1 for i, p in enumerate(pages) if q in norm(p)]
        if declared_hit:
            right += 1
        else:
            wrong += 1
            print(f"  [页码仍错] {r.get('relation_id')} 声明 {d0}-{d1}，实际 {actual[:3]}")
        _ = r.get("quote_verified")

    print()
    print(f"对照结果（同一本书、同一个模型、只差提示词里那一条）：")
    print(f"  改前（project1）：12/12 条页码错（恒定比实际小 5）")
    print(f"  改后（{NEW_PROJECT}）：{right} 条页码对得上 / {wrong} 条仍错 / 空引文 {missing}"
          f"（共 {len(rels)} 条）")
    return 0 if wrong == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

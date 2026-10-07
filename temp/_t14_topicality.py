"""`T1.4` · 检索切题率探针（2026-09-27，零 API 花费：只走检索、不调模型）。

它回答的问题（`draft/28` §100 / `temp/DECISION-PAGE-20260927.md` 题 1）：
  产品默认路径（`evidence.retrieve(topic, search_fn=None)` ⇒ 禁改区里的 `providers`，
  缺省 OpenAlex + Crossref）取回来的来源，**到底切不切题**？

口径（全部写出来，免得事后各说各话）：
  · `kb_overlap` = |topic 的汉字二元组 ∩ 来源标题+摘要前 400 字的二元组| / |topic 的二元组|
    —— "topic 里有多少个二字片段在来源里出现过"，0..1。它只做观测，**不用来过滤**。
  · `hit` = 产品自己的 `providers.keyword_hit(topic, title)`：True / False / **None（无法判定）**。
  · `keep` = 产品自己的 `providers._precise_keep(...)` 的 (是否保留, filter_note)
    —— 看它到底"判过了"还是"弃权了"。
  · `rejected` = `evidence.retrieve` 汇总里那几个数（今天只有 rejected，没有"弃权"这一档）。

用法：`$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'; cd D:\\Incubator\\agentflow`
      `python D:\\Incubator\\temp\\_t14_topicality.py`
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\Incubator\agentflow\src")))

from agentflow import evidence as E          # noqa: E402
from agentflow import providers as P          # noqa: E402

OUT = Path(r"D:\Incubator\temp\t14-topicality.json")

#: 题面：中文数学（本框架的主场）+ 一条英文做对照 + 一条与 T1 完全相同的题面
TOPICS = [
    "同调代数中导出函子的长正合列",          # = T1 / T1.5 的原题面（已知结果差）
    "图论中的拉姆齐数下界",
    "素数分布中的筛法",
    "紧黎曼曲面上全纯微分形式的维数",
    "有限群表示论中的特征标正交关系",
    "long exact sequence of derived functors",   # 英文对照
]

CJK = re.compile(r"[\u4e00-\u9fff]")


def bigrams_cjk(text: str) -> set[str]:
    """只取汉字二元组（跳过非汉字字符）。返回的是"相邻两个汉字"的片段集合。"""
    chars = [c for c in text]
    out: set[str] = set()
    for i in range(len(chars) - 1):
        a, b = chars[i], chars[i + 1]
        if CJK.match(a) and CJK.match(b):
            out.add(a + b)
    return out


def overlap(topic: str, source: dict) -> float | None:
    """topic 的汉字二元组有多少比例在来源的标题+摘要里出现过。"""
    t = bigrams_cjk(topic)
    if not t:
        return None
    body = " ".join(str(source.get(k) or "") for k in ("title", "abstract"))
    s = bigrams_cjk(body)
    return round(len(t & s) / len(t), 3)


def main() -> int:
    rows: list[dict] = []
    print(f"{'topic':<34} {'st':<4} {'n':>2} {'rej':>4} {'hit=None':>9} {'keep':>6} "
          f"{'min kb':>7} {'max kb':>7} {'mean kb':>8}")
    for topic in TOPICS:
        t0 = time.time()
        got = E.retrieve(topic, limit=5, search_fn=None)
        took = round(time.time() - t0, 1)
        srcs = got.get("sources") or []
        detail: list[dict] = []
        for s in srcs:
            hit = P.keyword_hit(topic, str(s.get("title") or ""))
            keep, note = P._precise_keep(topic, str(s.get("title") or ""), str(s.get("abstract") or ""))
            detail.append({
                "source_id": s.get("source_id"),
                "year": s.get("year"),
                "title": (str(s.get("title") or ""))[:120],
                "keyword_hit": hit,
                "keep": keep,
                "filter_note": note,
                "kb_overlap": overlap(topic, s),
            })
        kbs = [d["kb_overlap"] for d in detail if d["kb_overlap"] is not None]
        none_n = sum(1 for d in detail if d["keyword_hit"] is None)
        row = {
            "topic": topic,
            "status": got.get("status"),
            "checked": got.get("checked"),
            "reason": got.get("reason"),
            "n_sources": len(srcs),
            "rejected": len(got.get("rejected") or []),
            "sources_detail": got.get("sources_detail"),
            "keyword_hit_none": none_n,
            "kept": sum(1 for d in detail if d["keep"]),
            "kb_min": min(kbs) if kbs else None,
            "kb_max": max(kbs) if kbs else None,
            "kb_mean": round(sum(kbs) / len(kbs), 3) if kbs else None,
            "seconds": took,
            "sources": detail,
        }
        rows.append(row)
        print(f"{topic[:32]:<34} {str(row['status'])[:3]:<4} {row['n_sources']:>2} {row['rejected']:>4} "
              f"{none_n:>9} {row['kept']:>6} {str(row['kb_min']):>7} {str(row['kb_max']):>7} "
              f"{str(row['kb_mean']):>8}   ({took}s)")

    OUT.write_text(json.dumps({
        "produced_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "how": "evidence.retrieve(topic, limit=5, search_fn=None) —— 与产品默认路径同一条",
        "note": "kb_overlap 只做观测、不用来过滤；keyword_hit/keep 是产品自己的判定",
        "rows": rows,
    }, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")

    print("\n=== 汇总 ===")
    n = len(rows)
    all_none = sum(1 for r in rows if r["n_sources"] and r["keyword_hit_none"] == r["n_sources"])
    print(f"主题 {n} 个；其中 {all_none} 个主题**全部候选的 keyword_hit 都是 None（精筛整体弃权）**")
    vals = [r["kb_mean"] for r in rows if r["kb_mean"] is not None]
    if vals:
        print(f"kb_overlap 均值：min={min(vals)} / max={max(vals)} / 平均={round(sum(vals)/len(vals), 3)}")
    print(f"全部来源里 kb_overlap == 0 的条数："
          f"{sum(1 for r in rows for d in r['sources'] if d['kb_overlap'] == 0)}"
          f" / {sum(r['n_sources'] for r in rows)}")
    print(f"\n明细落盘：{OUT}")
    for r in rows:
        print(f"\n--- {r['topic']}（{r['status']}，{r['n_sources']} 条，耗时 {r['seconds']}s）---")
        for d in r["sources"]:
            print(f"   kb={str(d['kb_overlap']):>5}  hit={str(d['keyword_hit']):>5}  keep={d['keep']}  "
                  f"[{d['filter_note']}]  {d['title'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

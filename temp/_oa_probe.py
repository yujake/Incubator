"""OpenAlex 取回链路的现场探针（`C-2`/O6=0 的根因定位）。

只读探针：不发写操作、不落任何仓内文件。做法是把 `agentflow.providers.http_get_json`
换成一个记录器，原样打印产品实际发出去的 URL/参数与载荷 `meta.count`，
再报告 provider 自己的读数（stats / last_query_text / last_topicality / 候选条数）。

用法（先设好 PYTHONPATH=src，cd D:\\Incubator\\agentflow）：
  python -u D:\\Incubator\\temp\\_oa_probe.py [--topic "..."] [--mode topical]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import agentflow.providers as P

REAL = P.http_get_json
CALLS: list[dict] = []


def spy(url, params=None, **kw):
    payload = REAL(url, params, **kw)
    rec = {
        "url": url,
        "params": {k: (v if not isinstance(v, tuple) else list(v)) for k, v in (params or {}).items()},
        "payload_type": type(payload).__name__,
    }
    if isinstance(payload, dict):
        meta = payload.get("meta") or {}
        rec["meta_count"] = meta.get("count")
        rec["results_len"] = len(payload.get("results") or [])
        first = (payload.get("results") or [None])[0]
        if isinstance(first, dict):
            inv = first.get("abstract_inverted_index")
            rec["first_has_abstract"] = bool(inv)
            rec["first_id"] = first.get("id")
            rec["first_title"] = (first.get("title") or "")[:60]
    CALLS.append(rec)
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="")
    ap.add_argument("--mode", default="topical")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    topic = args.topic
    if not topic:
        tsv = pathlib.Path(r"D:\Incubator\temp\t3-topics.tsv")
        lines = [ln for ln in tsv.read_text(encoding="utf-8").splitlines() if ln.strip()]
        topic = lines[1].split("\t")[1].strip()
    print(f"topic = {topic!r}\nmode  = {args.mode}\n")

    P.http_get_json = spy
    prov = P.OpenAlexProvider()
    print(f"per_page={prov.per_page} max_pages={prov.max_pages} mailto={prov.mailto!r}")
    print(f"user_agent={prov.user_agent!r}\n")

    cands = prov.search(topic, args.mode, limit=args.limit)
    print(f"== 候选条数 = {len(cands)}")
    print("== stats = " + json.dumps(prov.stats, ensure_ascii=False))
    print("== last_query_text = " + json.dumps(prov.last_query_text, ensure_ascii=False))
    print("== last_filter_notes = " + json.dumps(prov.last_filter_notes, ensure_ascii=False))
    print(f"== last_filtered_out = {prov.last_filtered_out}")
    print("== last_query_provenance = " + json.dumps(prov.last_query_provenance, ensure_ascii=False))
    top = getattr(prov, "last_topicality", None)
    if top is not None:
        print("== last_topicality = " + json.dumps(top, ensure_ascii=False, default=str))
    print(f"\n== 实际发出的请求 {len(CALLS)} 次")
    for i, rec in enumerate(CALLS, 1):
        print(f"  [{i}] {rec['url']}")
        print("      params=" + json.dumps(rec["params"], ensure_ascii=False))
        print(f"      meta.count={rec.get('meta_count')} results={rec.get('results_len')} "
              f"first_has_abstract={rec.get('first_has_abstract')} id={rec.get('first_id')}")
    for c in cands[:3]:
        raw = getattr(c, "raw", {}) or {}
        print(f"  cand title={(getattr(c, 'title', '') or '')[:60]!r} "
              f"filtered_out={raw.get('filtered_out')} note={raw.get('filter_note')!r} "
              f"abstract_len={len(getattr(c, 'abstract', '') or '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

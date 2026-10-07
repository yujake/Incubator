"""自己量 `.noai-approvals.json` 的 `audits`（两份报告互相矛盾 ⇒ 必须由父代理裁决）。

背景：`d09eea42` 报"16 条各有 1 条 `audits`（共 16）"，`R1c` 报"`audits` 0"。
两者读的是**同一个文件、同一个 sha**（`8175efc213d9b0ee`，mtime `2026-09-26 05:04:26`）。
⇒ 必有一方口径错（或把不同字段名当成 `audits`）。这里把结构摊开逐条数，不做推断。

用法：`python D:\\Incubator\\temp\\_probe_ledger_audits.py`
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LEDGER = Path(r"D:\Incubator\agentflow\.noai-approvals.json")


def main() -> int:
    d = json.loads(LEDGER.read_text(encoding="utf-8"))
    print(f"顶层键：{sorted(d)}")
    entries = d.get("entries") or []
    print(f"条目数：{len(entries)}；generated_at={d.get('generated_at')}")

    tot_audits = 0
    tot_reviewers = 0
    with_audits = 0
    samples = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        a = e.get("audits")
        r = e.get("reviewers")
        n_a = len(a) if isinstance(a, (list, dict)) else (0 if a is None else 1)
        n_r = len(r) if isinstance(r, (list, dict)) else (0 if r is None else 1)
        tot_audits += n_a
        tot_reviewers += n_r
        if n_a:
            with_audits += 1
            if len(samples) < 3:
                samples.append((e.get("path"), a))
    print(f"\n**reviewers 元素总数 = {tot_reviewers}**（16 条应当全 0）")
    print(f"**audits 元素总数   = {tot_audits}**；非空 audits 的条目数 = {with_audits}")
    print("\n抽 3 条 audits 看它们是什么（谁写的、什么时候、scope 是什么）：")
    for path, a in samples:
        print(f"  --- {path}")
        if isinstance(a, list):
            for x in a[:2]:
                print(f"      {json.dumps(x, ensure_ascii=False)[:300]}")
        else:
            print(f"      {json.dumps(a, ensure_ascii=False)[:300]}")

    # 反向确认：`reviewers_total` 是不是派生量（README:293 的口径）
    print(f"\n根层有没有 `reviewers_total` 字段：{'reviewers_total' in d}")
    print("\n【判据五对照】允许的形态是：reviewers 全 0（待人签）。"
          "`audits` 非 0 的含义必须单独说明 —— 它不是'批准'，但它也不是 0。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

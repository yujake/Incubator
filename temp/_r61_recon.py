# -*- coding: utf-8 -*-
"""R-61 前置查证（只读）：`attack_plans.history` 的条目里到底记了什么？

R-61 的两条路里我倾向"只读反推"（从 history 尾推"最近一次触碰该子目标的轮次"），
前提是 history 条目里**记得住子目标**。若没记，那条路不成立，只能加 schema 字段（人裁）。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, r"D:\Incubator\agentflow\src")
from agentflow.store import Store  # noqa: E402

P2 = pathlib.Path(r"D:\Incubator\projects\p2-review")
ROOT = pathlib.Path(r"D:\Incubator")


def main() -> int:
    for label, root in (("p2-review", P2), ("probe-f4", ROOT / "projects" / "probe-f4")):
        if not (root / "data").is_dir():
            print(f"[{label}] 跳过：没有 data/")
            continue
        st = Store(root)
        plans = st.rows("attack_plans")
        print(f"[{label}] 计划 {len(plans)} 个")
        keys: set[str] = set()
        sample = None
        for p in plans:
            for e in (p.get("history") or []):
                keys |= set(e)
                if sample is None and e:
                    sample = e
        print(f"    history 条目的键并集 = {sorted(keys)}")
        if sample:
            print(f"    样例 = {json.dumps(sample, ensure_ascii=False)[:300]}")
        for p in plans:
            h = list(p.get("history") or [])
            if h:
                print(f"    plan {p.get('plan_id')}：history {len(h)} 条；末条键={sorted(h[-1])}")
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())

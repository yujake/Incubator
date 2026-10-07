# -*- coding: utf-8 -*-
"""探针 2：`precise` 模式下 description 怎么给，结果最好（真机、只读）。

上面那个探针的读数：同一个 topic，
- `topical`（默认）⇒ 15 条里几乎全是无关文献（异常扩散 / 分子演化 / 自旋电子学…）；
- `precise` ⇒ 8 条**全部对题**（The extremal process of BBM、Poissonian statistics…）。
差别是 `precise` 那一档带 `keyword_hit` 后置过滤。

这一轮问的是"默认该给哪个 mode"：把 `description` 的三种给法各跑一遍，
看哪一档既对题、又不把结果削没。
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"D:\Incubator\agentflow\src")

TOPIC = "Poisson point process of the extremal process of branching Brownian motion"
#: 用户（角色）通常会怎么描述"我要找什么"。
DESC_SHORT = "extremal process of branching Brownian motion"
DESC_EMPTY = ""


def run(label: str, mode: str, description: str) -> None:
    from agentflow import providers as P

    prov = P.OpenAlexProvider()
    print("=" * 100)
    print(f"{label}：mode={mode} description={description[:60]!r}")
    try:
        cands = prov.search(TOPIC, mode, description, 10)
    except Exception as exc:  # noqa: BLE001
        print(f"  [抛异常] {type(exc).__name__}: {exc}")
        return
    notes = getattr(prov, "last_filter_notes", None)
    print(f"  回去 {len(cands)} 条；过滤说明={notes}")
    hits = 0
    for c in cands:
        title = str(getattr(c, "title", ""))
        on = any(k in title.lower() for k in ("branching brownian", "extremal"))
        hits += 1 if on else 0
        print(f"    {'✓' if on else ' '} {title[:78]}  ({getattr(c, 'year', None)})")
    print(f"  ⇒ 对题 {hits}/{len(cands)}")


def main() -> int:
    run("A", "precise", DESC_EMPTY)
    run("B", "precise", DESC_SHORT)
    run("C", "topical", DESC_SHORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())

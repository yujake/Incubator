# -*- coding: utf-8 -*-
"""探针：`precise` 模式下**中文 description** 会把查询串弄成什么（真机、只读）。

现场：真机场景 II 里 G 自己写了一段中文 description（"论文包引言 used_by=… 需要一条
外部文献支撑：分支布朗运动极值过程的 Poisson 点过程"），A 的 `search_literature` 返回
`outcome=no_results`；而 §202 里同一句英文 topic、**不带 description** 时是 7/8 对题。
这个探针把两种给法打出来的查询串与结果并列，看清是哪一步把结果清零的。
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"D:\Incubator\agentflow\src")

TOPIC = "Poisson point process of the extremal process of branching Brownian motion"
DESC_CN = ("论文包引言 used_by=main.tex:introduction 需要一条外部文献支撑："
           "分支布朗运动极值过程的 Poisson 点过程")
DESC_EN = "extremal process of branching Brownian motion"


def run(label: str, mode: str, description: str) -> None:
    from agentflow import providers as P

    prov = P.OpenAlexProvider()
    print("=" * 96)
    print(f"{label}: mode={mode} description={description[:55]!r}")
    try:
        cands = prov.search(TOPIC, mode, description, 10)
    except Exception as exc:  # noqa: BLE001
        print(f"  [抛异常] {type(exc).__name__}: {exc}")
        return
    print(f"  query_text={getattr(prov, 'last_query_text', None)}")
    print(f"  provenance={getattr(prov, 'last_query_provenance', None)}")
    print(f"  过滤={getattr(prov, 'last_filter_notes', None)}  回去 {len(cands)} 条")
    for c in cands[:5]:
        print(f"    - {str(getattr(c, 'title', ''))[:76]}")


def main() -> int:
    run("A 中文 description", "precise", DESC_CN)
    run("B 英文 description", "precise", DESC_EN)
    run("C 中文 description + topical", "topical", DESC_CN)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""只读探针：真实工作区里 `documents.claims[].citations` 到底长什么样（R-03 裸号白名单的证据）。

为什么要先扫真实数据：主控要求"哪些 kind 允许裸号（逐个列，**给现算证据**：今天真机上出现的
裸号长什么样、在哪个字段）"。这件事不能靠读代码推断 —— 代码只能告诉我"裸号会被拒"，
拒的是不是真存在的东西只有数据知道。

输出：每个工作区一行小结 + 裸号样本 + 前缀分布 + 每条引用在不在册（按 kind→表）。
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, r"D:\Incubator\agentflow\src")

from agentflow.store import Store  # noqa: E402
from agentflow import textutil as T  # noqa: E402

ROOTS = (pathlib.Path(r"D:\Incubator\projects"), pathlib.Path(r"D:\Incubator\agentflow\projects"))
BARE = re.compile(r"^\d{4}$")


def _workspaces() -> list[pathlib.Path]:
    out = []
    for base in ROOTS:
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if p.is_dir() and (p / "data").is_dir():
                out.append(p)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    roots = _workspaces()
    print(f"# 工作区 {len(roots)} 个：{[p.name for p in roots]}\n")
    total_pref: dict[str, int] = {}
    total_bare: list[tuple[str, str]] = []
    total_other: list[tuple[str, str]] = []
    rows_seen = 0
    for ws in roots:
        try:
            st = Store(ws)
            docs = st.rows("documents")
        except Exception as exc:  # noqa: BLE001 —— 读不了就如实说，不折成"没有引用"
            print(f"## {ws.name}: 读不了（{type(exc).__name__}: {exc}）")
            continue
        pref: dict[str, int] = {}
        bare: list[str] = []
        other: list[str] = []
        for d in docs:
            for c in (d.get("claims") or []):
                for raw in (c.get("citations") or []):
                    rows_seen += 1
                    kind, ref = T.citation_ref_parts(raw)
                    if BARE.match(str(raw).strip()):
                        bare.append(str(raw))
                    elif kind and not ref:
                        # 无冒号、又不是 4 位数字 ⇒ 整串被当成前缀
                        other.append(str(raw))
                    else:
                        pref[kind] = pref.get(kind, 0) + 1
        for k, v in pref.items():
            total_pref[k] = total_pref.get(k, 0) + v
        total_bare += [(ws.name, b) for b in bare]
        total_other += [(ws.name, o) for o in other]
        print(f"## {ws.name}: documents={len(docs)} 行 / 引用 {sum(pref.values()) + len(bare) + len(other)} 条")
        print(f"   前缀分布：{pref}")
        print(f"   裸号：{len(bare)} 条 {sorted(set(bare))[:12]}")
        print(f"   无冒号且非裸号（整串当前缀）：{len(other)} 条 {sorted(set(other))[:8]}")
    print(f"\n# 合计：引用 {rows_seen} 条")
    print(f"#   前缀分布：{dict(sorted(total_pref.items()))}")
    print(f"#   裸号 {len(total_bare)} 条：{sorted(set(b for _w, b in total_bare))[:20]}")
    print(f"#   其它无冒号 {len(total_other)} 条：{sorted(set(o for _w, o in total_other))[:20]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""为 `draft/74` 采"真实工作区"的证据：每张表/每件产物的**字段名、条数、样本**。

为什么要它：配合矩阵里"输入从哪读 / 展示什么"这两列必须能被第三方复算 ——
`file:line` 只能证明"这个函数在"，**证明不了"它读出来的东西长这样"**。
这里逐项打出来源路径 + 条数 + 字段名（+ 一行样本的**键与非空键**，不打印长正文）。
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

AGENTFLOW = pathlib.Path(r"D:\Incubator\agentflow")
sys.stdout.reconfigure(encoding="utf-8")


def keys_of(row: dict) -> list[str]:
    return sorted(row)


def nonempty(row: dict) -> list[str]:
    return sorted(k for k, v in row.items() if v not in (None, "", [], {}, 0, False))


def load_rows(path: pathlib.Path) -> tuple[list[dict], str]:
    if not path.is_file():
        return [], "不在盘上"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, dict) and isinstance(doc.get("rows"), list):
        return [r for r in doc["rows"] if isinstance(r, dict)], f"rows 数组，{len(doc['rows'])} 行"
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)], f"数组，{len(doc)} 行"
    return [], f"未知形状 {type(doc).__name__}"


def table(ws: pathlib.Path, name: str, sample_filter=None) -> None:
    rows, note = load_rows(ws / "data" / name)
    print(f"\n### data/{name}   （{note}）")
    if not rows:
        print("  （没有行）")
        return
    print(f"  行数 {len(rows)}；字段（并集）：{keys_of_factory(rows)}")
    pick = rows[0]
    if sample_filter:
        for r in rows:
            if sample_filter(r):
                pick = r
                break
    print(f"  样本的非空键：{nonempty(pick)}")


def keys_of_factory(rows: list[dict]) -> str:
    out: set[str] = set()
    for r in rows:
        out |= set(r)
    return ", ".join(sorted(out))


def main() -> int:
    targets = sys.argv[1:] or ["p9b-post-fix-replay", "p6r-paper-from-results"]
    for name in targets:
        ws = AGENTFLOW / "projects" / name
        print("=" * 78)
        print(f"# 工作区 {name}    ({ws})")
        if not ws.is_dir():
            print("  （不在盘上）")
            continue
        for t in ("tasks", "search_requests", "statements", "conjectures", "experiments",
                  "review_findings", "relations", "literature", "usage_ledger", "documents"):
            table(ws, f"{t}.json")
        # tasks 的 inputs 标记（扇出受理 / 记账写回）
        rows, _ = load_rows(ws / "data" / "tasks.json")
        marks = Counter()
        for r in rows:
            for m in (r.get("inputs") or []):
                marks[str(m).split(":")[0] + ":" + str(m).split(":")[-1]] += 1
        print(f"\n### tasks.inputs 的标记分布（扇出受理 `conductor:admitted` / 记账写回 `tokenmeter:settled`）：")
        for k, v in marks.most_common(6):
            print(f"  {v:4}  {k}")
        # 事件与会话的种类分布
        for rel, label in (("data/events.jsonl", "台账事件"), ("sessions", "会话事件")):
            p = ws / rel
            if rel.endswith(".jsonl"):
                files = [p] if p.is_file() else []
            else:
                files = sorted(p.glob("*.jsonl")) if p.is_dir() else []
            cnt: Counter = Counter()
            total = 0
            for f in files:
                for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    cnt[str(d.get("kind"))] += 1
                    total += 1
            print(f"\n### {label}（{len(files)} 个文件 / {total} 行）kind 分布 top10：")
            for k, v in cnt.most_common(10):
                print(f"  {v:5}  {k}")
        # 交接账本
        hp = ws / "manuscripts" / "handoffs.jsonl"
        if hp.is_file():
            lines = [l for l in hp.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
            print(f"\n### manuscripts/handoffs.jsonl：{len(lines)} 行")
            if lines:
                first = json.loads(lines[0])
                print(f"  首行键：{keys_of(first)}")
                print(f"  首行非空键：{nonempty(first)}")
        # 产物台账
        ap = ws / "ARTIFACTS.jsonl"
        if ap.is_file():
            lines = [l for l in ap.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
            print(f"\n### ARTIFACTS.jsonl：{len(lines)} 行")
            if lines:
                first = json.loads(lines[0])
                print(f"  首行键：{keys_of(first)}")
                print(f"  首行非空键：{nonempty(first)}")
        # 六件产物
        for run in sorted(ws.glob("out/run-*")):
            print(f"\n### {run.relative_to(ws).as_posix()}/ 的内容：")
            for f in sorted(run.iterdir()):
                print(f"  {f.stat().st_size:9,} B  {f.name}")
        # 停机/进程/锚/论文包
        for rel in (".agentflow-stop", "runs", "doc-signatures", "paper", "verifications.jsonl"):
            p = ws / rel
            if p.exists():
                if p.is_dir():
                    n = len(list(p.rglob("*")))
                    print(f"\n### {rel}/（目录，{n} 项）")
                else:
                    print(f"\n### {rel}（{p.stat().st_size} B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

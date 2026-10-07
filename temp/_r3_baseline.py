# -*- coding: utf-8 -*-
"""R3 的**改前真机读数**（只读）：`bits` 到底有没有落过、`statements ↔ experiments` 两头各空多少。

口径（逐条写清，可复算）：
- 扫描面：`D:\\Incubator\\agentflow\\projects\\*` 与 `D:\\Incubator\\projects\\*` 两个根下的
  `data/statements.json`、`data/experiments.json`（工作区相对路径由 `store` 的布局决定；找不到就跳过并计数）。
- `statements` 的"带 bits 的行" = 行里 `bits` 是非空 mapping（`{}` 与缺失都算**没有**）。
- `statements.experiment_ids` 与 `subgoals.proof_experiment_ids` 的"非空行数"。
- 三态：文件读不成 ⇒ 单独一档（不折进 0）。

为什么必须先有这个数：R3 的判据是「同一份读数从 0 变成 >0」。如果 `bits` 本来就有值，
那条判据就是**真空**（永远绿），必须如实写成 `na`。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

ROOTS = [pathlib.Path(r"D:\Incubator\agentflow\projects"), pathlib.Path(r"D:\Incubator\projects")]
TABLES = ("statements", "experiments", "subgoals", "documents")


def _load(p: pathlib.Path) -> tuple[list[dict], str]:
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"[:120]
    if isinstance(raw, dict):
        raw = raw.get("rows") or raw.get("data") or []
    if not isinstance(raw, list):
        return [], f"形状不是 list（{type(raw).__name__}）"
    return [r for r in raw if isinstance(r, dict)], ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"D:\Incubator\temp\r3-baseline-改前.md")
    a = ap.parse_args()

    tally: dict[str, Counter] = {t: Counter() for t in TABLES}
    per_ws: list[tuple[str, int, int, int]] = []   # (ws, statements 行, 带 bits 行, experiment_ids 非空行)
    broken: list[tuple[str, str]] = []
    seen_files = 0

    for root in ROOTS:
        if not root.is_dir():
            continue
        for ws in sorted(p for p in root.iterdir() if p.is_dir()):
            srows, serr = _load(ws / "data" / "statements.json")
            if (ws / "data" / "statements.json").is_file():
                seen_files += 1
                if serr:
                    broken.append((str(ws / "data/statements.json"), serr))
            withbits = sum(1 for r in srows if isinstance(r.get("bits"), dict) and r.get("bits"))
            withexp = sum(1 for r in srows if r.get("experiment_ids"))
            tally["statements"]["行"] += len(srows)
            tally["statements"]["带 bits"] += withbits
            tally["statements"]["experiment_ids 非空"] += withexp
            if srows:
                per_ws.append((ws.name, len(srows), withbits, withexp))
            for t, key in (("experiments", "实验行"), ("subgoals", "子目标行"), ("documents", "稿件行")):
                rows, err = _load(ws / "data" / f"{t}.json")
                if (ws / "data" / f"{t}.json").is_file() and err:
                    broken.append((str(ws / "data" / f"{t}.json"), err))
                tally[t][key] += len(rows)
                if t == "subgoals":
                    tally[t]["proof_experiment_ids 非空"] += sum(1 for r in rows if r.get("proof_experiment_ids"))

    lines = ["# R3 改前真机读数（`bits` 与 `statements ↔ experiments`）", ""]
    lines.append(f"- 扫描面：`agentflow/projects/*` + `projects/*` 的 `data/*.json`；见到 `statements.json` 的工作区 **{len(per_ws)}** 个（读不成 {len(broken)} 个）")
    lines.append("")
    lines.append("| 表 | 读数 |")
    lines.append("|---|---|")
    for t in TABLES:
        for k, v in tally[t].items():
            lines.append(f"| `{t}` | {k} = **{v}** |")
    lines.append("")
    lines.append("## 逐工作区（只有有 statements 行的才列）")
    lines.append("")
    lines.append("| 工作区 | statements 行 | **带 bits** | experiment_ids 非空 |")
    lines.append("|---|---:|---:|---:|")
    for name, n, b, e in per_ws:
        lines.append(f"| `{name}` | {n} | {b} | {e} |")
    lines.append("")
    lines.append("## 读不成的（异常，不折进 0）")
    lines.append("")
    lines.extend([f"- `{p}` ⇒ {why}" for p, why in broken] or ["- （无）"])
    lines.append("")
    pathlib.Path(a.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"报告：{a.out}")
    print(f"  statements 行 {tally['statements']['行']} / 带 bits {tally['statements']['带 bits']} / "
          f"experiment_ids 非空 {tally['statements']['experiment_ids 非空']}")
    print(f"  experiments 行 {tally['experiments']['实验行']} / subgoals 行 {tally['subgoals']['子目标行']} / "
          f"proof_experiment_ids 非空 {tally['subgoals']['proof_experiment_ids 非空']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

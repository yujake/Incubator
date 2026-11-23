"""`check_wellformed` —— 一个工作区里的产物有没有畸形（只读，零模型调用）。

用法：

```
python scripts/check_wellformed.py --root projects/lp-ball-15
python scripts/check_wellformed.py --root projects/lp-ball-15 --kind relations --kind tasks
python scripts/check_wellformed.py --root projects/lp-ball-15 --json
```

退出码（三态纪律，与 `noai_gate.py` / `usage_ledger_audit.py` 同源）：

- `0` = 全 ok（查过了，没有畸形）；
- `1` = 有畸形（有 error/warning 的 Finding；逐条在输出里）；
- `2` = 没查成（工作区不存在、某类的文件读不出来、指定的类别没实现）。

`2` 绝不折成 `0`：读不出来与"没有畸形"是两件事。`info` 的 Finding（例如手稿登记之后
才落的签块让 ARTIFACTS 的 sha 落后一格）不改退出码，但它照样逐条列出来。

判据本体在 `src/agentflow/wellformed/`（一处判据：`__init__.py` 汇总对外面，规则按产物
类别各一个模块）；本脚本只做参数解析与呈现。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import wellformed as WF  # noqa: E402


def _parse_kinds(values: list[str] | None) -> list[str] | None:
    """把 `--kind a --kind b` 与 `--kind a,b` 两种写法摊成同一个清单。"""
    if not values:
        return None
    out: list[str] = []
    for one in values:
        for piece in str(one).split(","):
            name = piece.strip()
            if name and name not in out:
                out.append(name)
    return out or None


def _render_text(report: WF.WorkspaceReport) -> list[str]:
    """人读的呈现：抬头三行 + 逐条 Finding + 没查成的那一段。"""
    lines: list[str] = [f"工作区 {report.root}",
                        f"三态   state={report.state}  exit={report.exit_code}"]
    states: dict[str, int] = {}
    for res in report.results:
        states[res.state] = states.get(res.state, 0) + 1
    lines.append("类别   " + "  ".join(f"{k}={v}" for k, v in sorted(states.items())))
    findings = report.findings
    if findings:
        lines.append("")
        lines.append(f"逐条读数（{len(findings)} 条；error 在前）：")
        for f in findings:
            lines.append(f"  [{f.severity}] {f.kind} · {f.where}")
            lines.append(f"      {f.detail}")
    else:
        lines.append("")
        lines.append("逐条读数：无（这一类产物查过了、没有畸形）")
    unchecked = [r for r in report.results if r.state == WF.UNCHECKED]
    if unchecked:
        lines.append("")
        lines.append(f"没查成的 {len(unchecked)} 类（这些不是「没有畸形」）：")
        for r in unchecked:
            lines.append(f"  {r.kind}：{'；'.join(r.reasons) or '没给理由'}")
    notes = [f"{r.kind}：{one}" for r in report.results for one in r.notes]
    if notes:
        lines.append("")
        lines.append(f"顺带的读数（{len(notes)} 条，不算畸形）：")
        lines.extend(f"  {one}" for one in notes)
    lines.append("")
    lines.append({WF.OK: "结论：全 ok（0）",
                  WF.MALFORMED: "结论：有畸形（1）—— 逐条见上，处置由人定",
                  WF.UNCHECKED: "结论：没查成（2）—— 0 不是「没有畸形」"}[report.state])
    return lines


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码。

    不钉的后果（本机实测 2026-11-22）：GBK 控制台打印 `⇒` / 中文读数会抛
    UnicodeEncodeError，进程以 1 结束 —— 而那正好是"有畸形"的码，于是
    "打印不出来"被读成"查出了畸形"；`--json` 那一支还会让父进程按 utf-8 解码失败。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    """入口：解析参数、跑判据、按三态返回退出码。"""
    _pin_utf8()
    parser = argparse.ArgumentParser(
        description="查一个工作区的产物有没有畸形（只读；0=全 ok / 1=有畸形 / 2=没查成）")
    parser.add_argument("--root", default="",
                        help="工作区根（例如 projects/lp-ball-15）")
    parser.add_argument("--kind", action="append", default=None,
                        help="只查这一类（可重复，或逗号分隔）；缺省查全部")
    parser.add_argument("--json", action="store_true", help="输出机器读数")
    parser.add_argument("--list-kinds", action="store_true", help="列出可查的类别后退出")
    args = parser.parse_args(argv)

    if args.list_kinds:
        print("\n".join(WF.KINDS))
        return WF.EXIT_OK

    if not str(args.root or "").strip():
        print("必须给 --root <工作区根>（或用 --list-kinds 看可查的类别）", file=sys.stderr)
        return WF.EXIT_UNCHECKED

    kinds = _parse_kinds(args.kind)
    if kinds:
        unknown = [k for k in kinds if k not in WF.KINDS]
        if unknown:
            print(f"没有这几类：{unknown}（可查：{list(WF.KINDS)}）", file=sys.stderr)
            return WF.EXIT_UNCHECKED
    root = Path(args.root)
    if not root.is_dir():
        print(f"工作区不存在：{root} ⇒ 没查成（不是「没有畸形」）", file=sys.stderr)
        return WF.EXIT_UNCHECKED

    report = WF.check_workspace(root, kinds)
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=1))
    else:
        print("\n".join(_render_text(report)))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())

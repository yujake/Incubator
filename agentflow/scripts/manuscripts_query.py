# -*- coding: utf-8 -*-
"""查交接手稿 + 顺手打印被引用命题的五元位快照（`draft/39` §C4）。

## 为什么要有这个脚本（而不是让模型现读）

用户 2026-10-05 的口径：五元位快照由脚本查。理由有两层：

1. 手稿是"跨角色的交接记录"，读它的场合往往不是模型在跑循环（人验收、另一个角色冷启动、
收工后复核）—— 那些场合没有模型上下文可用，只有盘；
2. 让模型去"读一遍台账再自己算等级"，等于把派生等级这件机械事交给一个会读错的读者；
等级在本仓只有一个来源（`evidencebits.derive_grade`），脚本调它。

## 用法

```text python scripts/manuscripts_query.py <工作区>                 # 最近 20 份python scripts/manuscripts_query.py <工作区> --id 0007        # 读一份（正文全文）python scripts/manuscripts_query.py <工作区> --to F --since 2026-10-05 python scripts/manuscripts_query.py <工作区> --refs 0004 --json python scripts/manuscripts_query.py <工作区> --bits           # 附五元位快照```

`--bits` 做的事：把每份手稿 `refs` 里的 `stmt:<id>` / `exp:<id>` 解析出来，去工作区`data/statements.json` /
`data/experiments.json` 里取出对应行，用 `evidencebits` 现算五位与派生等级。读了但没有那两处引用的手稿，快照写"（没有可算的命题引用）
"——"没有引用"与"引用算不出来"必须分得开（三态纪律）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from agentflow import evidencebits as EB  # noqa: E402
from agentflow import manuscripts as MS  # noqa: E402


def _load_rows(ws: pathlib.Path, table: str) -> list[dict]:
    p = ws / "data" / f"{table}.json"
    if not p.is_file():
        return []
    try:
        got = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return list(got.get("rows") or [])


def five_bit_snapshot(ws: pathlib.Path, rec: dict) -> list[dict]:
    """一份手稿引到的命题/实验 ⇒ 五元位快照（全部现算，不读盘上存的等级）。"""
    refs = [str(x) for x in (rec.get("refs") or [])]
    stmt_refs = [r.split(":", 1)[1] for r in refs if r.startswith("stmt:")]
    exp_refs = [r.split(":", 1)[1] for r in refs if r.startswith("exp:")]
    out: list[dict] = []
    if stmt_refs:
        rows = {str(r.get("stmt_id") or ""): r for r in _load_rows(ws, "statements")}
        for sid in stmt_refs:
            row = rows.get(sid)
            if row is None:
                out.append({"ref": f"stmt:{sid}", "state": "not_found",
                            "note": "工作区台账里没有这条命题（引用悬空）"})
                continue
            bits = EB.bits_from_row(row)
            out.append({"ref": f"stmt:{sid}", "state": "ok", "grade": bits["grade"],
                        "grade_label": EB.GRADE_LABELS[bits["grade"]],
                        "bits": {b: bits[b] for b in EB.BIT_NAMES},
                        "problems": EB.bit_problems(bits)})
    if exp_refs:
        rows = {str(r.get("experiment_id") or ""): r for r in _load_rows(ws, "experiments")}
        for eid in exp_refs:
            row = rows.get(eid)
            if row is None:
                out.append({"ref": f"exp:{eid}", "state": "not_found",
                            "note": "工作区台账里没有这条实验（引用悬空）"})
                continue
            out.append({"ref": f"exp:{eid}", "state": "ok",
                        "method": str(row.get("method") or ""),
                        "result": str(row.get("result") or ""),
                        "exit_code": row.get("exit_code")})
    return out


def _format_bits(snap: list[dict]) -> str:
    if not snap:
        return "  （没有可算的命题引用）"
    lines = []
    for item in snap:
        if item.get("state") != "ok":
            lines.append(f"  - {item['ref']}：{item.get('note') or item['state']}")
            continue
        if "grade" in item:
            flags = "".join("1" if item["bits"][b] in (True, "verified") else "0"
                            for b in EB.BIT_NAMES)
            lines.append(f"  - {item['ref']}：{item['grade_label']}（{item['grade']}）"
                         f" 五位={flags}")
            if item["problems"]:
                lines.append(f"      不合规：{'；'.join(item['problems'])}")
        else:
            lines.append(f"  - {item['ref']}：{item['method']} / {item['result']}"
                         f" / exit={item['exit_code']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="查交接手稿（manuscripts/handoffs.jsonl）")
    ap.add_argument("workspace", help="工作区根（含 manuscripts/ 与 data/）")
    ap.add_argument("--id", default="", help="按编号读一份（打成全文）")
    ap.add_argument("--to", default="", help="按收件人过滤（ALL 只给广播）")
    ap.add_argument("--from", dest="sender", default="", help="按发件人过滤")
    ap.add_argument("--since", default="", help="只给这个时间之后（ISO 前缀比，如 2026-10-05）")
    ap.add_argument("--refs", default="", help="只给引用了这个编号/对象的手稿")
    ap.add_argument("--limit", type=int, default=20, help="最多几份（缺省 20）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（给脚本/下游用）")
    ap.add_argument("--bits", action="store_true", help="附被引用命题的五元位快照")
    args = ap.parse_args(argv)

    ws = pathlib.Path(args.workspace).resolve()
    if not ws.is_dir():
        print(f"[unknown] 工作区不在盘上：{ws} —— 没查成，不是「没有手稿」", file=sys.stderr)
        return 2
    got, problems = MS.query(ws, mid=args.id, to=args.to, sender=args.sender,
                             since=args.since, refs=args.refs, limit=args.limit)
    snaps = {str(r.get("id") or ""): five_bit_snapshot(ws, r) for r in got} if args.bits else {}

    if args.json:
        payload = {"workspace": str(ws), "count": len(got),
                   "bad_lines": problems, "rows": got,
                   "bits": snaps if args.bits else {}}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if problems:
        print(f"[warn] 账本里有 {len(problems)} 条读不出来的行：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
    if not got:
        print(f"（没有命中：{ws}/manuscripts/{MS.HANDOFFS_NAME}"
              + (f"，过滤器 id={args.id} to={args.to}" if (args.id or args.to) else "") + "）")
        return 0
    for rec in got:
        print(f"[{rec.get('id')}] {rec.get('sender')} → {rec.get('to')}"
              f"｜{rec.get('summary') or '（没有一句话）'}｜{rec.get('created_at') or ''}")
        if args.id:
            print(str(rec.get("body") or ""))
        if args.bits:
            print(_format_bits(snaps.get(str(rec.get("id") or ""), [])))
    return 0


if __name__ == "__main__":  # pragma: no cover - 脚本入口
    raise SystemExit(main())

"""把改前/改后两份差分读数并成一张表（题 5/5a 的核心交付）。

用法（工作目录 = 项目根）：
    python -B temp/render_doc_citation_diff_5a.py

退出码：0 = 每一格逐字相同且两侧原始报文逐字未变；1 = 有格子不同（必须停下来报）。

判定词表（粗粒度，见探针脚本头部的边界说明）：
    OK / SHAPE / NOT_FOUND / STALE / NON_DOC_BRANCH（+ 诊断行的 NOT_ACCEPTED_DOC）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def main() -> int:
    before = _load("out_5a_before.json")
    after = _load("out_5a_after.json")
    b_by = {r["label"]: r for r in before["records"]}
    a_by = {r["label"]: r for r in after["records"]}
    labels = [r["label"] for r in before["records"]]

    bad: list[str] = []
    print("## 判定表（四格：改前写 / 改前审 / 改后写 / 改后审）")
    print()
    print("| 输入 | 引用 | 改前·写入期 | 改前·审计期 | 改后·写入期 | 改后·审计期 | 四格同上 |")
    print("|---|---|---|---|---|---|---|")
    for label in labels:
        b, a = b_by[label], a_by[label]
        cells = [b["write_e2e_token"], b["audit_token"],
                 a["write_e2e_token"], a["audit_token"]]
        diagnostic = label.startswith("[诊断]")
        if diagnostic:
            # 诊断行**刻意**两侧不同（预存口径差：审计期多一条"目标稿件必须 accepted"），
            # 它要证的是"改前改后一字未变"，不是"两侧相同"。
            same = (cells[0] == cells[2]) and (cells[1] == cells[3])
            mark = "预存口径差（两侧本不同）" + ("、改前=改后" if same else "、改前≠改后")
        else:
            same = len(set(cells)) == 1
            mark = "是" if same else "否"
        if not same:
            bad.append(f"{label}: {cells}")
        raw = b["input"].replace("|", "\\|")
        print(f"| {label} | `{raw}` | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | "
              f"{mark} |")

    print()
    print("## 每一侧的原始报文 / 判据码：改前 vs 改后（逐字比对）")
    print()
    print("| 输入 | 侧 | 改前 | 改后 | 逐字相同 |")
    print("|---|---|---|---|---|")
    for label in labels:
        b, a = b_by[label], a_by[label]
        pairs = [
            ("写入期·三段单元 `_doc_citation_problem`", b["write_unit_msg"], a["write_unit_msg"]),
            ("写入期·端到端 `check_citations` 的 why", b["write_e2e_why"], a["write_e2e_why"]),
            ("审计期·判据码", b["audit_code"], a["audit_code"]),
            ("审计期·报文", b["audit_msg"], a["audit_msg"]),
        ]
        for side, old, new in pairs:
            same = old == new
            if not same:
                bad.append(f"{label} / {side} 的原始读数改了：{old!r} -> {new!r}")
            esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ") or "（空）"  # noqa: E731
            print(f"| {label} | {side} | {esc(old)} | {esc(new)} | {'是' if same else '否'} |")

    print()
    if bad:
        print("结论：有格子不同（停下报告，不许自己改其中一份）：")
        for x in bad:
            print(f"  - {x}")
        return 1
    print("结论：全部格逐字相同 —— 七个输入 x 四个读数格无一格变化，"
          "且两侧各自的原始报文/判据码逐字未变。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

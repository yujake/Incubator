#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""核对 `docs/ROLE-SPECS.md` 的结构完整性：A–H 八角色 + 主控 M，每节 8 个必备子节。

## 为什么这件事需要一道门，而不是"写文档时注意一下"

用户对正式版的要求之一是"为 A–H 八个角色各写详细规格说明书"，并逐字点名了小节：
职责 / 明确不负责 / 逐个工具的契约 / 状态机 / 预算与终止 / 三态与失败模式 / 不变式 / 接口。

一份 2000+ 行的规格最容易的坏法不是写错，而是写漏：新增一个角色（或重构某节）时
少写"明确不负责"或"不变式"，没有任何东西会变红 —— 文档不会报错，
而读者会以为"这一节大概没有那些内容"。
"没写"与"写了但没有"必须能区分，这是本项目三态纪律在文档上的同一条要求。

## 判据（机械、可复跑）

- 角色节：`^##\\s+([A-HMm])\\s*(——|--|·)?\\s*(.*)$` —— 恰好 9 个（A–H + M）。
- 子节：`^###\\s+<角色>\\.(\\d+)\\s+(.*)$` —— 每个角色节下必须能匹配到
  `REQUIRED` 里每一项的关键词（措辞允许出入，所以用关键词而不是精确标题）。
- 工具契约那一项额外要求：子节标题里必须能读出一个工具条数（实测数字），
  因为"逐个工具的契约"这句话如果没有数字，就无法与 `cli tools` 的普查对账。

## 退出码（三档，不许只有"没报错"）

- ``0`` —— 结构完整。
- ``1`` —— 查过了，有缺失（哪一节缺哪一项，逐条打印）。
- ``2`` —— 没查成（文档不存在 / 读不到 / 一个角色节都没匹配到）。
  `2` 绝不是 `0`：文档被改名或路径写错时，脚本不能"因为什么都没读到所以通过"。

用法：
    python tools/verify_role_specs.py
    python tools/verify_role_specs.py --json
    python tools/verify_role_specs.py --roles N,O,Q --doc docs/ROLE-SPECS-DRAFT-N-O-Q.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DOC_REL = Path("docs") / "ROLE-SPECS.md"

#: 用户逐字点名的 8 个必备子节 → 标题关键词（任一命中即算有）。
REQUIRED: dict[str, tuple[str, ...]] = {
    "职责": ("职责",),
    "明确不负责": ("不负责",),
    "工具契约": ("工具面", "工具契约"),
    "状态机": ("状态机", "状态迁移"),
    "预算与终止": ("预算", "终止"),
    "三态与失败模式": ("三态",),
    "不变式": ("不变式",),
    "接口": ("接口",),
}

#: `schema.ROLES` 的顺序，刻意写死在这里而不是 import：
#: 本脚本是文档结构的门，它应当在包 import 不进来时也能跑（那正是最需要它的时候）。
#: 合并进来的字母按给定顺序逐个占一个字符类，`A,H,M` 于是得到 `[AHM]` ——
#: 与原判据逐字相同。
EXPECTED_ROLES = ("A", "B", "C", "D", "E", "F", "G", "H", "M")

#: `--roles` 的默认值（`None` = 用 `EXPECTED_ROLES`）。
#: 默认行为一字不变：`^##\s+([A-HMm])…` 只认 A–H + M，正是本门登记时的判据。
DEFAULT_ROLES: tuple[str, ...] | None = None


def role_letters(roles: tuple[str, ...] | None = None) -> tuple[str, ...]:
    """把角色集合解析为单个大写字母序列。

    ── 为什么必须给本门一个"角色集合可传参"的入口（FC-27 外的真实缺口）──

    判据 `^##\\s+([A-HMm])` 把角色集合写死成 A–H + M。于是新增一个角色
    （本轮草稿里的 N/O/Q）并写进新文档之后，本门在那份文档上匹配不到任何角色节，
    报的是 `unknown`（"没查成"）—— 这是对的；但若那份草稿被改名成
    `docs/ROLE-SPECS.md`，门会拿旧的角色集合去查它，多出来的 N/O/Q 节
    被 `_ROLE_PAT` 直接忽略，于是门看不见它们：不报错 = 假通过。

    所以 `--roles` 让调用方把"这份文档应当有哪些角色节"说出来；不说时行为与原版相同。

    非法输入一律抛 `ValueError` 而不是静默回落到默认集合 ——
    后者会让 `--roles N;O;Q`（打错一个分隔符）变成一次"检查了别的东西"的假绿。
    """
    if roles is None:
        return tuple(EXPECTED_ROLES)
    if not isinstance(roles, (tuple, list)) or not roles:
        raise ValueError(f"roles 必须是非空序列，收到 {roles!r}")
    out: list[str] = []
    for r in roles:
        s = str(r).strip()
        if len(s) != 1 or not s.isalpha() or not s.isupper() or not s.isascii():
            raise ValueError(f"角色必须是单个大写字母（A–Z），收到 {r!r}")
        if s not in out:
            out.append(s)
    return tuple(out)


def _patterns(letters: tuple[str, ...]) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """按角色集合构造两个判据正则。`letters` 非空时与原 `[A-HMm]` 逐字等价。"""
    cls = "".join(letters)
    return (
        re.compile(rf"^##\s+([{cls}])\s*(?:——|--|·)?\s*(.*)$"),
        re.compile(rf"^###\s+([{cls}])\.(\d+)\s+(.*)$"),
    )


_ROLE_PAT, _SUB_PAT = _patterns(tuple(EXPECTED_ROLES))
#: 子节标题里的工具条数，例如 `工具面（20 个，实测）` / `工具面 —— 两层`（C 是两层，没有单一条数）
_COUNT_PAT = re.compile(r"(\d+)\s*个")


def project_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__).resolve()).resolve()
    for cand in (here, *here.parents):
        if (cand / DOC_REL).is_file():
            return cand
    return here.parents[1]


def check(doc: Path, *, roles: tuple[str, ...] | None = None) -> dict:
    """返回结构化结果。`verdict` ∈ ``ok`` / ``incomplete`` / ``unknown``。

    `roles=None` 时用 `EXPECTED_ROLES`（默认行为与原版相同）；给了就用它当判据。
    """
    try:
        letters = role_letters(roles)
    except ValueError as e:
        return {"verdict": "unknown", "reason": f"--roles 非法：{e}", "sections": []}
    role_pat, sub_pat = _patterns(letters)
    if not doc.is_file():
        return {
            "verdict": "unknown",
            "reason": f"规格文档不是一个可读文件：{doc}"
            + ("（是目录）" if doc.is_dir() else "（不存在）"),
            "sections": [],
        }
    try:
        lines = doc.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return {"verdict": "unknown", "reason": f"规格文档读不到：{doc}（{type(exc).__name__}: {exc}）",
                "sections": []}

    role_list: list[tuple[int, str, str]] = []
    for i, ln in enumerate(lines):
        m = role_pat.match(ln)
        if m:
            role_list.append((i, m.group(1), m.group(2).strip()))
    if not role_list:
        return {
            "verdict": "unknown",
            "reason": (
                f"在 {doc} 里一个角色节都没匹配到（判据 `^##\\s+([{''.join(letters)}])…`）。"
                "文档可能被改名/改格式了 —— 这属于『没查成』，不是『结构完整』"
            ),
            "sections": [],
        }

    sections: list[dict] = []
    for idx, (start, role, title) in enumerate(role_list):
        end = role_list[idx + 1][0] if idx + 1 < len(role_list) else len(lines)
        subs = [m.group(3).strip() for ln in lines[start:end]
                for m in [sub_pat.match(ln)] if m and m.group(1) == role]
        found: dict[str, str] = {}
        for key, kws in REQUIRED.items():
            hit = next((s for s in subs if any(k in s for k in kws)), None)
            if hit:
                found[key] = hit
        missing = [k for k in REQUIRED if k not in found]
        tool_counts = sorted({int(c) for s in subs for c in _COUNT_PAT.findall(s)})
        sections.append({
            "role": role, "title": title, "line": start + 1,
            "subsections": len(subs), "missing": missing,
            "found": found, "tool_counts_in_titles": tool_counts,
        })

    got_roles = [s["role"] for s in sections]
    problems: list[str] = []
    if got_roles != list(letters):
        problems.append(
            f"角色节顺序/集合与期望不符：期望 {list(letters)}，实际 {got_roles}"
        )
    for s in sections:
        if s["missing"]:
            problems.append(f"§{s['role']} 缺子节：{s['missing']}")
        # "逐个工具的契约" 这一项若连一个数字都读不出来，就无法与普查对账。
        if not s["tool_counts_in_titles"] and s["role"] != "M":
            problems.append(
                f"§{s['role']} 的工具面子节标题里读不出工具条数（『逐个工具的契约』无法与 "
                "`cli tools` 的普查对账）"
            )
    return {
        "verdict": "incomplete" if problems else "ok",
        "reason": "；".join(problems) if problems else
                  f"{len(sections)} 个角色节（{' '.join(letters)}）各自 {len(REQUIRED)} 个必备子节齐全",
        "sections": sections,
        "counts_by_role": {s["role"]: s["tool_counts_in_titles"] for s in sections},
        "roles": list(letters),
        "doc": str(doc),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="核对 docs/ROLE-SPECS.md 的结构完整性")
    ap.add_argument("--root", default=None, help="仓库根（默认自动探测）")
    ap.add_argument("--doc", default=None,
                    help=f"要核对的规格文档（仓库相对或绝对路径；默认 {DOC_REL.as_posix()}）")
    ap.add_argument("--roles", default=None,
                    help="期望的角色集合，逗号分隔（默认 A,B,C,D,E,F,G,H,M —— 不给时行为与原版一字不变）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args(list(argv) if argv is not None else None)

    try:
        roles = None if args.roles is None else tuple(r.strip() for r in args.roles.split(","))
        roles = role_letters(roles)
    except ValueError as e:
        print(f"[unknown] --roles 非法：{e}", file=sys.stderr)
        return 2
    doc = Path(args.doc) if args.doc else DOC_REL
    if not doc.is_absolute():
        root = Path(args.root).resolve() if args.root else project_root()
        doc = root / doc
    result = check(doc, roles=roles)
    code = {"ok": 0, "incomplete": 1, "unknown": 2}[result["verdict"]]

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[{result['verdict']}] {doc}")
        print(result["reason"])
        for s in result["sections"]:
            mark = "OK " if not s["missing"] else "MISS"
            print(f"  [{mark}] §{s['role']} {s['title'][:34]:34s} 行 {s['line']:5d} "
                  f"子节 {s['subsections']:2d}  工具条数 {s['tool_counts_in_titles']}")
            if s["missing"]:
                print(f"         缺：{s['missing']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

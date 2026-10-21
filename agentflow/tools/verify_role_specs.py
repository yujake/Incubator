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
EXPECTED_ROLES = ("A", "B", "C", "D", "E", "F", "G", "H", "V", "M")

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


def live_tool_counts(*, root: Path) -> tuple[dict[str, int] | None, str]:
    """真的装配一次注册表，返回 `({角色: 工具数}, "")`；取不到时返回 `(None, 原因)`。

    ## `H-8`：这道门此前从来没有做过它自己声称的那个对账

    实测（`draft/28` 的 `H-8`）：把副本里 `§D 工具面（37 个，实测）` 改成 `999 个`、
    `§H 工具面（22 个，实测）` 改成 `1 个`，本门照样 `[OK] … 工具条数 [37]`
    / `[OK] … 工具条数 [1]`、退出码 0。旧实现只检查"标题里能不能读出一个数字"，
    而 `docs/INDEX.md:16` 与 `DEVELOPMENT.md:1119` 逐字声称
    "文档每节标题里的工具条数必须等于真的跑一次 `python -m agentflow.cli tools` 得到的数字"。

    ## 三态（与 `axes-3` 同一条纪律）

    - 包 import 不进来 ⇒ `unknown`（返回 `(None, 原因)`）⇒ 调用方不许判 pass。
      这是刻意保留的：本脚本在"包烂到 import 不了"时仍然要能跑（那正是最需要它的时候），
      所以对账只在函数内部按需 import，不 import 顶层的 `agentflow`，
      失败时如实报"没查成"。
    - 角色数一致 ⇒ 逐角色比对标题里的数字。
    """
    try:
        sys.path.insert(0, str(root / "src"))
        import importlib
        import tempfile

        from agentflow.store import Store
        from agentflow.tools import ROLES, build_registry
    except Exception as exc:  # noqa: BLE001 - 任何 import 失败都是"没查成"
        return None, f"装配不了工具层（{type(exc).__name__}: {exc}）⇒ 对账没做"
    try:
        d = Path(tempfile.mkdtemp(prefix="role-specs-live-"))
        st = Store(d)
        st.init()
        built = build_registry(store=st, workspace_root=d, strict=True)
        counts = {r: len(built.registry.for_role(r)) for r in ROLES}
    except Exception as exc:  # noqa: BLE001 - 装配期抛异常同样是"没查成"
        return None, f"装配注册表失败（{type(exc).__name__}: {exc}）⇒ 对账没做"
    return counts, ""


def live_roles(*, root: Path) -> tuple[tuple[str, ...] | None, str]:
    """真的 import 一次包，返回 `(现场角色集合, 原因)`；取不到时 `(None, 原因)`。

    ## `R6-6`（工具侧）：这份对账此前只在 pytest 里做过

    门里那份 `EXPECTED_ROLES` 与现场角色名单（`tools.ROLES` + `schema.CONDUCTOR_ROLE`）
    之间原本没有任何导入期/跑门期的判据 —— `tests/test_role_specs_complete.py`
    里那条交叉断言只在跑 pytest 时红。于是"现场加了角色而门里的表没跟上"这件事
    在跑门的时候是看不见的：门会继续用一个已经不存在的角色集合判"结构完整"。
    这里把它搬进门本身（`check()` 拿到现场集合就当场比）。

    三态：import 不进来 ⇒ `(None, 原因)`，调用方按 `unknown` 处理 ——
    绝不判 pass（"没查成"不是"结构完整"）。
    """
    try:
        sys.path.insert(0, str(root / "src"))
        from agentflow import schema as S
        from agentflow.tools import ROLES
    except Exception as exc:  # noqa: BLE001 - 任何 import 失败都是"没查成"
        return None, f"装配不了角色名单（{type(exc).__name__}: {exc}）⇒ 角色集合对账没做"
    return tuple(ROLES) + (S.CONDUCTOR_ROLE,), ""


def check(doc: Path, *, roles: tuple[str, ...] | None = None,
          live_counts: dict[str, int] | None = None,
          live_reason: str = "",
          live_role_list: tuple[str, ...] | None = None) -> dict:
    """返回结构化结果。`verdict` ∈ ``ok`` / ``incomplete`` / ``unknown``。

    `roles=None` 时用 `EXPECTED_ROLES`（默认行为与原版相同）；给了就用它当判据。

    `live_counts`（`H-8`）是"真的装配一次注册表"得到的 `{角色: 工具数}`。
    不给时不做那一步对账，并在 `verdict` 上体现为 `unknown`（如果调用方要求对账）——
    见 `main` 的 `--no-live`。

    `live_role_list`（`R6-6` 工具侧）是现场角色集合（`tools.ROLES` +
    `schema.CONDUCTOR_ROLE`）。给了就与门里那份 `EXPECTED_ROLES` 当场比 ——
    不一致 ⇒ `incomplete`（不是 `unknown`：这是"查过了、不一致"，
    与"没查成"是两件事）。不给则不判（`check()` 的离线调用形态不变）。
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
    # `R6-6`（工具侧）：门里那份角色表必须与现场集合一致。
    # 为什么放在这里而不是只放测试里：加角色/改角色时，"门还绿着"与"仓库已经变了"
    # 可以同时成立，而门是唯一一个每次都会跑的东西（测试会被挑着跑）。
    # 用集合比而不是顺序比：顺序问题由上面那条 `got_roles != list(letters)` 负责，
    # 这里问的是"门的角色表与现场是不是同一批角色"。
    if live_role_list is not None and set(EXPECTED_ROLES) != set(live_role_list):
        problems.append(
            "`EXPECTED_ROLES` 与现场角色集合不一致：门里写的是 "
            f"{list(EXPECTED_ROLES)}，现场（`tools.ROLES` + `schema.CONDUCTOR_ROLE`）是 "
            f"{list(live_role_list)}。差集：门里多 "
            f"{sorted(set(EXPECTED_ROLES) - set(live_role_list))}、门里少 "
            f"{sorted(set(live_role_list) - set(EXPECTED_ROLES))}。"
            "现场加了角色而这张表没跟上时，这道门会继续拿一个已经不存在的角色集合"
            "判『结构完整』（`R6-6`）—— 请同时更新 `EXPECTED_ROLES` 与文档的角色节。"
        )
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
        # ---- `H-8`：与真的装配一次得到的数字对账（这是本门声称做过的事）
        #
        # `R6-3`（第一次重审实测）：对账必须是那一格的对账，不是"出现过就算"。
        # 旧判据是 `want not in got`，而 `got` 取的是该角色所有子节标题里的数字
        # ⇒ 只要别处任意一个 §X.n 标题里出现过 `22 个`，§H.4 写成 `999 个` 也照样 `ok`，
        # 而且会打印"逐角色工具条数与现场装配一致"。那是判据真空 + 声明撒谎叠在一起。
        # 现在改成：锚定 `REQUIRED["工具契约"]` 命中的那个子节标题，
        # 只读它里面的条数；标题里若有多个数字，实测值必须是其中之一。
        if live_counts is not None and s["role"] in live_counts:
            want = int(live_counts[s["role"]])
            anchor = s["found"].get("工具契约")
            if anchor is None:
                continue  # 缺子节由上面那条 `missing` 报
            anchored = sorted({int(c) for c in _COUNT_PAT.findall(anchor)})
            if not anchored:
                problems.append(
                    f"§{s['role']} 的工具面子节标题（{anchor!r}）里读不出工具条数 ⇒ "
                    "『逐个工具的契约』无法与现场装配对账（这一格没有可判的对象）"
                )
            elif want not in anchored:
                problems.append(
                    f"§{s['role']} 的**工具面子节**（{anchor!r}）里的条数 {anchored} "
                    f"与实测不符：真的装配一次注册表得到 {want} 个"
                    f"（`build_registry(...).for_role({s['role']!r})`）。"
                    "文档里那句『（N 个，实测）』必须等于现场实测值 —— "
                    "别处的标题里出现同一个数字**不算**（`R6-3` 的修法）"
                )
    return {
        "verdict": "incomplete" if problems else "ok",
        "reason": "；".join(problems) if problems else
                  f"{len(sections)} 个角色节（{' '.join(letters)}）各自 {len(REQUIRED)} 个必备子节齐全"
                  + ("；且逐角色工具条数与现场装配一致" if live_counts is not None else
                     "（未与现场装配对账）"),
        "sections": sections,
        "counts_by_role": {s["role"]: s["tool_counts_in_titles"] for s in sections},
        "live_counts": dict(live_counts) if live_counts is not None else None,
        "live_reason": live_reason,
        "live_role_list": list(live_role_list) if live_role_list is not None else None,
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
    ap.add_argument(
        "--no-live", action="store_true",
        help=("跳过『与现场装配对账』这一步（`H-8`）。默认做：包 import 不进来时"
              "那一项按 `unknown` 处理，不是按『结构完整』。"
              "注意（`R6-5`）：跳过了对账就**没有**结论 —— 本门以 `unknown`（退出码 2）"
              "结束，绝不报 `ok`。要一个只查结构、不判门的读数，请看 `--json` 的 sections 段。"),
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    try:
        roles = None if args.roles is None else tuple(r.strip() for r in args.roles.split(","))
        roles = role_letters(roles)
    except ValueError as e:
        print(f"[unknown] --roles 非法：{e}", file=sys.stderr)
        return 2
    root = Path(args.root).resolve() if args.root else project_root()
    doc = Path(args.doc) if args.doc else DOC_REL
    if not doc.is_absolute():
        doc = root / doc
    live: dict[str, int] | None = None
    live_reason = ""
    live_role_list: tuple[str, ...] | None = None
    if not args.no_live:
        live, live_reason = live_tool_counts(root=root)
        # `R6-6`：现场角色集合只在"判据就是门里那份默认角色表"时对账。
        # `--roles N,O,Q` 问的是另一份草稿的另一套角色，与门里那张表无关，
        # 拿它去比对默认表只会造一条假红。
        if tuple(roles) == tuple(EXPECTED_ROLES):
            live_role_list, role_reason = live_roles(root=root)
            if live_role_list is None:
                # 角色集合都没拿到 ⇒ 与"注册表装配不了"同一档：不许判 ok。
                live = None
                live_reason = f"{live_reason}；{role_reason}".strip("；")
    result = check(doc, roles=roles, live_counts=live, live_reason=live_reason,
                   live_role_list=live_role_list)
    # `H-8`：要做的对账没做成 ⇒ 不许报 ok。三态纪律：没查成不是通过。
    if not args.no_live and live is None:
        result["verdict"] = "unknown"
        result["reason"] = f"{live_reason}（对账没做 ⇒ 本门不给结论，更不许读成『结构完整』）"
    # `R6-5`：`--no-live` 是"跳过对账"的调试开关 —— 跳过了就没有结论。
    # 旧版让它照旧报 `[ok] …（未与现场装配对账）` 并以 0 退出，于是一个开关
    # 就能把 H-8 修好的那一步对账整个摘掉而门还是绿的（协议 §2 的
    # "门可被 `--skip` 绕过"形态）。这里把它降级成 `unknown`（退出码 2）：
    # 结构检查的明细仍然照常打印（调试用途不丢），但"结构完整"这个结论不给。
    #
    # 只在它当时是 `ok` 时降级：`incomplete`（查过了、结构有问题）比 `unknown`
    # 更强，把它降成 2 等于拿"没查成"盖掉一条已经查实的发现 —— 那是把判据
    # 往弱的方向改。此时只往理由尾巴上补一句"对账那一步没做"。
    if args.no_live:
        skip_note = (
            "（另：本次跳过了『与现场装配对账』这一步（`--no-live`）—— "
            "『结构完整』只有在真的与现场装配对过账之后才成立（`R6-5`），"
            "所以本次也没有『结构完整』这个结论）"
        )
        if result["verdict"] == "ok":
            result["verdict"] = "unknown"
            result["reason"] = (
                "跳过了『与现场装配对账』这一步（`--no-live`）⇒ 本门不给结论："
                "『结构完整』只有在真的与现场装配对过账之后才成立（`R6-5`）。"
                "下面每个角色节的明细仍然照常给出，可以当作调试读数用 —— "
                "但它不是一次门的结论，更不许被引用成『结构完整』。"
                f"（结构侧本次读数：{result['reason']}）"
            )
        else:
            result["reason"] = f"{result['reason']}{skip_note}"
    code = {"ok": 0, "incomplete": 1, "unknown": 2}[result["verdict"]]

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[{result['verdict']}] {doc}")
        print(result["reason"])
        if live is not None:
            print(f"  现场装配（对账面）：{live}")
        for s in result["sections"]:
            mark = "OK " if not s["missing"] else "MISS"
            live_n = "" if live is None or s["role"] not in live else f"  现场 {live[s['role']]}"
            print(f"  [{mark}] §{s['role']} {s['title'][:34]:34s} 行 {s['line']:5d} "
                  f"子节 {s['subsections']:2d}  工具条数 {s['tool_counts_in_titles']}{live_n}")
            if s["missing"]:
                print(f"         缺：{s['missing']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

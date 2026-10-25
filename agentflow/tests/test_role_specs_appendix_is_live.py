# -*- coding: utf-8 -*-
"""`docs/ROLE-SPECS-APPENDIX.md` 的逐角色 `.4` 节必须与实时装配同一套读数。

## 这个文件修的是什么

`docs/ROLE-SPECS.md` 有 `tests/test_role_specs_complete.py` 逐行对账（工具名集合、
`side_effect` / 审批 / `roles` 三列、逐角色条数）。附录这边此前一条判据都没有：
它写着 `[附录·实测]`、每一节都标着自己的条数、`side_effect` 分布与逐件清单，而这些数字
唯一的守卫是"下次有人记得重跑"。

代价已经出现过两次：2026-10-21 与 2026-10-25 各重算一遍，2026-10-27 又落后了
（`clock.periodic_start/periodic_stop/timer_purpose/wait_any` 四件进册后，
附录还停在 107 / 104 口径，A.4 还写 45 件而现场是 49）。过期的实测比没有实测更坏：
读者会把它当成当前值，而它连"我过期了"都不说。

所以本节自 2026-10-27 起改成"现读 + 一条只读判据"：每一节的五格（总数 / `side_effect` /
`external` / 需审批 / 逐件清单）都必须等于 `build_registry(...).for_role(role)` 的现算值，
标题里的件数也必须等于它。判据只读文档与注册表，不改任何东西。

## 三态

- 文档读不到 / 一个角色节都没匹配到 ⇒ 红（"没查成"绝不等于"对上了"）；
- 节在、但某一格解析不出 ⇒ 红（判据失去对象，不是"没问题"）；
- 值与现算不一致 ⇒ 红，报出"哪一节哪一格：文档写 X，实测 Y"。

## 为什么连"逐件清单"也判

只判总数会让"总数对了、清单里少了三件"静默常驻；而清单正是读者查"这个角色拿不拿得到
某件工具"的唯一落点。所以：列了名字的模块组，名字集合必须与现读逐一相等；没列名字的
大组（>9 件）只判条数 —— 那是刻意的：附录是实测快照，逐件契约在正文 §R0。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "ROLE-SPECS-APPENDIX.md"

#: 附录里必须有 `.4` 节的十一个角色（A–H + V + L + M）。少一节就是"漏写"，不是"这个角色没有工具面"。
EXPECTED_ROLES = ("A", "B", "C", "D", "E", "F", "G", "H", "V", "L", "M")

#: 每节第一行那句"现读于 …"的形态（防有人把节改回手抄而不标日期与版本）。
_READ_ON = re.compile(r"\*\*现读于 (\d{4}-\d{2}-\d{2})（p(\d+)，`AGENTFLOW_LEAN_ENABLED=1`）\*\*")

#: 模块组：`` `clock.*` 9（`now` `timer_start` …） `` 或 `` `conductor.*` 19 ``。
_GROUP = re.compile(r"`([a-z]+)\.\*` (\d+)(?:（((?:`[a-z_0-9]+`[ ]?)+)）)?")


def _appendix() -> str:
    text = DOC.read_text(encoding="utf-8")
    assert text.strip(), f"{DOC} 是空的 —— 判据失去对象"
    return text


def _section(text: str, role: str) -> str:
    head = re.search(r"^## %s\.4 .*$" % role, text, re.M)
    assert head, f"附录里找不到 §{role}.4 节（这条判据失去对象，不是'该节没问题'）"
    body = text[head.start():]
    end = body.find("\n---\n")
    assert end > 0, f"§{role}.4 节没有以 `---` 收尾（格式坏了）"
    return body[:end]


def _cell(section: str, label: str) -> str:
    m = re.search(r"^\| `?%s`? \| (.+?) \|$" % re.escape(label), section, re.M)
    assert m, f"这一节的表里没有 `{label}` 那一格"
    return m.group(1)


def _pairs(cell: str) -> dict[str, int]:
    """`read 23 / write_local 26 / none 0` → {'read':23,...}（只读第一个反引号跨度，零值去掉）。"""
    span = re.search(r"`([^`]+)`", cell)
    assert span, f"那一格没有反引号包住的读数：{cell!r}"
    out: dict[str, int] = {}
    for part in span.group(1).split("/"):
        key, _, num = part.strip().partition(" ")
        if int(num):
            out[key] = int(num)
    return out


def _nonzero(counter: dict[str, int]) -> dict[str, int]:
    """现算那一侧也去掉零值 —— 两边比的是"哪几档非零、各几件"。"""
    return {str(k): int(v) for k, v in counter.items() if int(v)}


def _groups(section: str, marker: str) -> tuple[int, dict[str, set[str]]]:
    """从"逐件清单…：…" 或 "X 拿不到：另 N 件 —— …" 那一行读出 (合计, 模块 → 列出的名字)。"""
    line = re.search(r"^\*\*%s.*$" % re.escape(marker), section, re.M)
    assert line, f"这一节没有 `{marker}` 那一行"
    total = 0
    listed: dict[str, set[str]] = {}
    for mod, count, names in _GROUP.findall(line.group(0)):
        total += int(count)
        got = {n for n in re.findall(r"`([a-z_0-9]+)`", names)}
        if got:
            listed[mod] = got
    return total, listed


@pytest.fixture(scope="module")
def live():
    """现算：角色 → (side_effect 分布, external 分布, 需审批数, 逐件名)。"""
    sys.path.insert(0, str(REPO / "src"))
    import tempfile  # noqa: PLC0415

    from agentflow import store as _store  # noqa: PLC0415
    from agentflow.tools import ROLES, build_registry  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="appendix_live_") as td:
        st = _store.Store(Path(td))
        st.init()
        reg = build_registry(store=st, workspace_root=Path(td), roles=tuple(ROLES)).registry
        by_role: dict[str, dict] = {}
        for role in EXPECTED_ROLES:
            specs = [reg.get(n) for n in sorted(x.name for x in reg.for_role(role))]
            se: dict[str, int] = {}
            ext: dict[str, int] = {}
            for s in specs:
                se[s.side_effect] = se.get(s.side_effect, 0) + 1
                ext[str(s.external)] = ext.get(str(s.external), 0) + 1
            by_role[role] = {
                "total": len(specs),
                "se": se,
                "ext": ext,
                "appr": sum(1 for s in specs if s.needs_approval),
                "names": {s.name for s in specs},
            }
        all_names = set(reg.names())
    return by_role, all_names


def test_every_role_section_is_marked_as_a_live_reading(live):
    """十一节都在，且每节第一行都标着"现读于 <日期>（p<版本>，Lean 开）"。

    为什么单列一条：附录最容易的坏法不是数字错，而是悄悄退回手抄 —— 那之后
    它就是一段没有出处的散文，而后来的人照样会引用它。
    """
    text = _appendix()
    missing, unmarked = [], []
    for role in EXPECTED_ROLES:
        try:
            section = _section(text, role)
        except AssertionError:
            missing.append(role)
            continue
        if not _READ_ON.search(section):
            unmarked.append(role)
    assert not missing, f"附录缺这些角色的 `.4` 节：{missing}"
    assert not unmarked, f"这些角色的 `.4` 节没有标'现读于 <日期>（p<版本>…）'：{unmarked}"


def test_totals_in_the_headings_and_tables_match_the_registry(live):
    """标题件数、表里的总数 / side_effect / external / 需审批 四格 == 现算值。"""
    by_role, _ = live
    text = _appendix()
    bad: list[str] = []
    for role in EXPECTED_ROLES:
        section = _section(text, role)
        want = by_role[role]
        head_n = re.search(r"^## %s\.4 .*（(\d+) 件" % role, section, re.M)
        if not head_n:
            bad.append(f"§{role}.4 的标题里读不出件数")
        elif int(head_n.group(1)) != want["total"]:
            bad.append(f"§{role}.4 标题写 {head_n.group(1)} 件，实测 {want['total']}")
        if int(re.search(r"\d+", _cell(section, "总数")).group(0)) != want["total"]:
            bad.append(f"§{role}.4 表里总数不是 {want['total']}")
        for label, key in (("side_effect", "se"), ("external", "ext")):
            got = _pairs(_cell(section, label))
            if got != _nonzero(want[key]):
                bad.append(f"§{role}.4 `{label}` 写 {got}，实测 {_nonzero(want[key])}")
        if int(re.search(r"\d+", _cell(section, "需审批")).group(0)) != want["appr"]:
            bad.append(f"§{role}.4 需审批写 {_cell(section, '需审批')!r}，实测 {want['appr']}")
    assert not bad, "\n".join(bad)


def test_the_per_tool_lists_add_up_and_name_the_right_tools(live):
    """逐件清单：模块分组合计 == 总数；列了名字的组，名字集合必须与现读逐一相等。"""
    by_role, _ = live
    text = _appendix()
    bad: list[str] = []
    for role in EXPECTED_ROLES:
        section = _section(text, role)
        want = by_role[role]
        total, listed = _groups(section, "逐件清单")
        if total != want["total"]:
            bad.append(f"§{role}.4 逐件清单分组合计 {total}，实测 {want['total']}")
        for mod, names in listed.items():
            live_names = {n.split(".", 1)[1] for n in want["names"] if n.startswith(mod + ".")}
            if names != live_names:
                bad.append(
                    f"§{role}.4 的 `{mod}.*` 清单少了 {sorted(live_names - names)}"
                    f"／多了 {sorted(names - live_names)}")
    assert not bad, "\n".join(bad)


def test_the_missing_lists_carry_the_right_counts(live):
    """从"X 拿不到：另 N 件"那一行读：N == len(全表) − len(该角色面)，模块分组合计同 N。"""
    by_role, all_names = live
    text = _appendix()
    bad: list[str] = []
    for role in EXPECTED_ROLES:
        section = _section(text, role)
        want = len(all_names - by_role[role]["names"])
        line = re.search(r"^\*\*%s 拿不到\*\*：另 (\d+) 件" % role, section, re.M)
        if not line:
            bad.append(f"§{role}.4 没有'拿不到：另 N 件'那一行")
            continue
        if int(line.group(1)) != want:
            bad.append(f"§{role}.4 写拿不到 {line.group(1)} 件，实测 {want}")
        total, _ = _groups(section, "%s 拿不到" % role)
        if total != want:
            bad.append(f"§{role}.4 拿不到的模块分组合计 {total}，实测 {want}")
    assert not bad, "\n".join(bad)


def test_a_one_off_number_is_caught(live):
    """负控：把标题里的件数改大 1 ⇒ 上面那条判据必然红（判据不是橡皮图章）。"""
    text = _appendix()
    section = _section(text, "A")
    n = int(re.search(r"^## A\.4 .*（(\d+) 件", section, re.M).group(1))
    injected = text.replace(
        "## A.4 [附录·实测] 工具面明细（%d 件）" % n,
        "## A.4 [附录·实测] 工具面明细（%d 件）" % (n + 1), 1)
    assert injected != text, "负控没注入进去 —— 那说明标题的形态已经变了（判据随之失效）"
    with pytest.raises(AssertionError):
        # 复用正控那一支的同一段逻辑：把"标题件数 == 现算"这一格单独跑在注入文本上。
        by_role, _ = live
        sec = _section(injected, "A")
        got = int(re.search(r"^## A\.4 .*（(\d+) 件", sec, re.M).group(1))
        assert got == by_role["A"]["total"], f"标题写 {got}，实测 {by_role['A']['total']}"


# ============================================================ R0.1 / R0.3 / S3
# 这三处是同一个实测面的另外三块：R0.1 是 handler 形态与两套口径，R0.3 是拿 INVENTORY.md
# 对账的右栏，S3 第 1 行是 `cli tools` 的原样输出。它们此前都停在 107 / 104 口径
# （2026-10-25 的读数），而 2026-10-27 那四件 `clock.*` 进册之后没有一个字被改过。
# 判据把它们一并拉进"等于现算"，理由是同一个：附录是实测，不是散文。


@pytest.fixture(scope="module")
def live_all():
    """现算全表：handler 形态、两根分布、需审批，以及"砍掉三件 formal.*"之后的 Lean 关口径。"""
    import functools  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    sys.path.insert(0, str(REPO / "src"))
    from agentflow import store as _store  # noqa: PLC0415
    from agentflow.tools import ROLES, build_registry  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="appendix_all_") as td:
        st = _store.Store(Path(td))
        st.init()
        reg = build_registry(store=st, workspace_root=td, roles=tuple(ROLES)).registry
        specs = [reg.get(n) for n in sorted(reg.names())]
    forms: dict[str, int] = {}
    for s in specs:
        h = s.handler
        if isinstance(h, functools.partial):
            key = "partial"
        elif getattr(h, "__name__", "") == "<lambda>":
            key = "lambda"
        elif getattr(h, "__closure__", None):
            key = "closure"
        else:
            key = "function"
        forms[key] = forms.get(key, 0) + 1

    def _counts(items):
        se: dict[str, int] = {}
        ext: dict[str, int] = {}
        for s in items:
            se[s.side_effect] = se.get(s.side_effect, 0) + 1
            ext[str(s.external)] = ext.get(str(s.external), 0) + 1
        return se, ext, sum(1 for s in items if s.needs_approval)

    se_on, ext_on, appr_on = _counts(specs)
    # Lean 关着时唯一少的就是 `formal_tools` 那三件（`leanscope` 决定装不装那个模块）。
    lean_off = [s for s in specs if not s.name.startswith("formal.")]
    se_off, ext_off, appr_off = _counts(lean_off)
    # 只读角色面里的写工具（`cli tools` 的"只读角色写工具泄漏"那一行数的就是它们）。
    leak_counts = {
        r: sum(1 for x in reg.for_role(r) if reg.get(x.name).side_effect == "write_local")
        for r in ("C", "H", "V")
    }
    return {
        "total": len(specs),
        "forms": forms,
        "se": se_on,
        "ext": ext_on,
        "appr": appr_on,
        "off_total": len(lean_off),
        "off_se": se_off,
        "off_ext": ext_off,
        "off_appr": appr_off,
        "names": {s.name for s in specs},
        "by_role": {r: len(reg.for_role(r)) for r in EXPECTED_ROLES},
        "leak_counts": leak_counts,
    }


def _r01(text: str) -> str:
    head = re.search(r"^## R0\.1 .*$", text, re.M)
    assert head, "附录里找不到 §R0.1（判据失去对象，不是'那节没问题'）"
    body = text[head.end():]
    end = body.find("\n---\n")
    assert end > 0, "§R0.1 没有以 `---` 收尾"
    return body[:end]


def _r03(text: str) -> str:
    head = re.search(r"^## R0\.3 .*$", text, re.M)
    assert head, "附录里找不到 §R0.3"
    body = text[head.end():]
    end = body.find("\n---\n")
    assert end > 0, "§R0.3 没有以 `---` 收尾"
    return body[:end]


def _s3_row(text: str) -> str:
    row = re.search(r"^\| 1 \| `python -m agentflow\.cli tools` \| (.*) \| 0 \|$", text, re.M)
    assert row, "§S3 里找不到 #1 那一行（`cli tools` 的原样输出）"
    return row.group(1)


def _table_row(section: str, label: str) -> list[str]:
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] == label:
            return cells
    raise AssertionError(f"表里没有 `{label}` 那一行")


def _pair_text(cell: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, num in re.findall(r"(read|write_local|none|egress|exec) (\d+)", cell):
        if int(num):
            out[key] = int(num)
    return out


def test_r01_handler_forms_and_the_two_gauge_row_match_the_registry(live_all):
    """§R0.1：handler 形态三个数 + 共 N，以及"B 口径 = 111（Lean 关 108）"那一行。"""
    text = _appendix()
    sec = _r01(text)
    m = re.search(r"`functools\.partial` \*\*(\d+)\*\* / `lambda` \*\*(\d+)\*\* / 具名闭包 \*\*(\d+)\*\*（共 (\d+)）", sec)
    assert m, "§R0.1 的 handler 形态那一句解析不出（判据失去对象）"
    partial, lam, closure, total = (int(x) for x in m.groups())
    want = live_all
    assert partial == want["forms"].get("partial", 0), f"partial 写 {partial}，实测 {want['forms'].get('partial', 0)}"
    assert lam == want["forms"].get("lambda", 0), f"lambda 写 {lam}，实测 {want['forms'].get('lambda', 0)}"
    assert closure == want["forms"].get("closure", 0), f"具名闭包写 {closure}，实测 {want['forms'].get('closure', 0)}"
    assert total == want["total"], f"共 {total}，实测 {want['total']}"
    cells = _table_row(sec, "B 口径（含 store 的完整装配）")
    assert len(cells) >= 3, f"§R0.1 的 B 口径那一行只有 {len(cells)} 格"
    n = re.search(r"\*\*(\d+)\*\*（Lean 关着时 (\d+)）", cells[2])
    assert n, "§R0.1 的 B 口径那一格解析不出"
    assert int(n.group(1)) == want["total"], f"B 口径写 {n.group(1)}，实测 {want['total']}"
    assert int(n.group(2)) == want["off_total"], f"Lean 关写 {n.group(2)}，实测 {want['off_total']}"


def test_r03_right_column_matches_the_registry(live_all):
    """§R0.3：对 `INVENTORY.md` 那张表的右栏五格（总数 / 逐角色 / 两根分布 / 需审批 / 泄漏）。"""
    text = _appendix()
    sec = _r03(text)
    want = live_all
    bad: list[str] = []

    row = _table_row(sec, "工具总数")
    n = re.search(r"\*\*(\d+)\*\*（.*?Lean 关着时 (\d+)）", row[2])
    if not n:
        bad.append("§R0.3 工具总数那一格解析不出")
    else:
        if int(n.group(1)) != want["total"]:
            bad.append(f"§R0.3 工具总数写 {n.group(1)}，实测 {want['total']}")
        if int(n.group(2)) != want["off_total"]:
            bad.append(f"§R0.3 Lean 关写 {n.group(2)}，实测 {want['off_total']}")

    row = _table_row(sec, "各角色工具数")
    got = {r: int(v) for r, v in re.findall(r"([A-Z])(\d+)", row[2])}
    if got != want["by_role"]:
        bad.append(f"§R0.3 各角色工具数写 {got}，实测 {want['by_role']}")

    row = _table_row(sec, "`side_effect` 分布")
    # 那一格里有四个"读数跨度"（还有 `none` 这类词本身也被反引号包着，所以要按键名挑）：
    # 本口径 side_effect / 本口径 external / Lean 关的 side_effect / Lean 关的 external。
    span = r"`((?:read|write_local|none|egress|exec) \d+(?: / (?:read|write_local|none|egress|exec) \d+)*)`"
    found = re.findall(span, row[2])
    se_spans = [s for s in found if s.startswith("read ")]
    ext_spans = [s for s in found if s.startswith("none ")]
    if len(se_spans) < 2 or len(ext_spans) < 2:
        bad.append(f"§R0.3 side_effect 那一格解析出 se={se_spans} ext={ext_spans}（应有各两档）")
    else:
        if _pair_text(se_spans[0]) != want["se"]:
            bad.append(f"§R0.3 side_effect 写 {_pair_text(se_spans[0])}，实测 {want['se']}")
        if _pair_text(se_spans[1]) != want["off_se"]:
            bad.append(f"§R0.3 Lean 关的 side_effect 写 {_pair_text(se_spans[1])}，实测 {want['off_se']}")
        ext_want = {k: want["ext"][k] for k in ("none", "egress", "exec") if want["ext"].get(k)}
        if _pair_text(ext_spans[0]) != ext_want:
            bad.append(f"§R0.3 external 写 {_pair_text(ext_spans[0])}，实测 {ext_want}")
        off_ext_want = {k: want["off_ext"][k] for k in ("none", "egress", "exec") if want["off_ext"].get(k)}
        if _pair_text(ext_spans[1]) != off_ext_want:
            bad.append(f"§R0.3 Lean 关的 external 写 {_pair_text(ext_spans[1])}，实测 {off_ext_want}")

    row = _table_row(sec, "需审批")
    n = re.search(r"\*\*(\d+) / (\d+)\*\*", row[2])
    if not n:
        bad.append("§R0.3 需审批那一格解析不出")
    elif (int(n.group(1)), int(n.group(2))) != (want["appr"], want["total"]):
        bad.append(f"§R0.3 需审批写 {n.group(1)} / {n.group(2)}，实测 {want['appr']} / {want['total']}")

    row = _table_row(sec, "只读角色泄漏")
    leaks = {r: int(v) for r, v in re.findall(r"`([A-Z])` (\d+) 件", row[2])}
    live_leaks = {r: v for r, v in want["leak_counts"].items() if v}
    if leaks != live_leaks:
        bad.append(f"§R0.3 只读泄漏写 {leaks}，实测 {live_leaks}")
    total_leak = re.search(r"\*\*(\d+) 件\*\*", row[2])
    if not total_leak or int(total_leak.group(1)) != sum(live_leaks.values()):
        bad.append(f"§R0.3 泄漏合计写 {total_leak.group(1) if total_leak else None}，"
                   f"实测 {sum(live_leaks.values())}")
    assert not bad, "\n".join(bad)


def test_s3_cli_tools_row_is_the_live_output(live_all, live):
    """§S3 第 1 行：`工具总数：111`、逐角色字典、三张泄漏清单的长度，全等于现算。"""
    text = _appendix()
    row = _s3_row(text)
    want = live_all
    bad: list[str] = []
    m = re.search(r"工具总数：(\d+)（已装模块 \d+", row)
    if not m:
        bad.append("§S3 #1 的'工具总数：N（已装模块 M'解析不出")
    elif int(m.group(1)) != want["total"]:
        bad.append(f"§S3 #1 工具总数写 {m.group(1)}，实测 {want['total']}")
    roles = {r: int(v) for r, v in re.findall(r"'([A-Z])': (\d+)", row)}
    if roles != want["by_role"]:
        bad.append(f"§S3 #1 各角色工具数写 {roles}，实测 {want['by_role']}")
    for role, count in want["leak_counts"].items():
        m = re.search(r"'%s': \[(.*?)\]" % role, row)
        if not m:
            bad.append(f"§S3 #1 泄漏清单里没有 `{role}`")
            continue
        got = len(re.findall(r"'[a-z_]+\.[a-z_]+'", m.group(1)))
        if got != count:
            bad.append(f"§S3 #1 `{role}` 的泄漏清单 {got} 件，实测 {count}")
    for stale in ("工具总数：107", "工具总数：104", "八件"):
        if stale in row:
            bad.append(f"§S3 #1 里还留着过期的 `{stale}`")
    assert not bad, "\n".join(bad)


# ============================================================ A.10–M.10 / M.4.2 / M.4.3 / M.8 / S1 / S2
# 这一组是"剩下那几节"的落点：能现读的（自检入口、REFUSAL_REASONS、rebuild 覆盖、
# 零测试工具、既有问题里能重跑的那几行）逐格对账；读不出的（要真机复现 / 要人读散文）
# 只断言它们标了留痕与日期——那是"我知道它过期、我不拿它当当前值"的机器可查形态。


def _h2(text: str, head: str) -> str:
    """取一个 `## <head>` 节（到下一个 `## ` 或 `---` 为止）。"""
    m = re.search(r"^## %s.*$" % re.escape(head), text, re.M)
    assert m, f"附录里找不到 §{head}"
    rest = text[m.end():]
    nxt = re.search(r"^(## |---$)", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _run_module(mod: str) -> tuple[int, list[str]]:
    """子进程跑一个自检入口（钉 Lean 关，与 §A.10–M.10 的口径同一档）。"""
    import subprocess  # noqa: PLC0415

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src")
    env["AGENTFLOW_LEAN_ENABLED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, "-m", f"agentflow.{mod}"], cwd=str(REPO),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300, env=env)
    out = ((p.stdout or "") + (p.stderr or "")).splitlines()
    return p.returncode, out


def test_a10_selfcheck_entries_match_a_live_run():
    """§A.10–M.10：十二个入口逐个重跑，比"尾部逐字 / 退出码 / 行数"三列。"""
    text = _appendix()
    sec = _h2(text, "A.10–M.10")
    rows: dict[str, list[str]] = {}
    for line in sec.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[0].startswith("`") and cells[0].endswith("`"):
            rows[cells[0].strip("`")] = cells
    assert rows, "§A.10–M.10 的入口表解析不出（判据失去对象）"
    bad: list[str] = []
    for mod in ("agent_a", "agent_b", "agent_c", "agent_d", "agent_e", "agent_f",
                "agent_g", "agent_h", "agent_v", "pipeline", "llm"):
        if mod not in rows:
            bad.append(f"§A.10–M.10 缺 {mod} 那一行")
            continue
        cells = rows[mod]
        code, out = _run_module(mod)
        live = "\n".join(out)
        if code != int(re.search(r"\d+", cells[2]).group(0)):
            bad.append(f"§A.10 {mod} 退出码写 {cells[2]}，实测 {code}")
        n = re.search(r"\d+", cells[3])
        if not n or int(n.group(0)) != len(out):
            bad.append(f"§A.10 {mod} 行数写 {cells[3]}，实测 {len(out)} 行")
        for seg in re.findall(r"`([^`]+)`", cells[1]):
            if seg not in live:
                bad.append(f"§A.10 {mod} 的读数 `{seg}` 不在实跑输出里")
    assert "conductor" in rows, "§A.10–M.10 的 `conductor`（无入口）那一行不见了"
    assert not bad, "\n".join(bad)


def test_m42_refusal_reasons_match_the_schema(live):
    """§M.4.2：`REFUSAL_REASONS` 的条数与词表。"""
    from agentflow import schema as _schema  # noqa: PLC0415

    sec = _h2(_appendix(), "M.4.2")
    reasons = sorted(_schema.REFUSAL_REASONS)
    m = re.search(r"`REFUSAL_REASONS`（`schema\.REFUSAL_REASONS`，\*\*(\d+)\*\* 个）", sec)
    assert m, "§M.4.2 的'REFUSAL_REASONS（…N 个）'解析不出"
    assert int(m.group(1)) == len(reasons), f"写 {m.group(1)} 个，实测 {len(reasons)}"
    listed = sorted(set(re.findall(r"^\| `([a-z_]+)` \|", sec, re.M)))
    assert listed == reasons, f"§M.4.2 的 reason 表与 schema 不一致：文档多 {set(listed) - set(reasons)}／少 {set(reasons) - set(listed)}"


def test_m43_symbols_and_criteria_files_still_exist():
    """§M.4.3：它讲的是划分规则，没有计数值；判"符号与判据文件都还在"。"""
    from agentflow import policy as _policy  # noqa: PLC0415

    assert hasattr(_policy, "waves_of"), "`policy.waves_of` 不见了（§M.4.3 的核心符号）"
    assert hasattr(_policy, "_same_role_other_instance"), "`policy._same_role_other_instance` 不见了（实例轴）"
    assert (REPO / "tests" / "test_scheduler.py").exists(), "实例轴的负控 `tests/test_scheduler.py` 不见了"
    gates = (REPO / "tests" / "test_agent_b_gates.py").read_text(encoding="utf-8")
    assert "test_i6_two_agents_write_concurrently_without_deadlock" in gates, \
        "并发写不死锁那条判据不见了（§M.4.3 点名引它）"


def test_m8_rebuild_coverage_row_matches():
    """§M.8：`tests/test_rebuild.py` 的 `def test_` 数与 `tasks` 命中数（I-9 的补核结论）。"""
    tr = (REPO / "tests" / "test_rebuild.py").read_text(encoding="utf-8")
    n_tests = len(re.findall(r"^def test_", tr, re.M))
    n_tasks = tr.count("tasks")
    sec = _h2(_appendix(), "M.8")
    m = re.search(r"共 \*\*(\d+)\*\* 个用例", sec)
    assert m, "§M.8 的'共 N 个用例'解析不出"
    assert int(m.group(1)) == n_tests, f"§M.8 写 {m.group(1)} 个用例，实测 {n_tests}"
    m = re.search(r"\*\*(\d+)\*\* 处 `tasks`|0 处 `tasks`", sec)
    assert m, "§M.8 的'`tasks` 命中数'解析不出"
    got = int(m.group(1)) if m.group(1) else 0
    assert got == n_tasks, f"§M.8 写 {got} 处 tasks，实测 {n_tasks}"


def test_s1_zero_test_tools_row_matches(live):
    """§S1 #1：按 INVENTORY §4.1 的口径复算"零测试工具"，必须仍是 0 件。"""
    _, all_names = live
    blob = "".join(p.read_text(encoding="utf-8", errors="replace")
                   for p in (REPO / "tests").rglob("*.py"))
    zero = [n for n in sorted(all_names) if n not in blob]
    text = _appendix()
    block = text[text.find("## S1 "): text.find("## S2 ")]
    assert "留痕（2026-10-18" in block, "§S1 的标题/首行没有标留痕与日期"
    sec = block
    row = [ln for ln in sec.splitlines() if ln.startswith("| 1 |")]
    assert row, "§S1 的 #1 那一行不见了"
    m = re.search(r"\*\*(\d+) 件\*\*\s*没有出现在 `tests/`", row[0])
    assert m, "§S1 #1 的现读结论解析不出"
    assert int(m.group(1)) == len(zero), f"§S1 #1 写 {m.group(1)} 件，实测 {len(zero)}"


def test_s2_status_rows_match_the_live_facts(live):
    """§S2：#1/#2/#3/#5/#6/#10/#13 是现读结论；#7/#8/#12 必须标留痕与日期。"""
    text = _appendix()
    sec = _h2(text, "S2")
    rows: dict[int, str] = {}
    for line in sec.splitlines():
        m = re.match(r"^\| (\d+) \|", line)
        if m:
            rows[int(m.group(1))] = line
    assert len(rows) >= 13, f"§S2 只有 {len(rows)} 行（应有 13）"
    bad: list[str] = []
    for idx in (1, 2, 3, 5, 6, 10, 13):
        if "（现读）" not in rows.get(idx, ""):
            bad.append(f"§S2 #{idx} 没标'（现读）'")
    for idx in (7, 8, 12):
        if "留痕（2026-10-18" not in rows.get(idx, ""):
            bad.append(f"§S2 #{idx} 没标留痕与日期")
    if 'roles=("C", "D")' not in rows.get(5, ""):
        bad.append("§S2 #5 没有给出今天的现读（`roles=(\"C\", \"D\")`）")
    if "supported_not_proved" not in rows.get(6, ""):
        bad.append("§S2 #6 没有给出今天的现读（含 supported_not_proved）")
    if (REPO / "src" / "agentflow" / "release_check.py").exists():
        bad.append("§S2 #10 说它不存在，而 `src/agentflow/release_check.py` 现在存在了 ⇒ 那一行要改成'已落地'")
    assert not bad, "\n".join(bad)



# -*- coding: utf-8 -*-
"""docs/DEVELOPMENT-SPEC.md 的 §16（2026-10-27 的十三个机制簇）必须与盘上同一口径。

## 这个文件修的是什么

本批改动在 44 个文件里新增了 745 条符号（func / const / class / tool / toolname，机器清单
见 `agentflow/temp/_inventory_master.md`），而在这之前它们一条都没进规范：判据住在 `tests/` 里，
"这个设计该长什么样"只能靠读代码。业主的判词是「新设计未被规范收录」——
判据绿不等于规范在；规范不在，下一个人就无法判断自己该照哪个口径改。

所以 `§16` 把 745 条归成 13 个机制簇，每簇三格：规则 / 落点 / 判据。这一份判据守那三格的
机器可核面，理由与 `tests/test_role_specs_appendix_is_live.py` 同族：附录那边守的是
"读数是当次的"，这里守的是"规范点名的东西真的在盘上、规范写的数真的相等"。

## 三态

- 文档读不到 / 一节都没匹配到 / 索引表为空 => 红（"没查成"绝不等于"对上了"）；
- 节在、但三格里缺一格 => 红（判据失去对象，不是"这条没问题"）；
- 落点里的符号找不到 / 判据里的用例找不到 / 数与现算不等 => 红，并点名是哪一簇哪一格。

## 为什么连"数字"也判

只判符号存在会让"符号还在、数写成上个月的"静默常驻；而 `§16` 的现算格正是读者拿来判断
"这条口径还成不成立"的唯一落点。所以每簇的 `现算：` 格逐对现算，多一项少一项都红。

没法机器核的条目刻意不写数字：`§16.13` 那一簇的判据格写的是 `数字格：无` + 指路
（`§16.14` 逐条列了为什么不写）。这一份判据认这个标记，但不认"既没现算格、也没说为什么"
的空白 —— 那种空白是"悄悄少了一格"，不是"这条不需要数"。

## 两条反真空

改错一个字母（符号）与改大一个数（数字），本文件的检查都必须红。两条都作用在注入后的
文本上（`_symbol_problems` / `_live_problems` 收的是文本，不是路径），所以负控不需要写盘。
"""
from __future__ import annotations

import functools
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "DEVELOPMENT-SPEC.md"

#: 索引表那一行：`| C1 | 名称 | §16.1 | `tests/...py` |`。
_INDEX_ROW = re.compile(r"^\| (C\d+) \| (.+?) \| §(16\.\d+) \| (.+?) \|$", re.M)

#: 一簇的标题：`### [规范] §16.1 C1 时钟族：…`。
_HEAD = re.compile(r"^### \[规范\] §(16\.\d+) (.*)$", re.M)
_CLUSTER_IN_TITLE = re.compile(r"^(C\d+)\b")

#: 三格。刻意要求行首（规则那一格是段首、落点与判据是项目符号，两种写法都认），
#: 防止有人把三格折成一段散文之后判据静默失去对象。
_CELL = re.compile(r"^(?:- )?\*\*(规则|落点|判据)\*\*：(.+)$", re.M)

#: 落点里的 `file::symbol`（路径相对仓库根，符号名在该文件里必须能 grep 到）。
_SYMBOL = re.compile(r"`([^`\n]+?::[^`\n]+?)`")

#: 判据里的 `tests/x.py::test_y` 与裸文件 `tests/x.py`。
_TEST_CASE = re.compile(r"`(tests/[A-Za-z0-9_./]+\.py)::([A-Za-z0-9_]+)`")
_TEST_FILE = re.compile(r"`(tests/[A-Za-z0-9_./]+\.py)`")

#: 现算格：`名字` = 值，值以 、或 ； 分隔（值里不许含反引号或空白，否则读出来的是下一项）。
_LIVE = re.compile(r"`([^`\n]+)` = ([^`、\s]+)")

#: 没有数字格时那一簇必须写的标记（"说清为什么不写"），以及"现算："这一格本身的标记。
_NO_NUMBER = "数字格：无"
_LIVE_MARK = "现算："

CELLS = ("规则", "落点", "判据")


def _doc() -> str:
    text = DOC.read_text(encoding="utf-8")
    assert text.strip(), f"{DOC} 是空的 —— 判据失去对象"
    return text


def _sections(text: str) -> list[dict[str, str]]:
    """把 `### [规范] §16.N Ck …` 切成节；只返回带簇号的那些（§16.0 索引与 §16.14 收尾不算）。"""
    heads = list(_HEAD.finditer(text))
    out: list[dict[str, str]] = []
    for i, m in enumerate(heads):
        title = m.group(2).strip()
        found = _CLUSTER_IN_TITLE.match(title)
        if not found:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append({
            "section": "§" + m.group(1),
            "cluster": found.group(1),
            "title": title,
            "body": text[m.end():end],
        })
    return out


def _cells(body: str) -> dict[str, str]:
    seen = {label: cell for label, cell in _CELL.findall(body)}
    missing = [label for label in CELLS if not seen.get(label, "").strip()]
    assert not missing, f"这一节缺这几格：{missing}"
    return seen


def _index_rows(text: str) -> list[tuple[str, str, str, str]]:
    """(簇, 名称, 段落, 判据文件那一格)。"""
    return [(m.group(1), m.group(2).strip(), "§" + m.group(3), m.group(4))
            for m in _INDEX_ROW.finditer(text)]


# ---------------------------------------------------------------- 结构


def test_the_index_table_and_the_sections_line_up():
    """§16.0 的索引表与 §16.N 的节必须一一对上，段落号与簇号都不许错位。

    这条单列的理由：簇是靠索引表被找到的。少了表，13 节就成了一堆没人读的散文；
    表里多一行而没有那一节，读者点过去会看见别的东西（而且不会有别的判据红）。
    """
    text = _doc()
    rows = _index_rows(text)
    sections = _sections(text)
    assert rows, "§16.0 的索引表一行都解析不出（判据失去对象）"
    assert sections, "§16 里一个机制簇都没解析到（判据失去对象）"
    by_cluster = {s["cluster"]: s for s in sections}
    bad: list[str] = []
    if len(rows) != len(sections):
        bad.append(f"索引表 {len(rows)} 行但有 {len(sections)} 节")
    for cluster, _name, section, files in rows:
        got = by_cluster.get(cluster)
        if not got:
            bad.append(f"索引表有 {cluster}，但 §16 里没有这一簇的节")
            continue
        if got["section"] != section:
            bad.append(f"{cluster} 在表里写 {section}，而它的节是 {got['section']}")
        named = _TEST_FILE.findall(files)
        if not named:
            bad.append(f"{cluster} 的判据文件那一格没有点名任何测试文件")
        for rel in named:
            if not (REPO / rel).exists():
                bad.append(f"{cluster} 的判据文件不存在：{rel}")
    indexed = {row[0] for row in rows}
    for cluster in sorted(set(by_cluster) - indexed):
        bad.append(f"{cluster} 有节但没进索引表")
    assert not bad, "\n".join(bad)


def test_every_cluster_has_the_three_cells():
    """每簇三格（规则 / 落点 / 判据）都在，且规则那一格是一句能判真假的话。

    为什么要求长度：三格里最容易的坏法是留一格只有半句（"见上文"），那之后读者
    会拿一段没有对象的话当规范。这里只判"够不够长"，不判文风 —— 文风没有判据。
    """
    text = _doc()
    sections = _sections(text)
    bad: list[str] = []
    for sec in sections:
        try:
            cells = _cells(sec["body"])
        except AssertionError as exc:
            bad.append(f"{sec['section']} {sec['cluster']}：{exc}")
            continue
        if len(cells["规则"]) < 40:
            bad.append(f"{sec['section']} 的规则格只有 {len(cells['规则'])} 字，读不成一句规则")
        if "现算：" not in cells["判据"] and _NO_NUMBER not in cells["判据"]:
            bad.append(f"{sec['section']} 的判据格既没有现算数、也没写 `{_NO_NUMBER}` 与理由")
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- 落点


def _symbol_problems(text: str) -> list[str]:
    """落点里每个 `file::symbol` 都要在盘上：文件在、符号名真的出现在那个文件里。

    这是"文档 ↔ 代码"最便宜也最硬的一条：符号改名时它会红，而散文不会。
    """
    bad: list[str] = []
    sections = _sections(text)
    if not sections:
        return ["一个机制簇都没解析到 —— 判据失去对象"]
    for sec in sections:
        try:
            landing = _cells(sec["body"])["落点"]
        except AssertionError as exc:
            bad.append(f"{sec['section']}：{exc}")
            continue
        targets = _SYMBOL.findall(landing)
        if not targets:
            bad.append(f"{sec['section']} 的落点格里没有 `file::symbol` 形态的落点")
            continue
        for raw in targets:
            path, _, symbol = raw.partition("::")
            f = REPO / path
            if not f.exists():
                bad.append(f"{sec['section']} 点名的文件不存在：{path}")
                continue
            if symbol not in f.read_text(encoding="utf-8", errors="replace"):
                bad.append(f"{sec['section']} 说 `{symbol}` 在 {path}，但那个文件里没有这个名字")
    return bad


def test_every_symbol_named_in_a_section_exists_on_disk():
    """十三簇的落点逐个核存在性（符号名必须能 grep 到，不认行号）。"""
    bad = _symbol_problems(_doc())
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- 判据


def _criterion_problems(text: str) -> list[str]:
    """判据格里点名的测试文件必须在、点名的用例必须真的有 `def test_...`。"""
    bad: list[str] = []
    sections = _sections(text)
    if not sections:
        return ["一个机制簇都没解析到 —— 判据失去对象"]
    for sec in sections:
        try:
            cell = _cells(sec["body"])["判据"]
        except AssertionError as exc:
            bad.append(f"{sec['section']}：{exc}")
            continue
        cases = _TEST_CASE.findall(cell)
        if not cases:
            bad.append(f"{sec['section']} 的判据格没有点名任何一个 `tests/...::test_...`")
        for rel, func in cases:
            f = REPO / rel
            if not f.exists():
                bad.append(f"{sec['section']} 点名的判据文件不存在：{rel}")
                continue
            if f"def {func}(" not in f.read_text(encoding="utf-8", errors="replace"):
                bad.append(f"{sec['section']} 说 {rel} 里有 `{func}`，但那个文件里没有这个用例")
        for rel in _TEST_FILE.findall(cell):
            if not (REPO / rel).exists():
                bad.append(f"{sec['section']} 点名的判据文件不存在：{rel}")
    return bad


def test_every_criterion_file_and_case_exists():
    """判据格里的每一条（文件 + 用例名）都必须在盘上 —— 引一条不存在的用例是假证据。"""
    bad = _criterion_problems(_doc())
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- 现算


@functools.lru_cache(maxsize=1)
def _measures() -> dict[str, object]:
    """现算口的登记表：键必须与文档里 `现算：` 格的字面量逐字一致。

    键不在表里 => 文档写了一个没人量的数（红）；键在表里而文档没用它 => 登记表里躺着一个
    已死的条目（也红，见最后一条）。两边一起红，才不会出现"表在量 A、文档在写 B"的静默分家。
    """
    sys.path.insert(0, str(REPO / "src"))
    from agentflow import clock, conductor, depsection, errorstats, readouts  # noqa: PLC0415
    from agentflow import papermapping, propositionkey, schema, secretary, tools  # noqa: PLC0415
    from agentflow import agent_loop, verifications  # noqa: PLC0415
    from agentflow.tools import conductor_tools  # noqa: PLC0415
    from agentflow.agent_f import core as fcore  # noqa: PLC0415
    from agentflow.agent_f import create_plan as fplan  # noqa: PLC0415

    return {
        "clock.TIMER_KINDS": lambda: len(clock.TIMER_KINDS),
        "clock.PROGRAM_OUTCOMES": lambda: len(clock.PROGRAM_OUTCOMES),
        "clock.PURPOSE_SOURCES": lambda: len(clock.PURPOSE_SOURCES),
        "clock.PARK_STATES": lambda: len(clock.PARK_STATES),
        "tools.UNIVERSAL_TOOLS[clock.*]": lambda: len(
            [n for n in tools.UNIVERSAL_TOOLS if str(n).startswith("clock.")]),
        "conductor.AGENT_STATES": lambda: len(conductor.AGENT_STATES),
        "conductor.ACTIVE_AGENT_STATES": lambda: len(conductor.ACTIVE_AGENT_STATES),
        "conductor.RETIRE_REFUSAL_TARGET_NOT_SILENT":
            lambda: str(conductor.RETIRE_REFUSAL_TARGET_NOT_SILENT),
        "conductor.CHAIN_DELIVERY_STATES": lambda: len(conductor.CHAIN_DELIVERY_STATES),
        "conductor.CHAIN_MAX_HOPS": lambda: int(conductor.CHAIN_MAX_HOPS),
        "conductor_tools.POST_TASK_STATES": lambda: len(conductor_tools.POST_TASK_STATES),
        "agent_loop.MONITOR_TURN_SHAPES": lambda: len(agent_loop.MONITOR_TURN_SHAPES),
        "agent_loop.MONITOR_TURN_TOOLS": lambda: len(agent_loop.MONITOR_TURN_TOOLS),
        "agent_loop.PARK_EVENT": lambda: str(agent_loop.PARK_EVENT),
        "agent_loop.PREEMPTIBLE_DISPATCH": lambda: bool(agent_loop.PREEMPTIBLE_DISPATCH),
        "schema.ITEM_KINDS": lambda: len(schema.ITEM_KINDS),
        "schema.ITEM_EXPECTS": lambda: len(schema.ITEM_EXPECTS),
        "schema.ITEM_STATES": lambda: len(schema.ITEM_STATES),
        "depsection.COLUMN_KEYS": lambda: len(depsection.COLUMN_KEYS),
        "depsection.CITATION_LEVELS": lambda: len(depsection.CITATION_LEVELS),
        "depsection.CITATION_MIN_LEVEL": lambda: str(depsection.CITATION_MIN_LEVEL),
        "secretary.DEPS_MISSING_STATES": lambda: len(secretary.DEPS_MISSING_STATES),
        "verifications.CITATION_VERDICTS": lambda: len(verifications.CITATION_VERDICTS),
        "verifications.CITATION_SIGNABLE": lambda: len(verifications.CITATION_SIGNABLE),
        "verifications.CITATION_BLOCKING": lambda: len(verifications.CITATION_BLOCKING),
        "verifications.CITATION_CHECK_KEYS": lambda: len(verifications.CITATION_CHECK_KEYS),
        "secretary.PROPOSITION_VERDICTS": lambda: len(secretary.PROPOSITION_VERDICTS),
        "secretary.CONCEPT_IDENTITY_KINDS": lambda: len(secretary.CONCEPT_IDENTITY_KINDS),
        "propositionkey.BASIS_CONCEPT_TERM": lambda: str(propositionkey.BASIS_CONCEPT_TERM),
        "secretary.EFFORT_TIER_BANDS": lambda: len(secretary.EFFORT_TIER_BANDS),
        "secretary.EFFORT_TOOL_CLUSTERS": lambda: len(secretary.EFFORT_TOOL_CLUSTERS),
        "agent_f.core.FORMAL_OWNER": lambda: str(fcore.FORMAL_OWNER),
        "agent_f.core.E_METHODS": lambda: len(fcore.E_METHODS),
        "agent_f.core.FORMAL_EDGE_MISSING_REASON": lambda: str(fcore.FORMAL_EDGE_MISSING_REASON),
        "agent_f.create_plan.FORMAL_IS_NOT_F_TODO": lambda: str(fplan.FORMAL_IS_NOT_F_TODO),
        "papermapping.THEOREM_ENV_KINDS": lambda: len(papermapping.THEOREM_ENV_KINDS),
        "tools.UNIVERSAL_TOOLS": lambda: len(tools.UNIVERSAL_TOOLS),
        "tools.BOOKKEEPING_TABLES": lambda: len(tools.BOOKKEEPING_TABLES),
        "tools.KNOWLEDGE_TABLES": lambda: len(tools.KNOWLEDGE_TABLES),
        "readouts.ROSTER_DATA_KEYS": lambda: len(readouts.ROSTER_DATA_KEYS),
        "errorstats.ALL_CATEGORIES": lambda: len(errorstats.ALL_CATEGORIES),
        "errorstats.PROCESS_CATEGORIES": lambda: len(errorstats.PROCESS_CATEGORIES),
    }


def _value(raw: str) -> object:
    """文档里那个值的三档形态：`True`/`False`、十进制整数、其余按字符串。"""
    text = raw.rstrip("。，；)、")
    if text in ("True", "False"):
        return text == "True"
    if text.isdigit():
        return int(text)
    return text


def _live_pairs(cell: str) -> list[tuple[str, str]]:
    """从判据格里取出 `现算：` 之后的那一串 (名字, 原值)。"""
    if _LIVE_MARK not in cell:
        return []
    tail = cell.split(_LIVE_MARK, 1)[1]
    return _LIVE.findall(tail)


def _live_problems(text: str) -> list[str]:
    """逐簇对账现算格：数与现算相等；文档用到的键都在登记表里；登记表里没有死条目。"""
    bad: list[str] = []
    measures = _measures()
    sections = _sections(text)
    if not sections:
        return ["一个机制簇都没解析到 —— 判据失去对象"]
    used: set[str] = set()
    total = 0
    for sec in sections:
        try:
            cell = _cells(sec["body"])["判据"]
        except AssertionError as exc:
            bad.append(f"{sec['section']}：{exc}")
            continue
        pairs = _live_pairs(cell)
        if not pairs:
            if _NO_NUMBER not in cell:
                bad.append(f"{sec['section']} 没有现算格，也没写 `{_NO_NUMBER}`")
            continue
        for name, raw in pairs:
            total += 1
            used.add(name)
            if name not in measures:
                bad.append(f"{sec['section']} 的现算项 `{name}` 没有登记到 _measures()（没人量的数）")
                continue
            want = measures[name]()
            got = _value(raw)
            if got != want:
                bad.append(f"{sec['section']} 写 `{name}` = {got!r}，实测 {want!r}")
    if not total:
        bad.append("整份 §16 一个现算数都没读到 —— 判据失去对象")
    for dead in sorted(set(measures) - used):
        bad.append(f"_measures() 里的 `{dead}` 在 §16 里没有任何一条用到（已死的登记条目）")
    return bad


def test_every_live_number_matches_its_live_value():
    """现算格里的每个数 == 当次现算值；登记表与文档的键集必须互相覆盖。"""
    bad = _live_problems(_doc())
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- 反真空


def test_a_one_letter_change_in_a_symbol_turns_this_red():
    """负控 1：把落点里第一个符号的名字改掉一个字母 => 存在性判据必然红。

    判据不是橡皮图章。这一条与 `test_every_symbol_named_in_a_section_exists_on_disk`
    走同一个 `_symbol_problems`，只是喂进去的是被改过的文本。
    """
    text = _doc()
    first = None
    for sec in _sections(text):
        targets = _SYMBOL.findall(_cells(sec["body"])["落点"])
        if targets:
            first = targets[0]
            break
    assert first, "落点格里一个 `file::symbol` 都没找到 —— 负控没打进去（形态已经变了）"
    path, _, symbol = first.partition("::")
    mutated = symbol[:-1] + ("Q" if symbol[-1] != "Q" else "Z")
    injected = text.replace(f"`{path}::{symbol}`", f"`{path}::{mutated}`", 1)
    assert injected != text, "负控没注入进去 —— 那说明落点的写法已经变了（判据随之失效）"
    problems = _symbol_problems(injected)
    assert problems, "把符号名改掉一个字母之后判据仍然全绿 —— 这条判据是橡皮图章"


def test_a_one_off_number_turns_this_red():
    """负控 2：把第一个现算数改大 1 => 现算判据必然红。"""
    text = _doc()
    pairs: list[tuple[str, str]] = []
    for sec in _sections(text):
        pairs = _live_pairs(_cells(sec["body"])["判据"])
        if pairs:
            break
    assert pairs, "整份 §16 没有一个现算数 —— 负控没打进去（现算格已经不见）"
    name, raw = pairs[0]
    got = _value(raw)
    assert isinstance(got, int), f"第一个现算数 `{name}` 不是整数（{raw!r}），负控打不进去"
    injected = text.replace(f"`{name}` = {raw}", f"`{name}` = {got + 1}", 1)
    assert injected != text, "负控没注入进去 —— 那说明现算格的写法已经变了（判据随之失效）"
    problems = _live_problems(injected)
    assert problems, "把一个数改大 1 之后判据仍然全绿 —— 这条判据是橡皮图章"


def test_planting_the_old_single_number_reads_red():
    """负控 3：把某簇的判据格整段换成"见代码"（三格里最常见的那种退化）=> 必红。

    这一形态在别处出现过：判据格被一句"见实现"顶替，格子还在、对象没了，
    而任何只数"这一行在不在"的判据都还是绿的。
    """
    text = _doc()
    sec = _sections(text)[0]
    cells = _cells(sec["body"])
    thin = cells["判据"].split("；现算", 1)[0]
    degraded = sec["body"].replace(cells["判据"], thin + "（见代码）", 1)
    assert degraded != sec["body"], "负控没注入进去（判据格的形态已经变了）"
    injected = text.replace(sec["body"], degraded, 1)
    assert injected != text, "负控没注入进去（节的正文已经变了）"
    problems = _live_problems(injected)
    assert problems, "判据格退化成『见代码』之后现算判据仍然全绿 —— 它只在数行数"


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__]))

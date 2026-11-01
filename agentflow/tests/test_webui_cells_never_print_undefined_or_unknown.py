# -*- coding: utf-8 -*-
"""页面单元格：不许把「可能是 undefined 的值」直接 `String()`，不许把「空正文」印成 `unknown`。

## 这一份钉的是类，不是那两个个例

改前真机两处（2026-11-01，`projects/paper-rewrite-81`）：

1. `ui/src/pages/Evidence.tsx` 的「fail_open」列写着 `render: (r) => String(r.fail_open)` ——
   `out/secretary/` 下混进来的两份旁支台账（`nontriviality.jsonl` 89 行 /
   `proposition_verdicts.jsonl` 54 行）根本没有这一栏，于是 613 行里有 143 行在屏上
   印成字面量 `undefined`。同页其余列都走 `components/Table.cell()`（它承诺
   `null` / `undefined` / 空串 ⇒ `unknown`，三态），只有这一列绕过了它。
2. `ui/src/pages/Acceptance.tsx` 的「读数」列写着 `detail === "" ? "unknown" : detail` ——
   而 `unknown` 在同一页专指「没查成」（`verdictBadge` 那一档）。`reviewaccept` 在几条
   判据过了的时候不写 `details`（`within_cost_cap` / `attachment_is_honest` 的通过
   分支），于是同一行会出现「结论 过了 / 读数 unknown」。

如果判据只钉这两行，下一张页面换个字段名就会再犯一次（改前全仓就有 8 处同族：见下）。
所以这里钉的是两条规则，扫 `ui/src/pages/*.tsx` 的每一个单元格：

- R1：单元格里出现 `String(<行成员>)`（`r.x` / `row.x` / `w.x` / `r["x"]`），而这一格里
  没有任何「缺值守卫」（`=== null` / `!== null` / `=== undefined` / `!== undefined` /
  `typeof` / `??`）⇒ 一条 finding。守卫写法放行，是因为它已经把「缺」折成了某个显示值；
  要判的是绕过取值器这件事（`cell()` / `plain()` / `blank()` 是唯一白名单）。
- R2：单元格里把正文类字段（`detail` / `details[…]` / `note` / `reason` /
  `problem` / `prose`）的空串折成裸 `"unknown"` ⇒ 一条 finding。三态词（`state` /
  `verdict` / `triage`）的空串就是「没查成」，不在此列 —— 这一条的分界线是语义，
  不是"扫到 unknown 就算"。

「单元格」的取法（两条规则都按它）：列定义 `render:` 的函数体（从 `=>` 起做括号平衡，
取到同层的 `,` / `;`）＋ 手写 `<td …>…</td>` 的正文。前者覆盖 `Table` 的列，后者覆盖
`Acceptance` 那种手写表格 —— 少覆盖一种，B 那一处就会从缝里漏过去。

## 改前红 / 改后绿（同一份扫描器，2026-11-01 实测）

改前 8 条 / 5 个文件（本文件落地后这些位置都已改成走取值器）：

```text
Acceptance.tsx:123  R2  detail === "" ? "unknown" : detail
Artifacts.tsx:235   R1  String(w.mine_attempts)（同一句里还有 ${w.mine_attempts}）
Artifacts.tsx:348   R1  render: (r) => String(r.bytes)
Artifacts.tsx:454   R1  render: (r) => String(r.bytes)
Evidence.tsx:651    R1  render: (r) => String(r.fail_open)
Home.tsx:512        R1  text={String(s.bad_lines)}
Live.tsx:88         R1  text={String(r.role)}
Live.tsx:106        R1  <span class="mono">{String(r.pid)}</span>
```

改后 0 条。这不是"当时这 8 处刚好合规"：三条负控证明这份扫描器真的会红（把改前的写法
种回副本 ⇒ 必红，且点名 file:line），一条正控证明它不会把合法的取值器写法冤杀。

## 为什么六处 `String(x.y)` → `cell(x.y)` 是安全的重构

有值时输出逐字不变（`cell(42) === "42"`、`cell(false) === "false"`）；只有"这一格
压根没有"时才从字面量 `undefined` 变成 `unknown`（= 这一页对"没读到"的既有承诺）。
"""

from __future__ import annotations

import pathlib
import re

import pytest

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
PAGES = UI_SRC / "pages"

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)

#: R1：`String(<标识符>.<成员>)` / `String(<标识符>[…)`。
_STRING_OF_MEMBER = re.compile(r"String\(\s*([A-Za-z_$][\w$]*)\s*(\.|\[)")

#: 「缺值守卫」：这一格已经把"缺"折成某个显示值，就不是"绕过取值器"。
_GUARDS: tuple[str, ...] = ("=== null", "!== null", "=== undefined", "!== undefined",
                            "!= null", "== null", "typeof ", "??")

#: R2：正文类字段（它们的空串意思是"这一格没有正文"，不是"没查成"）。
_PROSE_FIELDS: tuple[str, ...] = ("detail", "details", "note", "reason", "problem", "prose")

#: R2：`<表达式> === "" ? … "unknown"`（表达式里要出现正文类字段才算）。
_EMPTY_TO_UNKNOWN = re.compile(
    r'([A-Za-z_$][\w$\[\]."\']*)\s*===\s*""\s*\?[^;{}]*?"unknown"')


def _strip_comments(text: str) -> str:
    """去注释（块注释按行数换成空行，行号不变；JSX 的 `{/* … */}` 也算块注释）。"""

    def blank(match: re.Match[str]) -> str:
        return "\n" * match.group(0).count("\n")

    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub(blank, text))


def _balanced(text: str, start: int, *, limit: int = 4000) -> str:
    """从 `start` 起取一段平衡的表达式（括号栈回到 0，或遇到同层的 `,` / `;` / `}`）。"""
    depth = 0
    out: list[str] = []
    for ch in text[start:start + limit]:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch in ",;" and depth == 0:
            break
        out.append(ch)
    return "".join(out)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def cells(text: str) -> list[tuple[int, str]]:
    """这份源码里所有「单元格」的 `(行号, 正文)`：列定义 `render:` 的函数体 + 手写 `<td>`。"""
    out: list[tuple[int, str]] = []
    for match in re.finditer(r"render:\s*", text):
        body = text.find("=>", match.end())
        body = match.end() if body < 0 else body + 2
        out.append((_line_of(text, match.start()), _balanced(text, body)))
    for match in re.finditer(r"<td\b[^>]*>", text):
        end = text.find("</td>", match.end())
        if end >= 0:
            out.append((_line_of(text, match.start()), text[match.end():end]))
    return out


def audit_page_sources(sources: dict[str, str]) -> list[str]:
    """判据本体：每条 finding 一句，带 `文件:行`（空 = 这一批页面都合规）。"""
    problems: list[str] = []
    for name, raw in sources.items():
        body = _strip_comments(raw)
        for lineno, cell in cells(body):
            flat = " ".join(cell.split())
            for match in _STRING_OF_MEMBER.finditer(cell):
                if any(guard in cell for guard in _GUARDS):
                    continue
                problems.append(
                    f"{name}:{lineno} R1 单元格里 `String({match.group(1)}"
                    f"{match.group(2)}…)` 绕过了取值器，且没有缺值守卫 ⇒ 这一格没有时"
                    f"会印字面量 `undefined`：{flat[:110]!r}")
            for match in _EMPTY_TO_UNKNOWN.finditer(cell):
                tested = match.group(1)
                if not any(word in tested for word in _PROSE_FIELDS):
                    continue
                problems.append(
                    f"{name}:{lineno} R2 单元格把正文类字段（{tested}）的空串折成裸 "
                    f"`unknown`（与同页「unknown = 没查成」撞名）：{flat[:110]!r}")
    return problems


def _page_sources(root: pathlib.Path = PAGES) -> dict[str, str]:
    """`ui/src/pages/*.tsx` 的 `文件名 → 源码`。"""
    return {path.name: path.read_text(encoding="utf-8")
            for path in sorted(root.glob("*.tsx"))}


# ====================================================================== 正控
def test_every_cell_in_every_page_goes_through_a_getter() -> None:
    """正控：全 10 个页面、每一个单元格都合规（R1 / R2 都 0 条）。"""
    sources = _page_sources()
    assert sources, "ui/src/pages 下一个 .tsx 都没读到 ⇒ 这条判据是空转"
    problems = audit_page_sources(sources)
    assert problems == [], problems


def test_the_scan_is_not_vacuous() -> None:
    """反真空：页面数、单元格数、以及本棒owns 的两页都必须真的有落脚点。

    只断言 `problems == []` 是不够的：扫描器的 `render:` / `<td>` 正则哪天写坏了，
    它会对空集合恒绿 —— 那正是"看起来还在挡着什么"的形态。
    """
    sources = _page_sources()
    assert len(sources) >= 8, sorted(sources)          # 10 个页面（少两个就说明没扫全）
    counts = {name: len(cells(_strip_comments(text))) for name, text in sources.items()}
    assert sum(counts.values()) >= 100, counts          # 实测 140 个单元格
    with_cells = {name for name, n in counts.items() if n}
    assert len(with_cells) >= 8, counts
    # 本棒的两页：Evidence 的列、Acceptance 的手写 <td> —— 两种取法各要有一个落脚点
    assert counts["Evidence.tsx"] >= 20, counts["Evidence.tsx"]
    assert counts["Acceptance.tsx"] >= 3, counts["Acceptance.tsx"]

    # 正向锚点：这两处逐字就是改后的形态（不是"碰巧没被扫到"）
    evidence = sources["Evidence.tsx"]
    assert "render: (r) => cell(r.fail_open)," in evidence, (
        "Evidence 的 fail_open 列没有走 cell()（它会重新印出字面量 undefined）")
    # 按去注释后的源码断言：那一行改前的写法在注释里被引用着（讲"改前会印 undefined"），
    # 代码里不许再有它。
    assert "String(r.fail_open)" not in _strip_comments(evidence)
    acceptance = sources["Acceptance.tsx"]
    assert "{blank(detail)}" in acceptance, (
        "Acceptance 的「读数」列没有走 blank()（空 detail 会重新印成 unknown）")
    assert 'detail === "" ? "unknown"' not in _strip_comments(acceptance)


def test_blank_documents_that_empty_is_not_unread() -> None:
    """取值器 `blank()` 的 docstring 必须写清「空/缺 ≠ 没查成」。

    业主 2026-11-01 的裁定：`—` 不加括号说明，解释写在 docstring 里（不在每个格子里）。
    所以这句话是这条判据的一部分：它一变，`blank()` 的语义就没人守了。
    """
    table = (UI_SRC / "components" / "Table.tsx").read_text(encoding="utf-8")
    assert "export function blank(" in table, "ui/src/components/Table.tsx 里没有 `blank()`"
    doc_end = table.index("export function blank(")
    doc = table[table.rindex("/**", 0, doc_end):doc_end]
    assert "空/缺 ≠ 没查成" in doc, doc
    assert "unknown" in doc and "cell()" in doc, doc


# ====================================================================== 负控
def _with_replaced(page: str, *, old: str, new: str) -> dict[str, str]:
    """把某个页面的一段源码换掉，返回「一份整页副本」的 sources（不动真文件）。"""
    sources = _page_sources()
    text = sources[page]
    assert old in text, f"{page} 里找不到要替换的那一段（判据自己过期了）：{old!r}"
    return {**sources, page: text.replace(old, new, 1)}


def test_negative_control_the_old_fail_open_render_turns_it_red() -> None:
    """负控①：把 Evidence 那一处改回 `String(r.fail_open)` ⇒ 必红，且点名 file:line。

    这一条就是业主那句「把修好的那处临时改回 ⇒ 必红」的机器形态：它在整页副本上
    改，所以行号与真文件同一套坐标。
    """
    sources = _page_sources()
    planted = _with_replaced("Evidence.tsx", old="render: (r) => cell(r.fail_open),",
                            new="render: (r) => String(r.fail_open),")
    problems = audit_page_sources(planted)
    assert len(problems) == 1, problems
    lineno = sources["Evidence.tsx"][:sources["Evidence.tsx"].index(
        "render: (r) => cell(r.fail_open),")].count("\n") + 1
    assert problems[0].startswith(f"Evidence.tsx:{lineno} R1"), problems[0]
    assert "undefined" in problems[0], problems[0]


def test_negative_control_the_old_empty_detail_turns_it_red() -> None:
    """负控②：把 Acceptance 的「读数」列改回 `detail === "" ? "unknown" : detail` ⇒ 必红。"""
    sources = _page_sources()
    planted = _with_replaced("Acceptance.tsx", old="{blank(detail)}",
                            new='{detail === "" ? "unknown" : detail}')
    problems = audit_page_sources(planted)
    assert len(problems) == 1, problems
    lineno = sources["Acceptance.tsx"][:sources["Acceptance.tsx"].index(
        "{blank(detail)}")].count("\n") + 1
    assert problems[0].startswith(f"Acceptance.tsx:{lineno} R2"), problems[0]
    assert "撞名" in problems[0], problems[0]


def test_negative_control_a_multiline_render_body_is_seen_too() -> None:
    """负控③：缺陷写成多行 `render:` 体也照样被抓（证明不是按行扫的）。"""
    sources = _page_sources()
    planted = dict(sources)
    planted["Run.tsx"] = sources["Run.tsx"] + (
        "\nconst extra = {\n"
        "  key: \"bytes\",\n"
        "  title: \"字节\",\n"
        "  render: (r) =>\n"
        "    r.bytes === undefined\n"
        "      ? \"—\"\n"
        "      : String(r.bytes),\n"
        "};\n")
    assert audit_page_sources(planted) == [], (
        "带 undefined 守卫的多行写法被冤杀了（守卫就该放行）")
    planted["Run.tsx"] = sources["Run.tsx"] + (
        "\nconst extra = {\n"
        "  key: \"bytes\",\n"
        "  title: \"字节\",\n"
        "  render: (r) =>\n"
        "    r.ok\n"
        "      ? String(\n"
        "          r.bytes,\n"
        "        )\n"
        "      : \"—\",\n"
        "};\n")
    problems = audit_page_sources(planted)
    assert len(problems) == 1 and problems[0].startswith("Run.tsx:"), problems


def test_positive_control_the_sanctioned_getters_are_not_flagged() -> None:
    """正控（反冤杀）：`cell` / `plain` / `blank` 与带守卫的写法都是 0 条。

    没有这一条，"两条规则"就可能被写成"凡出现 String( 就算缺陷"——那会把合法的
    数字格（`r.x === null ? "unknown" : cell(r.x)`）一起打掉，判据就没人敢用了。
    """
    good = {
        "Fake.tsx": (
            "export function P() {\n"
            "  return <Table columns={[\n"
            "    { key: \"a\", title: \"a\", render: (r) => cell(r.a) },\n"
            "    { key: \"b\", title: \"b\", render: (r) => plain(r.b) },\n"
            "    { key: \"c\", title: \"c\", render: (r) => blank(r.c) },\n"
            "    { key: \"d\", title: \"d\", render: (r) => (r.d === null ? \"unknown\" : cell(r.d)) },\n"
            "    { key: \"e\", title: \"e\", render: (r) => (r.e ?? \"—\") },\n"
            "    { key: \"f\", title: \"f\", render: (r) => <span>{typeof r.f === \"number\" ? String(r.f) : \"—\"}</span> },\n"
            "    { key: \"g\", title: \"g\", render: (r) => <span>{String(7)}</span> },\n"
            "  ]} />;\n"
            "}\n"),
        "Fake2.tsx": (
            "export function Q(props) {\n"
            "  return <table><tbody><tr>\n"
            "    <td class=\"mono\">{blank(props.detail)}</td>\n"
            "    <td class=\"mono\">{props.state === \"\" ? \"unknown\" : props.state}</td>\n"
            "  </tr></tbody></table>;\n"
            "}\n"),
    }
    assert audit_page_sources(good) == []


if __name__ == "__main__":  # pragma: no cover - 人工跑一遍看读数
    got = audit_page_sources(_page_sources())
    print(f"findings = {len(got)}")
    for one in got:
        print("  " + one)
    pytest.main([__file__, "-q"])

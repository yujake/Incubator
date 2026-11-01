# -*- coding: utf-8 -*-
"""ROLE-SPECS 的 E / G / H / L 四节与两处全局读数必须等于现场（审计 C 第 ② 条）。

这四节停在旧设计上：E 还挂着 `check_formal`（方法已不存在）、边还写 `B D`
（实为 `B D V`）、动作还写 5 个（实为 4）；G-7 还写着已删掉的 `≥6`；H-6 还写
"向 E 核形式化"（形式化归 L，而 H 没有到 L 的边）；L.1 引用一个已删的常量名
（它的写法按两段拼在 `_DELETED_SYMBOL` 里，见那里的理由：整串字面量会命中
`test_e_has_no_lean_side.py::test_4` 的判据，而那条判据扫的正是全部 `.py`，包括本文件）、
自检还写"四步"（实现是五步）。另外 §0.5 的边总数与
§0.7 的动作总数在文档内部自相矛盾（35 vs 36、65 vs 64）。

判据只读文档与现场声明（`capabilities` / `specs`），真值取"源"：文档跟着源改，
不跟着文档改判据。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "ROLE-SPECS.md"

#: L.1 曾经引用过的那个已删常量。**按两段拼出来**，不写成整串字面量 ——
#: `tests/test_e_has_no_lean_side.py::test_4_no_code_reference_to_the_deleted_symbols`
#: 扫的是 `src` / `tests` / `scripts` / `tools` 下全部 `.py`（那条判据自己也在这四个根里），
#: 整串一写进本文件，那条判据就会命中这一行。拼出来的名字与整串逐字等价，
#: 所以下面那条「文档里不再出现它」的断言强度一处不降（判的是同一个名字）。
_DELETED_SYMBOL = "E_LEAN" + "_SIDE_HARD_OFF"


def _text() -> str:
    text = DOC.read_text(encoding="utf-8")
    assert text.strip(), f"{DOC} 是空的 —— 判据失去对象"
    return text


def _section(text: str, role: str) -> str:
    """取 `## <role> —— …` 那一节（到下一个一级标题为止）。"""
    m = re.search(rf"^## {role} —— .*$", text, re.M)
    assert m, f"ROLE-SPECS 里找不到 §{role}（判据失去对象，不是那一节没问题）"
    rest = text[m.start():]
    nxt = re.search(r"^## ", rest[1:], re.M)
    return rest[: 1 + nxt.start()] if nxt else rest


def _row(section: str, prefix: str) -> str:
    for line in section.splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(f"这一节里找不到以 {prefix!r} 开头的行")


def _capabilities():
    if str(REPO / "src") not in sys.path:
        sys.path.insert(0, str(REPO / "src"))
    from agentflow import capabilities as C

    return C


def _block_05(text: str) -> str:
    m = re.search(r"^### 0\.5 .*?(?=^### 0\.6 )", text, re.M | re.S)
    assert m, "§0.5 召唤边那一节找不到"
    return m.group(0)


# ---------------------------------------------------------------- E


def test_e_section_has_no_formal_checker_and_has_the_right_face():
    text = _text()
    sec = _section(text, "E")
    C = _capabilities()

    assert "形式化验证" not in sec.splitlines()[0], "E 的节标题还挂着「与形式化验证」"
    assert "check_formal" not in sec, "E 那一节还点名 check_formal（AgentE 上没有这个方法）"
    m = re.search(r"E 的动作只有 (\d+) 个", sec)
    assert m, "E 那一节里读不到「E 的动作只有 N 个」"
    assert int(m.group(1)) == len(C.CAPABILITIES["E"]), (
        f"E 的动作数写 {m.group(1)}，现场 {len(C.CAPABILITIES['E'])}"
    )
    out = re.search(r"\*\*E 能召唤谁\*\*：(.+?)(?=\n- |\Z)", sec, re.S)
    assert out, "E 那一节里读不到「E 能召唤谁」"
    assert set(C.ALLOWED_EDGES["E"]) <= set(re.findall(r"`([A-Z])`", out.group(1))), (
        f"E 能召唤谁漏了：{sorted(set(C.ALLOWED_EDGES['E']) - set(re.findall(r'`([A-Z])`', out.group(1))))}"
    )


def test_the_edge_row_and_the_two_edge_totals_are_live():
    text = _text()
    C = _capabilities()
    live = sum(len(v) for v in C.ALLOWED_EDGES.values())
    block = _block_05(text)

    row = re.search(r"^\| `E` \| `([^`]*)` \|$", block, re.M)
    assert row, "§0.5 里读不到 E 那一行"
    assert set(row.group(1).split()) == set(C.ALLOWED_EDGES["E"]), (
        f"§0.5 的 E 行写 {row.group(1)!r}，现场 {sorted(C.ALLOWED_EDGES['E'])}"
    )
    m = re.search(r"\*\*边总数 = (\d+)\*\*", block)
    assert m and int(m.group(1)) == live, f"§0.5 的边总数写 {m.group(1) if m else None}，现场 {live}"
    m = re.search(r"今天全表的读数是 (\d+)", block)
    assert m and int(m.group(1)) == live, (
        f"§0.5 里「今天全表的读数是 N」写 {m.group(1) if m else None}，现场 {live}"
    )
    tails = re.findall(r"复跑：[^\n]*⇒ `(\d+)`", block)
    assert tails, "§0.5 里读不到最后那条复跑读数"
    assert int(tails[-1]) == live, f"§0.5 最后一条复跑写 {tails[-1]}，现场 {live}"


# ---------------------------------------------------------------- G


def test_g_section_claims_match_the_live_declaration():
    sec = _section(_text(), "G")
    C = _capabilities()

    g7 = _row(sec, "| G-7 |")
    assert "≥6" not in g7 and not re.search(r"≥\s*\d+", g7), (
        "G-7 还写着写死的下限（specs/g.py 已按台账命题数定环境数）"
    )
    assert "statements" in g7, "G-7 没有说环境数由 statements 的定理类行数定"

    g3 = _row(sec, "| 判一条断言是否被证明")
    assert "**E** + **形式化检查器**" not in g3, "G.3 还把形式化判给 E"
    assert "L" in g3, "G.3 没写形式化归 L"

    cite = _row(sec, "| 断言引用不存在的文献")
    assert "已知缺陷" not in cite, "G.7 的悬空引用还挂着「已知缺陷」（已修）"
    assert "dangling_citation" in cite, "G.7 没写修后的受控形态 dangling_citation"

    m = re.search(r"`capabilities\.CAPABILITIES` 的 (\d+) 个动作 schema", sec)
    assert m, "G.9 里读不到「N 个动作 schema」"
    assert int(m.group(1)) == len(C.CAPABILITIES["G"]), (
        f"G.9 写 {m.group(1)} 个动作，现场 {len(C.CAPABILITIES['G'])}"
    )


# ---------------------------------------------------------------- H


def test_h_section_says_formalization_belongs_to_l_and_has_no_false_landing():
    sec = _section(_text(), "H")

    h6 = _row(sec, "| H-6 |")
    assert "向 E 核形式化" not in h6, "H-6 还写「向 E 核形式化」"
    assert "形式化归 L" in h6, "H-6 没写「形式化归 L」"

    h8 = _row(sec, "| H-8 |")
    assert "要留凭据用 `review.report`" not in h8, "H-8 还承诺用 review.report 留扫描凭据"
    assert "review.scan" in h8 and "本身就是凭据" in h8, (
        "H-8 没写「review.scan 的读数本身就是凭据」"
    )


# ---------------------------------------------------------------- L


def test_l_section_has_no_deleted_symbol_and_counts_five_self_check_steps():
    sec = _section(_text(), "L")

    assert _DELETED_SYMBOL not in sec, f"L.1 还引用已删符号 {_DELETED_SYMBOL}"
    assert "formal_not_in_e" in sec, "L.1 没写 E 今天的受控拒绝码 formal_not_in_e"
    assert "四步" not in sec, "L 那一节还写「四步」（leantoolchain 是五步）"
    assert "五步" in sec, "L 那一节没有写「五步」"


# ---------------------------------------------------------------- §0.7


def test_the_action_table_total_is_live_and_adds_up():
    text = _text()
    C = _capabilities()
    live = sum(len(v) for v in C.CAPABILITIES.values())

    m = re.search(r"^### 0\.7 .*?(\d+) 个动作", text, re.M)
    assert m, "§0.7 的标题里读不到动作总数"
    assert int(m.group(1)) == live, f"§0.7 标题写 {m.group(1)} 个动作，现场 {live}"

    foot = re.search(r"十一行加起来是 \*\*(\d+)\*\*（([^）]+)）", text)
    assert foot, "§0.7 的尾注里读不到『十一行加起来是 N（…）』"
    stated = int(foot.group(1))
    addends = [int(x) for x in foot.group(2).split("+")]
    want = [len(C.CAPABILITIES[r]) for r in ("A", "B", "C", "D", "E", "F", "G", "H", "V", "L", "M")]
    assert stated == live and sum(addends) == live, (
        f"§0.7 尾注写 {stated}（加出来 {sum(addends)}），现场 {live}"
    )
    assert addends == want, f"§0.7 尾注的逐角色加数 {addends}，现场 {want}"

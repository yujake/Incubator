# -*- coding: utf-8 -*-
"""`docs/ROLE-SPECS.md` 里所有逐角色动作表的机器判据（`draft/36` 的 T-3）。

## 为什么需要它

这张文档里有两处手抄 `capabilities.CAPABILITIES` 的逐角色动作表：§0.7「动作表」（全角色 A–H,V,L + 主控 M）；
- §M.4.1「M 能召唤的 8 个角色 × 它们的动作」（可召唤面）。`capabilities.py` 内部的同类手抄数字有断言看着，但这两处没有 —— 于是它们静默漂了：2026-09-30 加
`A.search_literature` 时表头还写着"48 个动作"；本次（T-3）加判据时又发现两处表都比能力表少 2 个动作（`D.register_conjecture`、`H.review_report`），
而且两处的表头数字（51 / 48）与各自的明细之和（49 / 46）都对不上。两次都不是"打错一个数"，而是"加动作的人不知道有这张表" —— 所以判据钉的是表与能力表逐角色逐动作相等这个结构，而不是某个数字。

## 判据的四条（缺一条就会退化成真空断言）

1. 每张动作表的角色集合都必须是合法角色（⊆ A–H,V,L + M）且非空；§0.7 那张必须恰好覆盖全部；
2. 每张表里每个角色的动作名集合与动作数都要与 `capabilities.actions_for(role)` 一致；
3. 每张表标题里的数字（"N 个动作" / "N 个可召唤动作"）必须等于该表逐角色动作数之和
—— 读者第一眼看到的是标题，它不能是唯一没人管的那一格；
4. §M.4.1 那张表的总数还要与边表对得上（`ALLOWED_EDGES["M"]` 覆盖的角色的动作之和）：
这张表说的是"主控能召唤多少动作"，判据就该按边表算，而不是按"文档里列了谁"算。
"""
from __future__ import annotations

import pathlib
import re

import pytest

from agentflow import capabilities as C
from agentflow import schema as S

REPO = pathlib.Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "ROLE-SPECS.md"

#: 表里那一行：`| A | 3 | `run_once` `run` |`
#: 角色字符类含 `V`（F-02 起）：文档里 §0.7 与 §M.4.1 两张表都要有 V 那一行，
#: 而解析器不认 `V` 时它会静默地少一行 —— 判据 1/2/3 全都看不见这件事。
#: 2026-10-23：再补 `L`。§0.7 里 L 那一行（`formalize` `check_formal` `record`）一直在，
#: 字符类写成 `[A-HMV]` 时它解析不出来 —— 于是标题的"65 个动作"与逐行之和（62）
#: 对不上。旧写法记录的是 L 立项前的角色数；补上 L 之后标题与明细同源，不是放宽判据。
_ROW_RE = re.compile(r"^\|\s*([A-HMVL])\s*\|\s*\*{0,2}(\d+)\*{0,2}\s*\|(.*)\|\s*$")
#: 标题里的读数：`…，51 个动作）` / `（48 个可召唤动作）`
_COUNT_IN_TITLE_RE = re.compile(r"(\d+)\s*个(?:可召唤)?动作")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_HEADING_RE = re.compile(r"^#{2,4} ")


def _sections(text: str) -> list[tuple[str, str]]:
    """按标题切段：`[(标题行, 这一段正文)]`。"""
    lines = text.splitlines()
    out: list[tuple[str, list[str]]] = []
    for line in lines:
        if _HEADING_RE.match(line):
            out.append((line, []))
        elif out:
            out[-1][1].append(line)
    return [(title, "\n".join(body)) for title, body in out]


def _rows(body: str) -> dict[str, tuple[int, list[str]]]:
    """`角色 -> (表里写的动作数, 表里列的动作名)`。"""
    rows: dict[str, tuple[int, list[str]]] = {}
    for line in body.splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        rows[m.group(1)] = (int(m.group(2)), _BACKTICK_RE.findall(m.group(3)))
    return rows


def _action_tables() -> list[tuple[str, str, dict[str, tuple[int, list[str]]]]]:
    """文档里所有"逐角色动作表"：`[(标题, 正文, 解析出的行)]`。

    认表的口径：这一段里既有表头（`动作名`）又有 ≥2 行 `| 角色 | 数字 | … |`。
    """
    found = []
    for title, body in _sections(DOC.read_text(encoding="utf-8")):
        if "动作名" not in body and "可召唤动作数" not in body:
            continue
        rows = _rows(body)
        if len(rows) >= 2:
            found.append((title, body, rows))
    return found


def test_the_document_really_has_more_than_one_action_table() -> None:
    """反真空：这份文档里确实有（至少）两张逐角色动作表 —— 判据的分析面不是空的。

    这条同时把"同一份数据抄了两遍"这件事记在判据里：将来谁把两处合成一处，
    这条会红，提醒他同步改判据（而不是让判据悄悄失去覆盖面）。
    """
    tables = _action_tables()
    assert len(tables) >= 2, (
        f"只找到 {len(tables)} 张逐角色动作表 —— 要么文档结构变了、要么解析口径坏了；"
        "两种情况都要人看一眼，不许静默缩小覆盖面")


def test_every_action_table_lists_only_real_roles() -> None:
    """判据 1：表里的角色必须是合法角色（⊆ A–H,V,L + M）且非空。"""
    allowed = set(S.ROLES) | {S.CONDUCTOR_ROLE}
    for title, _body, rows in _action_tables():
        assert rows, f"{title!r} 那张表一行都没解析出来"
        bad = sorted(set(rows) - allowed)
        assert not bad, f"{title!r} 那张表里有不存在的角色：{bad}"


def test_the_main_action_table_covers_every_role() -> None:
    """判据 1（§0.7 那一张）：必须恰好覆盖 A–H,V,L + 主控 M。"""
    for title, _body, rows in _action_tables():
        if "0.7" not in title:
            continue
        expected = set(S.ROLES) | {S.CONDUCTOR_ROLE}
        assert set(rows) == expected, (
            f"§0.7 的角色集合与能力表不一致：多出 {sorted(set(rows) - expected)}、"
            f"少了 {sorted(expected - set(rows))}")
        return
    pytest.fail("没找到 §0.7 那张动作表（文档结构变了？）")


def _table_cases() -> list[tuple[str, str]]:
    """`[(表标题, 角色)]` —— 供参数化用。主控排除在外：它那一行的第三列是依据（散文），
    不是动作名清单，由专门那条判据管（`test_the_conductor_row_says_it_has_no_actions`）。"""
    out = []
    for title, _body, rows in _action_tables():
        for role in sorted(rows):
            if role == S.CONDUCTOR_ROLE:
                continue
            out.append((title, role))
    return out


@pytest.mark.parametrize("title,role", _table_cases())
def test_each_roles_actions_in_every_table_match_the_capability_table(title: str, role: str) -> None:
    """判据 2：每张表里每个角色的动作名与动作数都要与 `capabilities.CAPABILITIES` 一致。

    钉的是集合相等而不是"顺序相同"：表是给人读的对照表，重排不改变它说的意思；
    但漏一个、多一个、拼错一个名字都必须红。
    """
    declared = [spec.action for spec in C.actions_for(role)]
    rows = dict((t, r) for t, _b, r in _action_tables())[title]
    count, names = rows[role]
    assert count == len(declared), (
        f"{title!r} 里 {role} 写 {count} 个动作，能力表实为 {len(declared)} 个：{declared}")
    assert set(names) == set(declared), (
        f"{title!r} 里 {role} 的动作名与能力表不一致："
        f"表里多 {sorted(set(names) - set(declared))}、"
        f"少了 {sorted(set(declared) - set(names))}")


@pytest.mark.parametrize("title", [t for t, _b, _r in _action_tables()])
def test_every_table_title_count_equals_its_rows_sum(title: str) -> None:
    """判据 3：标题里的"N 个动作"必须等于该表逐角色动作数之和。

    为什么单列一条：判据 2 都过、标题写错的形态真的发生过（两处表头与明细都对不上）。
    读者第一眼看到的是标题，所以它不能是唯一没人管的那一格。
    """
    rows = dict((t, r) for t, _b, r in _action_tables())[title]
    found = [int(x) for x in _COUNT_IN_TITLE_RE.findall(title)]
    if not found:
        pytest.skip(f"{title!r} 的标题里没有『N 个动作』这个读数")
    rows_sum = sum(count for count, _ in rows.values())
    assert found[0] == rows_sum, (
        f"{title!r} 的标题写 {found[0]} 个动作，而它逐角色加起来是 {rows_sum} —— "
        "标题与明细至少要有一处是错的")


def test_the_summonable_table_total_matches_the_edge_table() -> None:
    """判据 4：§M.4.1 说的是"主控能召唤多少动作"，总数按边表算，不按"文档里列了谁"算。

    这条与判据 3 不同：判据 3 只能证明"标题与明细自洽"，证明不了"明细覆盖的是该覆盖的角色"
    （例如漏掉某个可召唤角色时，标题与明细会一起变小、照样自洽）。
    """
    expected = sum(len(C.actions_for(r)) for r in C.ALLOWED_EDGES[S.CONDUCTOR_ROLE])
    for title, _body, rows in _action_tables():
        if "M.4.1" not in title:
            continue
        assert set(rows) == set(C.ALLOWED_EDGES[S.CONDUCTOR_ROLE]), (
            f"§M.4.1 列的角色与 `ALLOWED_EDGES['M']` 不一致："
            f"多 {sorted(set(rows) - set(C.ALLOWED_EDGES[S.CONDUCTOR_ROLE]))}、"
            f"少 {sorted(set(C.ALLOWED_EDGES[S.CONDUCTOR_ROLE]) - set(rows))}")
        found = [int(x) for x in _COUNT_IN_TITLE_RE.findall(title)]
        assert found and found[0] == expected, (
            f"§M.4.1 的标题写 {found} 个可召唤动作，按边表算实为 {expected} 个")
        return
    pytest.fail("没找到 §M.4.1 那张表（文档结构变了？）")


def test_negative_control_a_deleted_row_is_caught(tmp_path: pathlib.Path, monkeypatch) -> None:
    """负控 ①（T-3 的验收判据之一）：表里少一行/少一个动作必须红。

    做法：把文档复制到临时目录、把 H 那一行改回"3 个动作、没有 review_report"，
    让判据去读那份副本。没有这条，上面那些断言可能只是"永远为真"（夹具坏了也照样绿）。
    """
    import sys

    text = DOC.read_text(encoding="utf-8")
    good = "| H | 5 | `review` `verify_fixes` `list_findings` `judge_quote_semantics` `review_report` |"
    bad = "| H | 3 | `review` `verify_fixes` `list_findings` |"
    assert good in text, "夹具前提变了：文档里 H 那一行不是判据假设的写法"
    fake = tmp_path / "ROLE-SPECS.md"
    fake.write_text(text.replace(good, bad), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "DOC", fake)

    titles = [t for t, _b, _r in _action_tables() if "0.7" in t]
    assert titles, "副本里应当仍有 §0.7 那张表"
    with pytest.raises(AssertionError):
        test_each_roles_actions_in_every_table_match_the_capability_table(titles[0], "H")


def test_negative_control_a_new_action_without_a_table_update_is_caught(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """负控 ②（T-3 的验收判据之二）：能力表加了动作而文档没改必须红。

    做法：给 F 造一个不在表里的动作（`dataclasses.replace` 改一个真 `ActionSpec` 的名字），
    再跑同一条判据。它模拟的正是真实事故：加动作的人不知道文档里有这张手抄表。
    """
    import dataclasses

    real = C.actions_for

    def fake_actions_for(role: str):
        specs = real(role)
        if role == "F":
            return (*specs, dataclasses.replace(specs[0], action="brand_new_action",
                                               handler_name="brand_new_action"))
        return specs

    monkeypatch.setattr(C, "actions_for", fake_actions_for)
    titles = [t for t, _b, _r in _action_tables() if "0.7" in t]
    with pytest.raises(AssertionError):
        test_each_roles_actions_in_every_table_match_the_capability_table(titles[0], "F")


def test_the_conductor_row_says_it_has_no_actions() -> None:
    """判据 2（M 那一格）：主控的"动作"是 `summon()` 本身，能力表里它是空的。

    这一行不能省：省了读者会以为"主控没有动作 = 漏写了"，而事实是设计如此。
    """
    for title, _body, rows in _action_tables():
        if "0.7" not in title:
            continue
        assert S.CONDUCTOR_ROLE in rows, "§0.7 必须有主控那一行（写明它没有动作）"
        count, names = rows[S.CONDUCTOR_ROLE]
        assert count == 0, f"主控的动作数应当是 0，表里写 {count}"
        assert C.actions_for(S.CONDUCTOR_ROLE) == (), (
            "能力表里主控不该有动作（`CAPABILITIES['M'] == ()` 是可断言的事实）")
        assert any("CAPABILITIES" in n for n in names), (
            f"主控那一行要写明依据（`CAPABILITIES[\"M\"] == ()`），实得 {names}")
        return
    pytest.fail("没找到 §0.7 那张动作表")

# -*- coding: utf-8 -*-
"""判据：`docs/TWO-AXES-GRADE-AND-KIND.md` 那几张表 == 从代码与现场现算（逐格）。

## 这条判据钉什么

1. 文档的表不许手抄：表一（五元位 ⇒ 等级）、表二（五元位 ⇒ 档位）、表三（等级 ⇄ 档位，
   真机 + 夹具两张横表）、表 3X（"不是函数"的现场反例）逐格与现算比对；
2. 表过期 ⇒ 红：`derive_grade` 的一条规则改了、档位那一列的写法改了、现场快照换了，
   这里都会红 —— 不是"差不多"，是 `第 N 行第 M 格: 文档 'x' ≠ 现算 'y'`；
3. 反真空（三条负控，见文件末）：
   - 把文档里任意一格改错 ⇒ 比对必须报出来；
   - 把 `derive_grade` 的一条规则改掉而不改文档 ⇒ 比对必须报出来，且先断言
     "改过的规则真的改变了这张表"（否则这条负控什么都没量到）；
   - 删掉一段标记块 ⇒ 报"表不见了"，不许当成"没有不一致"。

## 为什么判据读的是快照、不是 `projects/`

`projects/` 在 `.gitignore` 里（`:164` `/agentflow/projects/`），一份新克隆的仓库里没有它。
判据要是直接读 `projects/`，这条测试会在别人机器上以"读不到 = 没有不一致"的形态变绿 ——
那正是本仓反复踩过的"没查成被读成查过了"。所以现场先冻成
`tests/fixtures/two_axes_scene.json`（带 `captured_at` 与复跑命令），判据读它，
文档 §8 给刷新命令。

## 三张表各自"从哪段代码现算"

- 表一：`evidencebits.derive_grade`（`src/agentflow/evidencebits.py:1060`）+ `bits_of` 的
  `audited_badge`（`:273`）；
- 表二：`secretary._manuscript_upgrade_basis`（`src/agentflow/secretary.py:1533`，
  五元位唯一能决定的那一格 `signed`，`:1585`）+ `verifications._grade_recomputed_from_signature`
  （`src/agentflow/verifications.py:2625`，通道 ⇒ 档位 `:2685-2686`，32×2 的那个实验）；
- 表三：`derive_grade` 逐行现算 `grade`，按 `evidence_kind` 做横表；现场是
  `tests/fixtures/two_axes_scene.json`（真机频次快照）与
  `tests/fixtures/paper_rewrite_86_reviewed_bit.json`（夹具工作区）。
"""
from __future__ import annotations

import copy
import re

import pytest

import _two_axes as TA

from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import schema as S

#: 文档里的标记块：`<!-- TWO-AXES:<名字>:BEGIN --> … <!-- TWO-AXES:<名字>:END -->`。
_BEGIN = re.compile(r"^<!--\s*TWO-AXES:([A-Z0-9]+):BEGIN\s*-->$")
_END = re.compile(r"^<!--\s*TWO-AXES:([A-Z0-9]+):END\s*-->$")

#: 业主那句话（逐字），它必须还在文档里 —— 两张换算表可以被改写，这句话不行。
ONE_SENTENCE = ("「**可引**」读**档位**（`evidence_kind`）；「**多硬**」读**等级**（`grade`）。\n"
                "两者不是同一个轴，谁也替不了谁")


# ------------------------------------------------------------------ 解析


def 文档() -> str:
    path = TA.REPO / "docs" / "TWO-AXES-GRADE-AND-KIND.md"
    assert path.is_file(), f"`{path}` 不在盘上（三张表没有落点）"
    return path.read_text(encoding="utf-8")


def 解析(text: str | None = None) -> dict[str, list[list[str]]]:
    """把带标记的表格块解析成 `{名字: 行}`（行含表头；分隔行已去掉；格子已去空白）。"""
    out: dict[str, list[list[str]]] = {}
    cur: str | None = None
    for raw in (文档() if text is None else text).splitlines():
        line = raw.strip()
        m = _BEGIN.match(line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, [])
            continue
        m = _END.match(line)
        if m:
            assert cur == m.group(1), f"标记块交叉了：{cur!r} 里出现了 {m.group(1)!r} 的 END"
            cur = None
            continue
        if cur is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        out[cur].append(cells)
    return out


def 期望() -> dict[str, tuple[tuple[str, ...], list[tuple[str, ...]]]]:
    return TA.期望块()


def 逐格比对(name: str, got: list[list[str]]) -> list[str]:
    """`got`（文档里那张表）与现算的差异，一格一条；空清单 = 对上了。"""
    want_header, want_rows = 期望()[name]
    if not got:
        return [f"{name}: 标记块里一张表都没有（表被删了 / 标记写错 / 只写了表头）"]
    problems: list[str] = []
    header, *body = got
    if tuple(header) != tuple(want_header):
        problems.append(f"{name} 表头：文档 {header} ≠ 现算 {list(want_header)}")
    if len(body) != len(want_rows):
        problems.append(f"{name} 行数：文档 {len(body)} ≠ 现算 {len(want_rows)}")
    for i, (got_row, want_row) in enumerate(zip(body, want_rows), 1):
        if len(got_row) != len(want_row):
            problems.append(f"{name} 第 {i} 行：列数 {len(got_row)} ≠ {len(want_row)}")
            continue
        for j, (a, b) in enumerate(zip(got_row, want_row), 1):
            if a != b:
                problems.append(f"{name} 第 {i} 行第 {j} 格：文档 {a!r} ≠ 现算 {b!r}")
    if len(body) > len(want_rows):
        problems.append(f"{name} 多出来 {len(body) - len(want_rows)} 行（现算没有这些组合）")
    return problems


# ------------------------------------------------------------------ 三张表


def test_doc_tables_match_code() -> None:
    """三张表（+ 两张附表）逐格 == 现算。"""
    blocks = 解析()
    problems: list[str] = []
    for name in 期望():
        problems.extend(逐格比对(name, blocks.get(name, [])))
    assert not problems, "文档与现算对不上：\n" + "\n".join(problems)


def test_all_markers_present_and_not_vacuous() -> None:
    """反真空：五段标记都在，且表里真的有多样的值（不许"空表也算对上"）。"""
    blocks = 解析()
    assert set(期望()) <= set(blocks), f"文档缺标记块：{sorted(set(期望()) - set(blocks))}"
    table1 = blocks["TABLE1"]
    assert len(table1) == 33, f"表一应当是表头 + 32 行，实际 {len(table1)} 行"
    grades = {row[6] for row in table1[1:]}
    assert grades == set(EB.GRADES), (
        f"表一的等级列只出现了 {sorted(grades)} —— 四档没全出现，说明这几格没被真跑过"
        f"（期望 {list(EB.GRADES)}）")
    badges = {row[7] for row in table1[1:]}
    assert badges == {"true", "false"}, f"`audited_badge` 两档应当都出现，实际 {sorted(badges)}"
    table2 = blocks["TABLE2"]
    assert len(table2) == 33, f"表二应当是表头 + 32 行，实际 {len(table2)} 行"
    assert {row[7] for row in table2[1:]} == {TA.NOT_FROM_BITS}, (
        "表二的档位那一列必须逐格写「不由五元位决定」；出现了别的值 ⇒ "
        "要么真有函数了（那要先改代码与文档），要么有人在那一列手抄了档位")


def test_table1_is_a_function_of_bits_but_ignores_audited() -> None:
    """等级确实是五元位的函数（同五位必同等级），而第 5 位（`audited`）不在函数里。"""
    for numeric, proof, reviewed, formal, _audited in TA.COMBO_GRID[:16]:
        a = EB.derive_grade(EB.bits_of(numeric=numeric, proof=proof, reviewed=reviewed,
                                       formal=formal, audited=True))
        b = EB.derive_grade(EB.bits_of(numeric=numeric, proof=proof, reviewed=reviewed,
                                       formal=formal, audited=False))
        assert a == b, (f"`audited` 翻转改变了等级（{a!r} → {b!r}）——那说明第 5 位进了"
                        "`derive_grade`，本文件 §3.3 与表一都得重写")


def test_numeric_only_verified_lifts_the_grade() -> None:
    """第 1 位四态里只有 `verified` 抬等级（`pending`/`na`/`failed` 等价）。"""
    got = {state: EB.derive_grade(
        EB.bits_of(numeric=state, proof=True, reviewed=False, formal="pending", audited=False))
        for state in EB.BIT_STATES}
    assert got["verified"] == "strong_conjecture", got
    assert {got[s] for s in ("pending", "na", "failed")} == {"conjecture"}, got


def test_kind_is_not_a_function_of_bits() -> None:
    """档位对五元位不敏感、对证明通道敏感 —— 32 组 × 2 条通道，现跑。"""
    got = TA.档位换通道的实验()
    assert set(got) == {"文字证明", "穷举程序"}, sorted(got)
    文字, 穷举 = got["文字证明"], got["穷举程序"]
    assert len(文字) == len(穷举) == 32, (len(文字), len(穷举))
    assert set(文字) == {"proof_review"}, (
        f"文字证明通道下 32 组五元位给出了 {sorted(set(文字))} —— 多于一个值意味着"
        "五元位参与了选档（那与本文件表二的说法相反，先改代码再说）")
    assert set(穷举) == {"proof"}, f"穷举通道下 32 组五元位给出了 {sorted(set(穷举))}"
    assert 文字[0] != 穷举[0], (
        "两条通道给出同一个档位 ⇒ 这条实验什么都没量到（反真空：通道必须真的改变档位）")


def test_two_vocabularies_do_not_overlap_and_the_gate_judges_the_kind() -> None:
    """两套词表不相交；"可引"那道闸吃的是档位，等级传进去只会静默落空。"""
    assert not (set(EB.GRADES) & set(S.EVIDENCE_KINDS)), "等级与档位出现同名取值"
    assert EB.GRADE_NOT_APPLICABLE not in S.EVIDENCE_KINDS, (
        "`not_applicable` 混进了档位词表 —— 它是等级的「不适用」那一档，不是档位")
    assert DS.CITATION_MIN_LEVEL == "proof_review", DS.CITATION_MIN_LEVEL
    assert DS.CITATION_LEVELS == frozenset({"proof_review", "proof"}), (
        f"可引集合变了：{sorted(DS.CITATION_LEVELS)}（改它要同时改本文件 §1 与表三）")
    for ek in S.EVIDENCE_KINDS:
        assert DS.citation_level_allowed(ek) == (ek in DS.CITATION_LEVELS), ek
    for grade in [*EB.GRADES, EB.GRADE_NOT_APPLICABLE]:
        assert DS.citation_level_allowed(grade) is False, (
            f"等级 {grade!r} 被判成「够格被引」 —— 两套词表串了")


def test_scene_snapshot_is_consistent() -> None:
    """现场快照自洽：条数对得上、证人真的在册、反例对真的成立。"""
    scene = TA.现场()
    total = sum(int(sg["count"]) for sg in scene["signatures"])
    assert total == int(scene["rows_total"]), (
        f"快照里 signatures 的条数合计 {total} ≠ rows_total {scene['rows_total']}")
    assert int(scene["workspaces"]) >= 50, scene["workspaces"]
    assert len(scene["signatures"]) >= 40, len(scene["signatures"])
    assert len(scene["witnesses"]) >= 8, len(scene["witnesses"])
    census = {TA._签名键(str(sg["kind"]), str(sg["evidence_kind"]), sg["bits"])
              for sg in scene["signatures"]}
    for row in scene["witnesses"]:
        key = TA._签名键(str(row["kind"]), str(row["evidence_kind"]), row["bits"])
        assert key in census, f"证人行 {row['workspace']}/{row['stmt_id']} 不在频次快照里"
    # 三组反例各自的形状（不许"文档说有反例、现场其实没有"）
    by_pair: dict[str, list[dict]] = {}
    for row in scene["witnesses"]:
        by_pair.setdefault(str(row["pair"]), []).append(row)
    for pair, rows in by_pair.items():
        if pair == "A" or pair == "A2":
            bits = {TA._签名键(str(r["kind"]), str(r["evidence_kind"]), r["bits"])[2] for r in rows}
            assert len(bits) == 1, f"反例 {pair} 组的五元位不是逐字相同：{len(bits)} 种"
            assert len({str(r["evidence_kind"]) for r in rows}) >= 2, (
                f"反例 {pair} 组的档位没有分叉 ⇒ 这个反例不成立")
        elif pair == "B":
            assert len({str(r["evidence_kind"]) for r in rows}) == 1, "反例 B 组同一个档位"
            assert len({TA.等级(r) for r in rows}) >= 2, "反例 B 组的等级没有分叉"
        elif pair == "C":
            for r in rows:
                assert str(r["evidence_kind"]) == "proof_review", r
                assert TA.等级(r) == "conjecture", r


def test_doc_keeps_the_one_sentence() -> None:
    """业主那一句"两个轴"的话必须逐字还在（表可以改，结论不许悄悄改）。"""
    assert ONE_SENTENCE in 文档(), (
        "文档 §0 那句结论被改写了：两套读法的关系是这次任务的核心，改它要先改判据")


# ------------------------------------------------------------------ 反真空


def test_negative_control_a_wrong_cell_turns_red() -> None:
    """把文档里任意一格改错 ⇒ 逐格比对必须报出来。"""
    blocks = 解析()
    broken = copy.deepcopy(blocks["TABLE1"])
    broken[5][6] = "conjecture"          # 第 5 行（#04）的等级格
    problems = 逐格比对("TABLE1", broken)
    assert problems, "改错了一格却没报 —— 逐格比对是空的（判据失效）"
    assert any("第 5 行第 7 格" in p for p in problems), problems


def test_negative_control_b_changed_derive_grade_rule_turns_red(monkeypatch) -> None:
    """把 `derive_grade` 的一条规则改掉而不改文档 ⇒ 比对必须报出来。"""
    original = EB.derive_grade

    def 改过的等级(bits, *, kind: str = "") -> str:
        """把"第 2 位 + 第 4 位 ⇒ theorem"改成"还要第 3 位"（`evidencebits.py:1083` 那条）。"""
        got = original(bits, kind=kind)
        if got == "theorem" and not bool(bits.get("reviewed")):
            return "pre_theorem"
        return got

    monkeypatch.setattr(EB, "derive_grade", 改过的等级)
    mutated = TA.表一行()
    moved = [r for r in mutated if r[6] == "pre_theorem"]
    assert len(moved) > 6, (
        "改过的规则没有让更多格落到 pre_theorem ⇒ 这条负控没量到那条规则（反真空失效）")
    doc_rows = 解析()["TABLE1"]
    problems = 逐格比对("TABLE1", doc_rows)
    assert problems, "改了 derive_grade 的一条规则、文档没改，却一格格都对上了（判据失效）"
    assert any("pre_theorem" in p for p in problems), problems


def test_negative_control_c_missing_block_turns_red() -> None:
    """删掉一段标记块 ⇒ 报"表不见了"，不许当成"没有不一致"。"""
    text = 文档()
    stripped = re.sub(r"<!-- TWO-AXES:TABLE2:BEGIN -->.*?<!-- TWO-AXES:TABLE2:END -->", "",
                      text, flags=re.S)
    assert stripped != text, "文档里没找到 TABLE2 的标记块（解析器的标记名与文档不一致）"
    blocks = 解析(stripped)
    problems = 逐格比对("TABLE2", blocks.get("TABLE2", []))
    assert problems and "一张表都没有" in problems[0], problems


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

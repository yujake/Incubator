# -*- coding: utf-8 -*-
"""判据：`docs/TWO-AXES-GRADE-AND-KIND.md` 那几张表 == 从代码与现场现算（逐格）。

## 2026-11-05 业主裁定之后（这是本文件的第二次生命）
「cross_check 等价于强猜想等价于有普通数值实验支撑的猜想……不妨就用等级制平替掉」+
「穷举证书相当于 lean 形式化，表示绝对正确」。于是本文件钉的东西从"两个轴"换成
"等级是唯一的轴"：档位只是等级的历史反算名，判定面（可引门槛）读等级。

旧的"两个轴"结论不删，进文档 §6 历史（判据 `test_doc_keeps_the_history` 钉住日期、
裁定原文与 362 行里 169 行不一致这个读数）。

## 这条判据钉什么

1. 文档的表不许手抄：表一（五元位 ⇒ 等级）、表二（五元位 ⇒ `signed` + 档位反算名）、
   表三（等级 × 历史档位的存量审计横表）、表 3X（存量漂移的现场样本）逐格与现算比对；
2. 表过期 ⇒ 红：`derive_grade` / 反算表改了、现场快照换了，这里都会红 ——
   不是"差不多"，是 `第 N 行第 M 格: 文档 'x' ≠ 现算 'y'`；
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

#: 裁定之后的一句话（逐字）。文档 §0 必须写着它。
ONE_SENTENCE = ("**等级是唯一的轴**：`conjecture < strong_conjecture < pre_theorem < theorem`；\n"
                "档位（`evidence_kind`）只是等级的历史反算名（`kind_from_grade`）。")

#: 文档 §6 历史那一段必须逐字保留的三件：日期、裁定原文、存量不一致读数。
HISTORY_DATE = "2026-11-05"
HISTORY_RULING = "cross_check等价于强猜想等价于有普通数值实验支撑的猜想"
HISTORY_RULING_2 = "穷举证书相当于lean形式化"
HISTORY_COUNT = "169"


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
    # 2026-11-05：表二最后一列从「不由五元位决定」改成档位反算名 —— 它必须是
    # `kind_from_bits` 的真输出（逐格 == 现算），不是手抄的字面量。
    want_kinds = [row[-1] for row in TA.表二行()]
    got_kinds = [row[7] for row in table2[1:]]
    assert got_kinds == want_kinds, (
        "表二的档位列与 `kind_from_bits` 的现算不一致 ⇒ 要么表过期，要么有人手抄了档位")
    assert set(got_kinds) == set(EB.LEGACY_KINDS), (
        f"表二的档位只出现了 {sorted(set(got_kinds))} —— 反算表里四档应当都出现")


def test_table1_is_a_function_of_bits_but_ignores_audited() -> None:
    """等级确实是五元位的函数（同五位必同等级），而第 5 位（`audited`）不在函数里。"""
    for numeric, proof, reviewed, formal, _audited in TA.COMBO_GRID[:16]:
        a = EB.derive_grade(EB.bits_of(numeric=numeric, proof=proof, reviewed=reviewed,
                                       formal=formal, audited=True))
        b = EB.derive_grade(EB.bits_of(numeric=numeric, proof=proof, reviewed=reviewed,
                                       formal=formal, audited=False))
        assert a == b, (f"`audited` 翻转改变了等级（{a!r} → {b!r}）——那说明第 5 位进了"
                        "`derive_grade`，本文件 §3.3 与表一都得重写")


def test_numeric_verified_with_a_proof_is_a_theorem() -> None:
    """2026-11-05：穷举证书与 Lean 同级 ⇒ numeric=verified ∧ proof ⇒ `theorem`。

    负控（反真空的另一半）：没有证明时，数值怎么翻都到不了定理 ——
    `theorem = 证明 ∧ 机器可核` 里的"证明"那一半不许被这一条改掉。
    """
    with_proof = EB.bits_of(numeric="verified", proof=True, reviewed=False, formal="pending",
                            audited=False)
    assert with_proof["grade"] == "theorem", with_proof
    for state in EB.BIT_STATES:
        without = EB.bits_of(numeric=state, proof=False, reviewed=False, formal="pending",
                             audited=False)
        assert without["grade"] in ("conjecture", "strong_conjecture"), (state, without)


def test_legacy_kind_is_a_function_of_the_grade() -> None:
    """档位只由等级反算：`kind_from_grade(derive_grade(bits)) == kind_from_bits(bits)`。

    这条是旧判据 `test_kind_is_not_a_function_of_bits` 的反面（业主 2026-11-05：
    「不妨就用等级制平替掉」）。它比旧的那条更强：旧条只证"档位不是五元位的函数"，
    这条证"档位是同一个函数的反算值"—— 32 组逐格核，任何一格漂开就红。
    """
    for numeric, proof, reviewed, formal, audited in TA.COMBO_GRID:
        bits = EB.bits_of(numeric=numeric, proof=proof, reviewed=reviewed,
                          formal=formal, audited=audited)
        grade = EB.derive_grade(bits)
        assert EB.kind_from_bits(bits) == EB.kind_from_grade(grade), (
            numeric, proof, reviewed, formal, audited, grade)
        assert EB.kind_from_bits(bits) in EB.LEGACY_KINDS, bits
    # 反真空：五档等级确实落到四个不同的反算名上（不是"全返回同一个"）。
    assert {EB.kind_from_grade(g) for g in EB.GRADES} == set(EB.LEGACY_KINDS)


def test_two_vocabularies_do_not_overlap_and_the_gate_judges_the_grade() -> None:
    """两套词表不相交；"可引"那道闸吃的是等级（2026-11-05 改口径）。

    反向断言（不许两套词表再分家）：把历史档位词传进可引闸必须落空 ——
    判定面只认等级；档位要先走 `kind_from_grade` 换算。
    """
    assert not (set(EB.GRADES) & set(S.EVIDENCE_KINDS)), "等级与档位出现同名取值"
    assert EB.GRADE_NOT_APPLICABLE not in S.EVIDENCE_KINDS, (
        "`not_applicable` 混进了档位词表 —— 它是等级的「不适用」那一档，不是档位")
    assert DS.CITATION_MIN_LEVEL == "pre_theorem", DS.CITATION_MIN_LEVEL
    assert DS.CITATION_LEVELS == frozenset({"pre_theorem", "theorem"}), (
        f"可引集合变了：{sorted(DS.CITATION_LEVELS)}（它是从 `evidencebits.GRADES` 切的，"
        "改门槛要同时改本文件与文档）")
    for grade in [*EB.GRADES, EB.GRADE_NOT_APPLICABLE]:
        assert DS.citation_level_allowed(grade) == (grade in DS.CITATION_LEVELS), grade
    for ek in S.EVIDENCE_KINDS:
        assert DS.citation_level_allowed(ek) is False, (
            f"历史档位 {ek!r} 被判成「够格被引」—— 两套词表串了（判定面读等级）")


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
    """文档 §0 必须逐字写着"等级是唯一的轴 / 档位只是反算名"（2026-11-05 裁定）。"""
    assert ONE_SENTENCE in 文档(), (
        "文档 §0 那句结论不是裁定后的口径 —— 判定面已经读等级了，文档不许还写两个轴")


def test_doc_keeps_the_history() -> None:
    """旧的双轴结论不删，进 §6 历史：日期 + 裁定原文 + 存量 169 条不一致都必须还在。

    为什么钉这三样：这次改造是语义变更，不是"原来写错了"。后来的读者必须能看见
    "2026-11-05 之前确实是两个轴、确有 362 行里 169 行对不上"，否则会把这段历史
    误读成"从来就只有一个轴"，下次又把它分回去。
    """
    text = 文档()
    for needle in (HISTORY_DATE, HISTORY_RULING, HISTORY_RULING_2, HISTORY_COUNT):
        assert needle in text, f"文档 §6 历史缺了 {needle!r} —— 历史被删掉了"
    assert "两个轴" in text, "文档 §6 必须写明「之前是两个轴」，否则历史读不出对比"


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

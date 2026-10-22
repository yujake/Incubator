# -*- coding: utf-8 -*-
"""判据（覆盖矩阵）：多证明模型的 L1 → L9 每一环都必须有一个真的判据文件守着。

## 这一份在防什么（"某一环其实没测"）

正控（`test_multi_proof_end_to_end.py`）一条线走完九环，看上去"全覆盖"。但那是
一条线，不是一个矩阵：只要某一环的判据文件被改名、被删、被清空，或者
表里干脆漏掉一环，全量门照样全绿 —— 因为没有任何东西在数"九环各由谁守"。
这一份就是把"九环 → 判据文件 → 那一条 test"钉成一张常量表，并逐条核：

1. 表里的每一环，目标文件存在且真的含那个 test（用 `ast` 扫模块级
   `def test_*`，不起子进程 —— 起子进程会在沙箱里踩到管道边界，也会让这一条判据
   依赖"另一个 pytest 愿意跑起来"）；
2. 表里出现但文件不存在 / 文件里 0 个 test / 名字对不上 ⇒ 红，且点名是哪一环；
3. 表里缺 L1–L9 任何一环 ⇒ 红（反真空：漏一环等于那一环没人守）；
4. 这条矩阵判据本身不是空转：把表在内存里改坏（删一个键 / 指向不存在的文件 /
   指向一个没有 test 的文件），判据必须红并且点名那一环 —— 三条负控各跑一次，
   全部用 `monkeypatch` 在内存里改，不落盘。

## 表怎么读

`LINKS[环] = {"file": 判据文件, "tests": (那一条 test 的名字, ...), "also": 补充分支}`。
`also` 是同一环在另一个文件里的判据（例如 L7 的两半：R10 的计数在
`test_two_dimensional_dependency_grouping.py`，mapping 格的三态在
`test_paper_mapping_table.py`）—— 两半都是 L7 的判据，缺一半就是半环。

## 这一张表不是"审计报告"，它是一份契约

改判据文件名、改 test 名、拆文件，都会让这条判据红。那不是噪声：它正是这一环
"还有人守"的唯一机器读数。要改就同时改这一张表，并在理由里写清换成了哪一条。
"""
from __future__ import annotations

import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 九环必须齐（顺序就是业主那张单子的顺序；`_coverage_problems` 按它判缺环）。
EXPECTED_LINKS: tuple[str, ...] = (
    "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9",
)

#: 九环 → 守它的那个判据文件与那一条（或那几条）test。
#:
#: 选点口径：谁最直接地钉住这一环，就写谁；同一环的两半分散在两个文件时，
#: 主栏写一半、`also` 写另一半。端点（`test_multi_proof_end_to_end.py` /
#: `test_multi_proof_negative_matrix.py`）在本批之前没有任何判据，所以 L3 与 L9
#: 的"位与等级"、"只读面"两环由端点主守 —— 那不是退而求其次：本批之前
#: `statement_grade` 与网页面上的 `reviewed` 一条判据都没有（见交付报告）。
LINKS: dict[str, dict[str, object]] = {
    "L1": {
        "file": "tests/test_multi_proof_write_side.py",
        "tests": ("test_two_proofs_put_p1_in_proof_text_and_p2_in_the_list",),
        "also": (("tests/test_multi_proof_write_side.py",
                  ("test_a_proof_text_only_call_is_byte_identical_to_a_one_proof_list",)),),
    },
    "L2": {
        "file": "tests/test_proof_review_reaches_the_statement.py",
        "tests": ("test_signing_the_current_proof_reaches_the_statement_row",),
        "also": (("tests/test_multi_proof_write_side.py",
                  ("test_signing_proof_two_records_the_object_in_the_signature_line",)),),
    },
    "L3": {
        "file": "tests/test_multi_proof_end_to_end.py",
        "tests": ("test_the_multi_proof_line_is_connected_end_to_end",),
        "also": (("tests/test_multi_proof_write_side.py",
                  ("test_proof_two_does_not_borrow_proof_ones_signature",)),),
    },
    "L4": {
        "file": "tests/test_two_dimensional_dependency_grouping.py",
        "tests": ("test_proof_two_keeps_its_own_path_groups",
                  "test_proof_one_and_proof_two_are_never_melted_into_one_path"),
        "also": (("tests/test_multi_proof_negative_matrix.py",
                  ("test_a_bad_proof_tail_is_not_folded_into_p1",)),),
    },
    "L5": {
        "file": "tests/test_two_dimensional_dependency_grouping.py",
        "tests": ("test_the_group_readings_are_isomorphic_to_the_one_dimensional_ones",
                  "test_proof_one_and_proof_two_stay_two_candidate_paths"),
        "also": (("tests/test_multi_proof_end_to_end.py",
                  ("test_the_multi_proof_line_is_connected_end_to_end",)),),
    },
    "L6": {
        "file": "tests/test_paper_mapping_table.py",
        "tests": ("test_clean_mapping_passes",
                  "test_multi_proof_rows_do_not_stand_in_for_each_other"),
        "also": (("tests/test_multi_proof_end_to_end.py",
                  ("test_the_multi_proof_line_is_connected_end_to_end",)),),
    },
    "L7": {
        "file": "tests/test_two_dimensional_dependency_grouping.py",
        "tests": ("test_r10_counts_per_statement_and_proof_pair",),
        "also": (("tests/test_paper_mapping_table.py",
                  ("test_the_closing_reading_has_all_three_states",)),
                 ("tests/test_multi_proof_negative_matrix.py",
                  ("test_a_paper_without_a_table_fails_and_is_never_downgraded",)),),
    },
    "L8": {
        "file": "tests/test_paper_mapping_table.py",
        "tests": ("test_objective_kinds_block_and_subjective_ones_only_name",),
        "also": (("tests/test_multi_proof_negative_matrix.py",
                  ("test_an_unresolvable_ledger_or_a_missing_file_is_a_blocker",)),),
    },
    "L9": {
        "file": "tests/test_multi_proof_end_to_end.py",
        "tests": ("test_the_multi_proof_line_is_connected_end_to_end",),
        "also": (("tests/test_ledger_faces_carry_role_and_id.py",
                  ("test_the_evidence_rows_carry_a_role_and_the_run",)),),
    },
}


# ------------------------------------------------------------------ 判据本体

def _module_test_defs(tree: ast.Module) -> tuple[str, ...]:
    """模块级 `def test_*` 与 `async def test_*` 的名字（按源码顺序；不含类里的方法）。"""
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            out.append(node.name)
    return tuple(out)


def _read_defs(root: pathlib.Path, rel: str) -> tuple[tuple[str, ...], str]:
    """读一个判据文件的测试名清单；返回 `(名字, 读不成的原因)`（原因是空串 = 读成了）。

    读不成（文件不在 / 解析不了）单独一档：把它并进"0 个 test"会让"这一环没人守"
    与"这个文件坏了"长得一样，而处置完全不同（补判据 / 修文件）。
    """
    path = root / rel
    if not path.is_file():
        return (), f"文件不存在：{rel}"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        return (), f"读不出来：{rel}（{type(exc).__name__}: {exc}）"
    return _module_test_defs(tree), ""


def _entry_problems(root: pathlib.Path, link: str, rel: str,
                    wanted: tuple[str, ...]) -> list[str]:
    """一栏（一个文件 + 它欠的那几条 test）⇒ 问题清单（每条都点名这一环）。"""
    defs, why = _read_defs(root, rel)
    if why:
        return [f"{link}：{why} —— 这一环现在没有判据守着"]
    if not defs:
        return [f"{link}：{rel} 里一个模块级 `def test_*` 都没有 —— 这一环现在没有判据守着"]
    missing = [name for name in wanted if name not in defs]
    if missing:
        return [f"{link}：{rel} 里找不到 {missing}（那个文件里现有 {len(defs)} 条 test，"
                f"名字对不上也算这一环没人守）"]
    return []


def _check_links(table: dict, root: pathlib.Path) -> list[str]:
    """整张表逐栏核一遍 ⇒ 问题清单（空表 = 九环都有人守）。"""
    problems: list[str] = []
    if not table:
        return ["L 表是空的：九环一个都没登记 ⇒ 这一条判据本身空转"]
    for link in sorted(table):
        entry = table.get(link) or {}
        rel = str(entry.get("file") or "")
        wanted = tuple(entry.get("tests") or ())
        if not rel:
            problems.append(f"{link}：没有登记判据文件")
            continue
        if not wanted:
            problems.append(f"{link}：没有登记要核的 test 名（只给文件等于只核了一半）")
        problems += _entry_problems(root, link, rel, wanted)
        for extra in tuple(entry.get("also") or ()):
            extra_rel, extra_tests = str(extra[0] or ""), tuple(extra[1] or ())
            if not extra_rel or not extra_tests:
                problems.append(f"{link}：`also` 那一栏登记不全（{extra!r}）")
                continue
            problems += _entry_problems(root, link, extra_rel, extra_tests)
    return problems


def _coverage_problems(table: dict) -> list[str]:
    """九环齐不齐 ⇒ 缺环清单（反真空：漏一环等于那一环没人守）。"""
    have = set(table)
    missing = [link for link in EXPECTED_LINKS if link not in have]
    extra = sorted(have - set(EXPECTED_LINKS))
    problems = [f"表里缺 {link} —— 那一环等于没人守" for link in missing]
    problems += [f"表里多出 {link}（不在 L1–L9 里）—— 环号对不上，读数会错位"
                 for link in extra]
    return problems


def _reading(root: pathlib.Path, table: dict) -> dict:
    """这一条判据自己的读数（不是空转的证据：数了几环、几条 test、几个文件）。"""
    files = set()
    tests = 0
    for entry in table.values():
        rel = str((entry or {}).get("file") or "")
        if rel:
            files.add(rel)
        for name in tuple((entry or {}).get("tests") or ()):
            tests += 1
        for extra in tuple((entry or {}).get("also") or ()):
            if str(extra[0] or ""):
                files.add(str(extra[0]))
            tests += len(tuple(extra[1] or ()))
    return {"links": len(table), "files": len(files), "named_tests": tests,
            "root": str(root)}


# ============================================================ 三条正判据

def test_every_link_points_at_a_real_judge() -> None:
    """L1–L9 每一环的目标文件都在、且真的含登记的那几条 test。"""
    problems = _check_links(LINKS, REPO)
    reading = _reading(REPO, LINKS)
    assert reading["links"] == len(EXPECTED_LINKS), (
        f"表里只登记了 {reading['links']} 环（应为 {len(EXPECTED_LINKS)}）：{reading}")
    assert reading["named_tests"] >= len(EXPECTED_LINKS), (
        f"只核了 {reading['named_tests']} 条 test（应当每环至少一条）：{reading}")
    assert problems == [], (
        "有环没有判据守着（每条都点名了哪一环）：" + "；".join(problems))


def test_the_matrix_covers_every_link_from_one_to_nine() -> None:
    """表里不许漏 L1–L9 任何一环（反真空：漏一环等于那一环没人守）。"""
    problems = _coverage_problems(LINKS)
    assert set(EXPECTED_LINKS) <= set(LINKS), (
        "覆盖矩阵漏了环：" + "；".join(problems))
    assert problems == [], problems


# ============================================================ 反空转（内存里改坏）

def test_the_checker_is_not_inert_when_a_link_is_deleted(monkeypatch) -> None:
    """把表里的一个键删掉（内存里）⇒ 覆盖判据必须红，并点名那一环。"""
    monkeypatch.delitem(LINKS, "L4")
    problems = _coverage_problems(LINKS)
    assert problems, "删掉一环之后覆盖判据仍然绿 ⇒ 这条判据是空转的"
    assert any("L4" in one for one in problems), (
        f"删掉的是 L4，判据却没有点名它：{problems}")
    # 被删的那一环也确实不再有判据（`_check_links` 那一侧只剩九环里剩下的那些）。
    assert _check_links(LINKS, REPO) == [], "夹具不成立：剩下那八环本身应当都是好的"


def test_the_checker_is_not_inert_when_a_file_is_missing(monkeypatch) -> None:
    """把一个环指到不存在的文件（内存里）⇒ 存在性判据必须红，并点名那一环。"""
    monkeypatch.setitem(LINKS, "L6", {"file": "tests/这一份不存在.py",
                                      "tests": ("test_nothing",)})
    problems = _check_links(LINKS, REPO)
    assert problems, "指向不存在的文件之后判据仍然绿 ⇒ 这条判据是空转的"
    assert any(one.startswith("L6") and "不存在" in one for one in problems), problems


def test_the_checker_is_not_inert_when_a_file_has_no_tests(monkeypatch) -> None:
    """把一个环指到一个 0 test 的文件（内存里）⇒ 判据必须红，并点名那一环。

    夹具用 `tests/paperfixture.py`：它是真文件、真在 `tests/` 下，但不是判据
    （`pytest` 也不会收它，因为它不匹配 `test_*.py`）—— 正是"文件在、里面没有
    判据"这一档的现实形态。
    """
    monkeypatch.setitem(LINKS, "L1", {"file": "tests/paperfixture.py",
                                      "tests": ("test_the_second_proof_is_listed",)})
    problems = _check_links(LINKS, REPO)
    assert problems, "指向一个 0 test 的文件之后判据仍然绿 ⇒ 这条判据是空转的"
    assert any(one.startswith("L1") and "一个模块级" in one for one in problems), problems


def test_the_checker_is_not_inert_when_the_matrix_is_empty(monkeypatch) -> None:
    """整张表清空（内存里）⇒ 判据必须红：空的表不许读成"九环都有人守"。"""
    monkeypatch.setattr(sys.modules[__name__], "LINKS", {}, raising=True)
    problems = _check_links(LINKS, REPO)
    assert problems, "整张表清空之后判据仍然绿 ⇒ 这一条判据在空转"
    assert any("L 表是空的" in one for one in problems), problems
    coverage = _coverage_problems(LINKS)
    assert len(coverage) == len(EXPECTED_LINKS), (
        f"表空掉之后应当逐环点名（{len(EXPECTED_LINKS)} 条），实得 {coverage}")

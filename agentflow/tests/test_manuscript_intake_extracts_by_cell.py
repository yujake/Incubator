# -*- coding: utf-8 -*-
"""逐格提取的判据（T1：设计 `_design_T123.md` 第 2 节）。

## 这一份判据钉什么

1. 五个格各自的三态：`present` / `absent` / `unreadable`。缺节必须是 `absent`
   （`value=None`、`source` 没有行号与 sha），不许拿别的节或整份全文顶替（D4 口径；
   真机 `reports/e-num-*` 没有 `## 证明` 就是这么被读错的）；
2. `source` 是来源读数：节名 + 行号区间 + 那一格内容的 sha（`proof_text` 的 sha
   与签的 `proof_sha` 同一把尺：对正文文本、不 strip、不加换行）；
3. 依赖表的四列解析与 `kind` 稿头声明；空节是 `present`（空表 / 空正文是事实）；
4. 冲突矩阵（设计 2.6）与两条对拍不变量 I1 / I2（设计 2.4）；
5. 反真空：把 `absent` 判成 `present`（拿依赖段顶替证明段）必须让同一条判据红。

全部纯函数，不读写盘、不 import 任何既有模块。
"""
from __future__ import annotations

import hashlib

import pytest

from agentflow import manuscriptfamily as MF
from agentflow import manuscriptintake as MI

#: 一份五格齐全的稿（命题 / 证明 / 数值结果 / 依赖 + 稿头证据种类）。
FULL_TEXT = (
    "- 命题号：stmt:000001\n"
    "- 实验号：exp:000012\n"
    "- 证据种类：lemma\n"
    "\n"
    "## 命题\n"
    "命题正文：对所有实数 x，x^2 >= 0。\n"
    "\n"
    "## 证明\n"
    "证明第一行。\n"
    "证明第二行。\n"
    "\n"
    "## 数值结果\n"
    "- 方法：numeric\n"
    "- 结果：inconclusive\n"
    "\n"
    "## 依赖\n"
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n"
    "| 原话一 | stmt:000002 | 1 | 1 |\n"
)

#: 每一格 present 时应当读到的值（空节与坏表另有专门用例）。
EXPECTED_PRESENT: dict[str, object] = {
    "statement_full": "命题正文：对所有实数 x，x^2 >= 0。",
    "proof_text": "证明第一行。\n证明第二行。",
    "dependencies": [{"line": 19, "quote": "原话一", "stmt_id": "000002",
                      "step": "1", "path_group": 1}],
    "kind": "lemma",
    "numeric_evidence": {"experiment_id": "000012", "method": "numeric",
                         "result": "inconclusive",
                         "fields": {"方法": "numeric", "结果": "inconclusive"}},
}

#: 每个格的段标题（`source.section` 的期望；`kind` 是稿头那一行）。
EXPECTED_SECTION: dict[str, str] = {
    "statement_full": "## 命题",
    "proof_text": "## 证明",
    "dependencies": "## 依赖",
    "kind": "head: - 证据种类：",
    "numeric_evidence": "## 数值结果",
}


def without_cell(text: str, cell: str) -> str:
    """把某一格所在的节整段删掉（`kind` 删稿头那一行）；其余四格必须原样还在。"""
    if cell == "kind":
        return "\n".join(line for line in text.split("\n")
                         if "证据种类" not in line)
    heading = EXPECTED_SECTION[cell]
    out: list[str] = []
    skipping = False
    for line in text.split("\n"):
        if line.strip() == heading:
            skipping = True
            continue
        if skipping and line.strip().startswith("## "):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out)


def absent_violations(reading: dict) -> list[str]:
    """`absent` 的判据（返回人话；空列表 = 这一份缺节读数是对的）。

    反真空用：把缺节读成 present（`value` 里塞了别的节）时，这里必须报出来。
    """
    problems: list[str] = []
    source = reading.get("source") or {}
    if reading.get("outcome") != MI.EXTRACT_ABSENT:
        problems.append(f"outcome 是 {reading.get('outcome')!r}，不是 absent")
    if reading.get("value") is not None:
        problems.append(f"value 是 {reading.get('value')!r}，不是 None")
    if source.get("sha"):
        problems.append(f"source.sha 是 {source.get('sha')!r}，缺节不该有 sha")
    if source.get("lines"):
        problems.append(f"source.lines 是 {source.get('lines')!r}，缺节不该有行号")
    return problems


@pytest.mark.parametrize("cell", MI.INGEST_CELLS)
def test_present_reads_the_cell_and_its_source(cell: str) -> None:
    """present：值逐字/逐行对得上，source 带节名、行号区间与内容的 sha。"""
    reading = MI.extract_cells(FULL_TEXT, "f-proof", [cell])[cell]
    assert reading["outcome"] == MI.EXTRACT_PRESENT, reading
    assert reading["value"] == EXPECTED_PRESENT[cell], reading["value"]
    source = reading["source"]
    assert source["section"] == EXPECTED_SECTION[cell]
    assert source["lines"] and source["lines"][0] >= 1 and source["lines"][1] >= source["lines"][0]
    assert len(source["sha"]) == 64 and set(source["sha"]) <= set("0123456789abcdef")
    if cell in ("statement_full", "proof_text", "kind"):
        want = hashlib.sha256(str(reading["value"]).encode("utf-8")).hexdigest()
        assert source["sha"] == want
    assert reading["why"]


@pytest.mark.parametrize("cell", MI.INGEST_CELLS)
def test_absent_does_not_borrow_another_block(cell: str) -> None:
    """absent：缺这一节 ⇒ `value=None`、没有 sha / 行号；其余四格仍然 present。

    这是本文件的主判据（设计 1.2 / D4）：真机 `e-num-*` 没有 `## 证明`，旧读法会
    退到 `## 依赖`、再退到整份全文 —— 那让"没有证明"变成"别的块就是证明"。
    """
    text = without_cell(FULL_TEXT, cell)
    readings = MI.extract_cells(text, "f-proof", MI.INGEST_CELLS)
    reading = readings[cell]
    problems = absent_violations(reading)
    assert problems == [], problems
    assert reading["source"]["section"] == EXPECTED_SECTION[cell]
    for other in MI.INGEST_CELLS:
        if other == cell:
            continue
        assert readings[other]["outcome"] == MI.EXTRACT_PRESENT, (cell, other)
        assert readings[other]["value"] is not None


@pytest.mark.parametrize("cell", MI.INGEST_CELLS)
def test_unreadable_is_not_absent(cell: str) -> None:
    """unreadable：传进来的不是文本 ⇒ 说"没读到"，不折成"稿里没有这一节"。"""
    reading = MI.extract_cells(None, "f-proof", [cell])[cell]
    assert reading["outcome"] == MI.EXTRACT_UNREADABLE, reading
    assert reading["value"] is None
    assert reading["source"]["sha"] == ""
    assert reading["source"]["lines"] == []
    assert reading["why"]
    # bytes 同样不是文本（不猜编码）。
    assert MI.extract_cells(b"## \xe5\x91\xbd\xe9\xa2\x98\n", "f-proof",
                            [cell])[cell]["outcome"] == MI.EXTRACT_UNREADABLE


def test_the_absent_judge_rejects_a_present_reading() -> None:
    """反真空：把 absent 判成 present（拿别的节顶替）⇒ 同一条判据必须红。

    这是设计 2.11 b / D4 要求的反真空方向。喂的是"错读数"，不改源码、不动工作树。
    """
    mutant = {
        "outcome": MI.EXTRACT_PRESENT,
        "value": "| 原话一 | stmt:000002 | 1 | 1 |",
        "source": {"section": "## 依赖", "lines": [19, 21], "sha": "a" * 64},
        "why": "缺节时退到了 ## 依赖 那一节",
    }
    problems = absent_violations(mutant)
    assert problems, "把 absent 判成 present 时判据一声不吭 ⇒ 它是真空的"
    assert any("outcome" in one for one in problems)
    assert any("value" in one for one in problems)


def test_empty_proof_section_is_present_not_absent() -> None:
    """空节：`## 证明` 在、正文是空的 ⇒ present 且 value 是空串（不是 absent）。

    三态纪律：空正文与"没有这一节"是两件事；计划那一层再按"空正文不是一份证明"拒。
    """
    text = (
        "- 命题号：stmt:000001\n"
        "\n"
        "## 命题\n"
        "P\n"
        "\n"
        "## 证明\n"
        "\n"
        "## 依赖\n"
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n"
    )
    reading = MI.extract_cells(text, "f-proof", ["proof_text"])["proof_text"]
    assert reading["outcome"] == MI.EXTRACT_PRESENT, reading
    assert reading["value"] == ""
    plan = MI.plan_cells({"stmt_id": "000001", "statement_full": "P"},
                         {"proof_text": reading}, "refuse", family="f-proof")
    assert plan["ok"] is False
    assert plan["refused"] == MI.CODE_PROOF_EMPTY


def test_dependencies_parse_four_columns_and_report_problems() -> None:
    """依赖表：四列按表头取、顺序不限；坏表进 problems（不静默读成空表）。"""
    good = MI.extract_cells(FULL_TEXT, "f-proof", ["dependencies"])["dependencies"]
    assert good["outcome"] == MI.EXTRACT_PRESENT
    assert good["rows"] == 1 and good["problems"] == []
    row = good["value"][0]
    assert row["stmt_id"] == "000002" and row["path_group"] == 1
    assert row["quote"] == "原话一" and row["step"] == "1"

    swapped = FULL_TEXT.replace(
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |",
        "| 命题号（stmt:NNNNNN） | 引用（F 的原话） | 路径号（第几条证明） | 用在哪一步 |")
    swapped = swapped.replace("| 原话一 | stmt:000002 | 1 | 1 |",
                              "| stmt:000002 | 原话一 | 1 | 1 |")
    reading = MI.extract_cells(swapped, "f-proof", ["dependencies"])["dependencies"]
    assert reading["outcome"] == MI.EXTRACT_PRESENT
    assert reading["problems"] == []
    assert reading["value"][0]["quote"] == "原话一"
    assert reading["value"][0]["path_group"] == 1

    broken = FULL_TEXT.replace(
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |",
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |")
    broken = broken.replace("|---|---|---|---|", "|---|---|---|")
    bad = MI.extract_cells(broken, "f-proof", ["dependencies"])["dependencies"]
    assert bad["outcome"] == MI.EXTRACT_PRESENT
    assert bad["problems"], bad
    plan = MI.plan_cells({"stmt_id": "000001", "statement_full": "P"},
                         {"dependencies": bad}, "refuse", family="f-proof")
    assert plan["refused"] == MI.CODE_DEP_UNREADABLE


def test_extract_cells_rejects_unknown_cells_and_families() -> None:
    """闭集：未知格 / 未知族 / 空格集 / 把字符串当序列 ⇒ `ValueError`（不猜）。"""
    with pytest.raises(ValueError):
        MI.extract_cells(FULL_TEXT, "f-proof", ["vision"])
    with pytest.raises(ValueError):
        MI.extract_cells(FULL_TEXT, "x-proof", ["proof_text"])
    with pytest.raises(ValueError):
        MI.extract_cells(FULL_TEXT, "f-proof", [])
    with pytest.raises(ValueError):
        MI.extract_cells(FULL_TEXT, "f-proof", "proof_text")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        MI.plan_cells({}, {}, "ignore")


def test_numeric_evidence_carries_the_experiment_id_and_method() -> None:
    """`## 数值结果` + 稿头实验号：普通数值档的凭据按字段读出来（不读 experiments 表）。"""
    reading = MI.extract_cells(FULL_TEXT, "e-num", ["numeric_evidence"])["numeric_evidence"]
    assert reading["outcome"] == MI.EXTRACT_PRESENT
    assert reading["value"]["experiment_id"] == "000012"
    assert reading["value"]["method"] == "numeric"
    assert reading["value"]["result"] == "inconclusive"


# ---------------------------------------------------------------- 冲突矩阵


def plan_for(cells: list[str], row: dict | None, *, conflict: str = "refuse",
             family: str = "f-proof", proof_no: int = 1,
             text: str = FULL_TEXT) -> dict:
    """跑一遍提取 + 计划（判据只走被测的这两个纯函数）。"""
    got = MI.extract_cells(text, family, cells)
    return MI.plan_cells(row, got, conflict, family=family, proof_no=proof_no)


def test_register_fills_statement_full_and_apply_locks_it() -> None:
    """`statement_full`：新行可写；在册行只校验（相同 unchanged、不同 proposition_locked）。"""
    register = plan_for(["statement_full"], None)
    assert register["cells"]["statement_full"]["outcome"] == MI.PLAN_FILLED
    assert register["target_is_register"] is True

    same_row = {"stmt_id": "000001",
                "statement_full": EXPECTED_PRESENT["statement_full"]}
    same = plan_for(["statement_full"], same_row)
    assert same["cells"]["statement_full"]["outcome"] == MI.PLAN_UNCHANGED
    assert same["cells"]["statement_full"]["writable"] is False

    other_row = {"stmt_id": "000001", "statement_full": "另一条命题"}
    for conflict in MI.CONFLICTS:
        locked = plan_for(["statement_full"], other_row, conflict=conflict)
        assert locked["ok"] is False, conflict
        assert locked["refused"] == MI.CODE_STATEMENT_LOCKED, conflict


@pytest.mark.parametrize("case,conflict,outcome,code", [
    ("empty", "refuse", MI.PLAN_FILLED, ""),
    ("same", "refuse", MI.PLAN_UNCHANGED, ""),
    ("different", "refuse", MI.PLAN_REFUSED, MI.CODE_PROOF_EXISTS),
    ("different", "overwrite", MI.PLAN_FILLED, ""),
    ("different", "append", MI.PLAN_FILLED, ""),
    ("different", "keep", MI.PLAN_KEPT, ""),
])
def test_proof_text_conflict_readings(case: str, conflict: str, outcome: str,
                                      code: str) -> None:
    """`proof_text` 冲突四态（设计 2.6）：空 / 同 sha / 不同 sha × 四种策略。"""
    proof = EXPECTED_PRESENT["proof_text"]
    sha = hashlib.sha256(proof.encode("utf-8")).hexdigest()
    row = {"stmt_id": "000001", "statement_full": "P", "proof_text": "",
           "proof_sha256": ""}
    if case == "same":
        row.update(proof_text=proof, proof_sha256=sha)
    elif case == "different":
        row.update(proof_text="另一份正文", proof_sha256=hashlib.sha256(
            "另一份正文".encode("utf-8")).hexdigest())
    plan = plan_for(["proof_text"], row, conflict=conflict)
    cell = plan["cells"]["proof_text"]
    assert cell["outcome"] == outcome, (case, conflict, cell)
    assert cell["code"] == code, (case, conflict, cell)
    if outcome == MI.PLAN_REFUSED:
        assert plan["ok"] is False
        assert plan["diff"]["requested_not_filled"] == ["proof_text"]


def test_second_proof_needs_the_first_and_cannot_take_a_used_number() -> None:
    """`-p2`：没有 #p1 ⇒ `proof_no_gap`；#p2 已占不同正文 ⇒ `proof_no_taken`。"""
    gap = plan_for(["proof_text"], {"stmt_id": "000001", "statement_full": "P"},
                   proof_no=2)
    assert gap["refused"] == MI.CODE_PROOF_GAP

    row = {"stmt_id": "000001", "statement_full": "P", "proof_text": "第一份",
           "proof_sha256": hashlib.sha256("第一份".encode("utf-8")).hexdigest()}
    appended = plan_for(["proof_text"], row, proof_no=2)
    assert appended["cells"]["proof_text"]["outcome"] == MI.PLAN_FILLED

    taken_row = {**row, "proofs": [{"proof_no": 2, "proof_sha256": "b" * 64}]}
    taken = plan_for(["proof_text"], taken_row, proof_no=2)
    assert taken["refused"] == MI.CODE_PROOF_TAKEN


def test_kind_only_upgrades_with_a_sign_and_never_downgrades() -> None:
    """`kind`：台账更弱 ⇒ kept + `kind_not_upgraded_without_sign`；更强 ⇒ 拒降档。"""
    weak_row = {"stmt_id": "000001", "statement_full": "P", "kind": "conjecture"}
    upgrade = plan_for(["kind"], weak_row)
    cell = upgrade["cells"]["kind"]
    assert cell["outcome"] == MI.PLAN_KEPT
    assert cell["code"] == MI.CODE_KIND_UPGRADE_UNSIGNED
    assert upgrade["diff"]["requested_not_filled"] == ["kind"]

    strong_row = {"stmt_id": "000001", "statement_full": "P", "kind": "theorem"}
    downgrade = plan_for(["kind"], strong_row)
    assert downgrade["refused"] == MI.CODE_KIND_DOWNGRADE


def test_dependencies_append_are_idempotent_and_missing_section_is_judged() -> None:
    """依赖是集合：有表 ⇒ 追加；没表且正文没引用 ⇒ not_applicable；有引用 ⇒ 拒缺节。"""
    row = {"stmt_id": "000001", "statement_full": "P"}
    present = plan_for(["dependencies"], row)
    assert present["cells"]["dependencies"]["outcome"] == MI.PLAN_FILLED
    assert present["cells"]["dependencies"]["rows_written"] == 1

    no_deps = without_cell(FULL_TEXT, "dependencies")
    nothing = plan_for(["dependencies"], row, text=no_deps)
    assert nothing["cells"]["dependencies"]["outcome"] == MI.PLAN_NOT_APPLICABLE

    ref_text = no_deps.replace("证明第一行。", "由 stmt:000002 推出。")
    refused = plan_for(["dependencies"], row, text=ref_text)
    assert refused["refused"] == MI.CODE_DEP_MISSING


def test_numeric_evidence_is_unchanged_for_the_same_program() -> None:
    """数值凭据按程序比：同一程序 ⇒ unchanged；不同结果 ⇒ filled。"""
    same_row = {"stmt_id": "000001", "statement_full": "P",
                "numeric_evidence": {"code_path": "", "method": "numeric",
                                     "result": "inconclusive"}}
    same = plan_for(["numeric_evidence"], same_row, family="e-num")
    assert same["cells"]["numeric_evidence"]["outcome"] == MI.PLAN_UNCHANGED

    other_row = {**same_row, "numeric_evidence": {"code_path": "",
                                                  "method": "numeric",
                                                  "result": "supports"}}
    other = plan_for(["numeric_evidence"], other_row, family="e-num")
    assert other["cells"]["numeric_evidence"]["outcome"] == MI.PLAN_FILLED


def test_cells_outside_the_family_are_refused_and_legacy_is_read_only() -> None:
    """族收窄：`b-proof` 不收 `statement_full`；`e-num` 不收 `proof_text`；`legacy` 全拒。"""
    b_plan = plan_for(["statement_full"], None, family="b-proof")
    assert b_plan["cells"]["statement_full"]["code"] == MI.CODE_CELL_NOT_APPLICABLE

    e_plan = plan_for(["proof_text"], None, family="e-num")
    assert e_plan["cells"]["proof_text"]["code"] == MI.CODE_CELL_NOT_APPLICABLE

    legacy = plan_for(["proof_text", "dependencies"], None, family="legacy")
    assert legacy["ok"] is False
    for cell in ("proof_text", "dependencies"):
        assert legacy["cells"][cell]["outcome"] == MI.PLAN_REFUSED
        assert legacy["cells"][cell]["code"] == MI.CODE_LEGACY
        assert legacy["cells"][cell]["writable"] is False


def test_plan_keeps_the_two_reconciliation_invariants() -> None:
    """对拍不变量 I1 / I2（设计 2.4）：没有一格越权写，没填的格都要给理由。"""
    row = {"stmt_id": "000001", "statement_full": "P", "proof_text": "",
           "proof_sha256": "", "kind": "theorem"}
    plan = plan_for(["proof_text", "dependencies", "kind"], row, family="f-proof")
    assert plan["diff"]["filled_not_requested"] == []
    assert plan["diff"]["requested_not_filled"] == ["kind"]  # kind 降档被拒
    for cell in plan["diff"]["requested_not_filled"]:
        one = plan["cells"][cell]
        assert one["outcome"] in (MI.PLAN_REFUSED, MI.PLAN_KEPT, MI.PLAN_NOT_APPLICABLE)
        assert one["reason"]
    assert plan["derived_write"] == list(MF.derived_cells("f-proof"))


def test_the_intake_vocabulary_is_the_family_table_mirror() -> None:
    """两份新模块的词表不许各写各的：格、族、允许格、派生列逐格相等。"""
    assert MI.INGEST_CELLS == MF.INGEST_CELLS
    assert MI.FAMILY_NAMES == tuple(MF.FAMILIES)
    assert {family: MI._ALLOWED_BY_FAMILY[family] for family in MF.FAMILIES} == {
        family: MF.allowed_cells(family) for family in MF.FAMILIES}
    assert {family: MI._DERIVED_BY_FAMILY[family] for family in MF.FAMILIES} == {
        family: MF.derived_cells(family) for family in MF.FAMILIES}
    assert tuple(MI.KIND_RANK) == ("conjecture", "example", "proposition",
                                   "lemma", "corollary", "theorem")

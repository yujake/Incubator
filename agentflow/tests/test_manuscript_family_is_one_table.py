# -*- coding: utf-8 -*-
"""族判定表的判据（T2：设计 `_design_T123.md` 第 3 节）。

## 这一份判据钉什么

1. 四族 × 每个后缀 × 每个目录的往返：`relpath` 拼出来的名字必须被 `classify_manuscript` /
   `parse` 读回原值（改表忘改解析时当场红，设计 3.6 g）；
2. `legacy` 档：`-v2` 与 `notes/` 手稿形名字只读成历史档（可列出、可 preview、
   不可签、不可收录、`proof_no=0`），不读成 `-p2`、不读成正式族；
3. `bad_name` 与 `unrecognized` 是两件事（前者像手稿、号解析不出）；
4. 行为列逐格对拍：允许格 / 缺省格 / 派生列 / 签 / `evidence_kind` / `kind` 缺省 /
   出处；
5. 反真空：把 `-v2` 判成正式族（`tier=family, proof_no=2`）必须让同一条判据红。

全部纯函数，不读写盘、不 import 任何既有模块（被测对象只有 `manuscriptfamily`）。
"""
from __future__ import annotations

import re

import pytest

from agentflow import manuscriptfamily as MF

#: 四族写路径的名字用例：`(族, 号, 证明号)`。写侧只有一种形式 ——
#: 一个稿号 = 一份文件 = 一份证明，证明号不进名字，所以这里只有 1。
#: 盘上老名字 `…-p<N>.md` 已不再被认成手稿（`-pN` 退出解析侧）：本文件下面
#: `reports/f-proof-000000-p2.md` 那一格是 False 正控，B 拒写老名形态的读数见
#: `test_b_may_edit_its_own_unsigned_proof.py` 的 h 行。
NAME_CASES: tuple[tuple[str, str, int], ...] = (
    ("f-proof", "000000", 1),
    ("f-proof", "plan-0001", 1),
    ("b-proof", "000000", 1),
    ("e-proof", "000012", 1),
    ("e-num", "000012", 1),
)

#: 目录是身份的一部分：只有 `reports/` 是族；其余（含没有目录）读成历史档。
DIRECTORIES: tuple[str, ...] = ("reports", "notes", "out", "")

#: 行为列的唯一期望（设计 3.1.2 逐格抄下来；改表没改这里会红）。
BEHAVIOUR: dict[str, dict[str, object]] = {
    "f-proof": {
        "allowed": ("statement_full", "proof_text", "dependencies", "kind"),
        "default": ("statement_full", "proof_text", "dependencies"),
        "derived": ("bits", "proof_no", "proof_sha256", "kind", "proofs"),
        "needs_sign": True,
        "evidence_kind": "heuristic",
        "kind_default": "conjecture",
        "line_range_origin": "manuscript_path",
    },
    "b-proof": {
        "allowed": ("proof_text", "dependencies", "kind"),
        "default": ("proof_text", "dependencies"),
        "derived": ("bits", "proof_no", "proof_sha256", "kind", "proofs"),
        "needs_sign": True,
        "evidence_kind": "",
        "kind_default": "",
        "line_range_origin": "manuscript_path",
    },
    "e-proof": {
        "allowed": ("statement_full", "proof_text", "dependencies", "kind"),
        "default": ("statement_full", "proof_text", "dependencies"),
        "derived": ("bits", "proof_no", "proof_sha256", "kind", "proofs"),
        "needs_sign": True,
        "evidence_kind": "proof",
        "kind_default": "theorem",
        "line_range_origin": "experiment_id",
    },
    "e-num": {
        "allowed": ("statement_full", "numeric_evidence"),
        "default": ("statement_full", "numeric_evidence"),
        "derived": ("bits", "grade"),
        "needs_sign": False,
        "evidence_kind": "cross_check",
        "kind_default": "conjecture",
        "line_range_origin": "experiment_id",
    },
    "legacy": {
        "allowed": (), "default": (), "derived": (), "needs_sign": False,
        "evidence_kind": "", "kind_default": "", "line_range_origin": "",
    },
}


def rel_for(family: str, manuscript_id: str, proof_no: int, directory: str) -> str:
    """拼一份稿的路径（`reports/` 用被测的 `relpath`；别的目录只换目录那一段）。"""
    canonical = MF.relpath(family, manuscript_id, proof_no)
    if directory == MF.MANUSCRIPT_DIR:
        return canonical
    name = canonical.rsplit("/", 1)[-1]
    return f"{directory}/{name}" if directory else name


def legacy_violations(reading: dict, carrier: dict, allowed: tuple[str, ...]
                      ) -> list[str]:
    """历史档的判据（返回人话；空列表 = 这一份读法是对的）。

    反真空用：把 `-v2` 读成正式族（`tier=family, proof_no=2`）时，这里必须报出来。
    判据刻意把"签"与"允许格"也算进来：只查 `tier` 会漏掉"能签但收不进去"那种半档。
    """
    problems: list[str] = []
    if reading.get("tier") != MF.TIER_LEGACY:
        problems.append(f"tier 是 {reading.get('tier')!r}，不是 legacy")
    if reading.get("family") != MF.LEGACY_FAMILY:
        problems.append(f"family 是 {reading.get('family')!r}，不是 legacy")
    if int(reading.get("proof_no") or 0) != 0:
        problems.append(f"proof_no 是 {reading.get('proof_no')!r}，不是 0")
    if reading.get("code") != MF.CODE_LEGACY:
        problems.append(f"code 是 {reading.get('code')!r}，不是 {MF.CODE_LEGACY}")
    if carrier.get("ok"):
        problems.append("sign_carrier.ok 是 True（历史档不可签）")
    if carrier.get("code") != MF.CODE_LEGACY:
        problems.append(f"sign_carrier.code 是 {carrier.get('code')!r}")
    if tuple(allowed) != ():
        problems.append(f"allowed_cells 是 {tuple(allowed)!r}，历史档不可收录")
    return problems


def absent_violations_for_legacy_reading(reading: dict) -> list[str]:
    """把 `-v2` 读成正式族的那种读数 ⇒ 违规清单（只给反真空用）。"""
    return legacy_violations(reading, {"ok": True, "code": ""},
                             MF.allowed_cells(reading.get("family") or "legacy"))


@pytest.mark.parametrize("family,manuscript_id,proof_no,directory", [
    (family, manuscript_id, proof_no, directory)
    for family, manuscript_id, proof_no in NAME_CASES
    for directory in DIRECTORIES
])
def test_every_family_suffix_and_directory_round_trips(
        family: str, manuscript_id: str, proof_no: int, directory: str) -> None:
    """四族 × 后缀 × 目录的往返读数（设计 3.6 g；这是本文件的主判据）。

    `reports/` 下：`tier=family`、族 / 号 / 证明号逐字读回、签的载体按族判。
    别的目录：同一个名字读成 `legacy`（目录是身份的一部分），`proof_no=0`、
    规范名指回 `reports/` 那一份。
    """
    rel = rel_for(family, manuscript_id, proof_no, directory)
    reading = MF.classify_manuscript(rel)
    parsed = MF.parse(rel)
    carrier = MF.sign_carrier(rel)
    if directory == MF.MANUSCRIPT_DIR:
        assert reading["tier"] == MF.TIER_FAMILY, reading
        assert reading["family"] == family, reading
        assert reading["name_family"] == family
        assert reading["id"] == manuscript_id
        assert reading["proof_no"] == proof_no
        assert reading["code"] == ""
        assert parsed["tier"] == MF.TIER_FAMILY
        assert parsed["manuscript_id"] == manuscript_id
        assert parsed["proof_no"] == proof_no
        assert parsed["family"] == family
        assert parsed["is_family"] is True
        if family == "e-num":
            assert carrier["ok"] is False
            assert carrier["code"] == MF.CODE_NUMERIC_NOT_SIGN
        else:
            # 2026-11-10 业主裁定：`f-proof-plan-*` 是老盘上的只读兼容名，与数字名同等
            # （可签）。新稿不再写这种名字（`AgentF.manuscript_path` 只按稿号）。
            assert carrier["ok"] is True, carrier
            assert carrier["code"] == ""
    else:
        assert reading["tier"] == MF.TIER_LEGACY, reading
        assert reading["family"] == MF.LEGACY_FAMILY
        assert reading["name_family"] == family
        assert reading["id"] == manuscript_id
        assert reading["proof_no"] == 0
        assert reading["code"] == MF.CODE_LEGACY
        assert reading["canonical"] == MF.relpath(family, manuscript_id, proof_no)
        assert parsed["tier"] == MF.TIER_LEGACY
        assert parsed["proof_no"] == 0
        assert parsed["manuscript_id"] == manuscript_id
        assert carrier["ok"] is False
        assert carrier["code"] == MF.CODE_LEGACY
        assert MF.allowed_cells("legacy") == ()


def test_classify_name_ignores_the_directory() -> None:
    """fs 保留表只拿得到文件名：目录不参与，所以 `notes/b-proof-*` 仍是手稿形名字。

    为什么这与 `classify_manuscript` 不矛盾：`classify_manuscript` 判"这一份稿属于哪一族"（目录参与），
    `classify_name` 判"这个名字该不该被拒写"（只按名字）。两处都拒写 `notes/` 的
    手稿形名字，但前者读成 legacy、后者读成 family —— 这是两件事，不许折平。
    """
    assert MF.classify_manuscript("notes/b-proof-000003.md")["tier"] == MF.TIER_LEGACY
    assert MF.classify_name("notes/b-proof-000003.md")["tier"] == MF.TIER_FAMILY
    assert MF.classify_name("b-proof-000003.md")["tier"] == MF.TIER_FAMILY
    assert MF.classify_name("notes/f-proof-x.md")["tier"] == MF.TIER_BAD
    assert MF.classify_name("notes/A.md")["tier"] == MF.TIER_UNRECOGNIZED


@pytest.mark.parametrize("rel, version", [
    ("notes/b-proof-000003-v2.md", 2),
    ("reports/b-proof-000004-v2.md", 2),
    ("notes/f-proof-000001-v7.md", 7),
    ("out/e-proof-000012-v1.md", 1),
])
def test_legacy_versions_are_a_read_not_a_family(rel: str, version: int) -> None:
    """`-vN` 只读成历史档：`proof_no=0`、不可签、不可收录；规范名是建议，不是读数。

    `-v2` 尤其不许读成 `-p2`：那会把一份未审、且已知有缺陷的稿变成正式证明
    （设计 1.2 第 3 条）。这里的正控与反真空共用 `legacy_violations`。
    """
    reading = MF.classify_manuscript(rel)
    carrier = MF.sign_carrier(rel)
    problems = legacy_violations(reading, carrier, MF.allowed_cells("legacy"))
    assert problems == [], problems
    expected_canonical = (f"reports/{reading['name_family']}-"
                          f"{reading['id']}.md")
    assert reading["canonical"] == expected_canonical, reading
    # 三处读口各自独立地拒它（单改正则不够：vsigns 内部曾有两把尺打架）。
    assert MF.parse(rel)["proof_no"] == 0
    assert MF.parse(rel)["tier"] == MF.TIER_LEGACY
    assert MF.is_sign_carrier(rel) is False


def test_the_legacy_judge_rejects_a_formal_reading_of_v2() -> None:
    """反真空：把 `-v2` 判成正式族（`tier=family, proof_no=2`）⇒ 同一条判据必须红。

    这是设计 3.6 c 要求的反真空方向。做法是把"错读数"喂给正控用的同一个判据函数；
    不做修改源码那种一次性实验（那会污染工作树）。
    """
    reading = MF.classify_manuscript("notes/b-proof-000003-v2.md")
    mutant = {**reading, "tier": MF.TIER_FAMILY, "family": "b-proof",
              "proof_no": 2, "code": ""}
    problems = absent_violations_for_legacy_reading(mutant)
    assert problems, "把 -v2 读成正式族时判据一声不吭 ⇒ 它是真空的"
    assert any("tier" in one for one in problems)
    assert any("proof_no" in one for one in problems)


@pytest.mark.parametrize("rel", [
    "reports/f-proof-abc.md",
    "reports/f-proof-x.md",
    "notes/f-proof-x.md",
    "reports/f-proof-123.md",
    "reports/f-proof-1234567.md",
    "reports/b-proof-000003-p0.md",
    "reports/b-proof-000003-pabc.md",
    "reports/b-proof-000003-p01.md",
    "reports/e-num-000012-p2.md",
    "reports/b-proof-plan-0001.md",
])
def test_bad_names_are_neither_family_nor_legacy(rel: str) -> None:
    """像手稿、号解析不出 ⇒ `bad_name`（受控拒那一档），不是历史档、也不是族。"""
    reading = MF.classify_manuscript(rel)
    assert reading["tier"] == MF.TIER_BAD, reading
    assert reading["family"] == ""
    assert reading["name_family"] != ""
    assert reading["proof_no"] == 0
    assert reading["code"] == MF.CODE_BAD
    assert MF.classify_name(rel)["tier"] == MF.TIER_BAD
    assert MF.sign_carrier(rel)["ok"] is False
    assert MF.sign_carrier(rel)["code"] == MF.CODE_BAD
    assert MF.parse(rel)["checked"] is False


@pytest.mark.parametrize("rel", [
    "RESEARCH.md",
    "notes/A.md",
    "notes/b-notes.md",
    "lit-r-0001.md",
    "reports/RESEARCH.md",
    "proof.md",
])
def test_unrecognized_is_not_a_manuscript(rel: str) -> None:
    """不是手稿族的名字 ⇒ `unrecognized`（不列进手稿清单、也不拒写普通笔记）。"""
    reading = MF.classify_manuscript(rel)
    assert reading["tier"] == MF.TIER_UNRECOGNIZED, reading
    assert reading["family"] == ""
    assert reading["name_family"] == ""
    assert reading["proof_no"] == 0
    assert reading["canonical"] == ""
    assert MF.classify_name(rel)["tier"] == MF.TIER_UNRECOGNIZED
    assert MF.sign_carrier(rel)["ok"] is False
    assert MF.sign_carrier(rel)["code"] == MF.CODE_NOT_MANUSCRIPT


def test_sign_carrier_is_exactly_three_families_in_reports() -> None:
    """签的载体 = `f-proof` / `b-proof` / `e-proof` 且 `reports/`（设计 3.2 第 3 处）。

    清单式读数：每一格都是显式的（不是从别的判定里推出来的）。
    """
    table = {
        "reports/f-proof-000000.md": True,
        "reports/f-proof-000000-p2.md": False,
        "reports/b-proof-000000.md": True,
        "reports/e-proof-000012.md": True,
        "reports/f-proof-plan-0001.md": True,
        "reports/e-num-000012.md": False,
        "notes/f-proof-000000.md": False,
        "notes/b-proof-000000.md": False,
        "notes/e-proof-000012.md": False,
        "notes/b-proof-000003-v2.md": False,
        "reports/f-proof-abc.md": False,
        "RESEARCH.md": False,
    }
    for rel, want in table.items():
        assert MF.is_sign_carrier(rel) is want, (rel, MF.sign_carrier(rel))


@pytest.mark.parametrize("family", list(BEHAVIOUR))
def test_behaviour_columns_come_from_the_one_table(family: str) -> None:
    """行为列逐格对拍（设计 3.1.2）：允许格 / 缺省格 / 派生列 / 签 / 证据种类 / 出处。"""
    want = BEHAVIOUR[family]
    assert MF.allowed_cells(family) == want["allowed"]
    assert MF.default_cells(family) == want["default"]
    assert MF.derived_cells(family) == want["derived"]
    assert MF.needs_sign(family) is want["needs_sign"]
    assert MF.evidence_kind(family) == want["evidence_kind"]
    assert MF.kind_default(family) == want["kind_default"]
    assert MF.line_range_origin(family) == want["line_range_origin"]
    assert set(MF.allowed_cells(family)) <= set(MF.INGEST_CELLS)


def test_the_five_entries_and_the_closed_cell_set_are_one_table() -> None:
    """表本体：五档（四族 + legacy 读档）、四个前缀互不相同、格是闭集。

    反真空：`FAMILIES` 少一族或多一族都算表漂了；签不要的那一族（e-num）必须真的
    在表里且 `allowed_cells` 不含 `proof_text`（设计 3.6 d）。
    """
    assert tuple(MF.FAMILIES) == (*MF.FAMILY_ORDER, MF.LEGACY_FAMILY)
    assert len(MF.FAMILY_ORDER) == 4
    prefixes = [MF.prefix_of(one) for one in MF.FAMILY_ORDER]
    assert len(set(prefixes)) == 4
    assert all(one.endswith("-") and one for one in prefixes)
    assert set(MF.INGEST_CELLS) == {
        "statement_full", "proof_text", "dependencies", "kind", "numeric_evidence"}
    assert "proof_text" not in MF.allowed_cells("e-num")
    # 派生列与请求格可以重叠（`kind` 是设计里刻意两边都列的），但其余派生列不是格。
    outside = {one for family in MF.FAMILY_ORDER
               for one in (set(MF.derived_cells(family)) - set(MF.INGEST_CELLS))}
    assert outside == {"bits", "proof_no", "proof_sha256", "proofs", "grade"}
    for family in MF.FAMILY_ORDER:
        assert (set(MF.derived_cells(family)) - set(MF.INGEST_CELLS)) <= outside


@pytest.mark.parametrize("family,manuscript_id,proof_no", NAME_CASES)
def test_relpath_is_the_only_spelling_and_round_trips(
        family: str, manuscript_id: str, proof_no: int) -> None:
    """拼名 → 解析回原值（设计 3.6 g）：`relpath` 是唯一拼法。"""
    rel = MF.relpath(family, manuscript_id, proof_no)
    assert rel.startswith("reports/") and rel.endswith(".md")
    parsed = MF.parse(rel)
    assert parsed["tier"] == MF.TIER_FAMILY
    assert parsed["family"] == family
    assert parsed["manuscript_id"] == manuscript_id
    assert parsed["proof_no"] == proof_no
    assert parsed["canonical"] == ""
    reading = MF.classify_manuscript(rel)
    assert reading["tier"] == MF.TIER_FAMILY
    assert reading["name_family"] == family


@pytest.mark.parametrize("call", [
    lambda: MF.relpath("nope", "000000", 1),
    lambda: MF.relpath("legacy", "000000", 1),
    lambda: MF.relpath("b-proof", "000000", 0),
    lambda: MF.relpath("b-proof", "000000", "x"),
    lambda: MF.relpath("b-proof", "abc", 1),
    lambda: MF.relpath("b-proof", "000000/../x", 1),
    lambda: MF.relpath("b-proof", "plan-0001", 1),
    lambda: MF.relpath("e-num", "000012", 2),
    lambda: MF.allowed_cells("nope"),
])
def test_relpath_and_accessors_fail_closed(call) -> None:
    """未知族 / 号形不对 / 证明号不合法 ⇒ `ValueError`（不猜一个名字出来）。"""
    with pytest.raises(ValueError):
        call()


def test_relpath_refuses_a_proof_no_suffix() -> None:
    """写路径给 `proof_no >= 2` ⇒ 受控拒绝（产出侧不拼 `-pN`）。

    为什么是拒绝而不是静默压成 1：压成 1 会让"以为在写第 2 份"的调用方覆盖第 1 份
    的稿，而那在盘上表现为"第 1 份变了、第 2 份不存在"，没有任何地方会报。
    """
    for family, manuscript_id in (("f-proof", "000000"), ("b-proof", "000041"),
                                  ("e-proof", "000012"), ("e-num", "000012")):
        with pytest.raises(ValueError):
            MF.relpath(family, manuscript_id, 2)
        assert re.search(r"-p\d+\.md$", MF.relpath(family, manuscript_id)) is None


def test_parse_keeps_the_legacy_compatibility_readings() -> None:
    """`parse` 兼容旧 `vsigns.parse_manuscript_name` 的键，并多给 `tier` / `is_family`。

    - `e-num`：`family == "e-num"`（设计 3.6 d；旧读法是 `family=False`）；
    - `f-proof-abc`：`is_family=True, checked=False`（旧读法的 `family=True` 那一档）。
    """
    keys = {"checked", "family", "is_family", "manuscript_id", "proof_no", "code",
            "reason", "name", "tier", "canonical"}
    parsed = MF.parse("reports/e-num-000012.md")
    assert keys <= set(parsed)
    assert parsed["family"] == "e-num"
    assert parsed["tier"] == MF.TIER_FAMILY
    bad = MF.parse("reports/f-proof-abc.md")
    assert bad["is_family"] is True
    assert bad["checked"] is False
    assert bad["code"] == MF.CODE_BAD

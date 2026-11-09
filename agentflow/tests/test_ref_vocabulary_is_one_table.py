# -*- coding: utf-8 -*-
"""B1 判据：`refvocab` 是一张表、三态读得开、legacy 各形态读得通且不被判非法。

这一组钉四件事（对应设计 `_design_D9_D10.md` §3）：

1. 一张表：每个命名空间都能往返（`parse_ref` 的 `namespace`/`target` 与写法一致），
   且台账行那一组与 `schema.CITATION_PREFIXES` 指向同一张表（模块本身不 import schema，
   一致性在这里钉）；
2. 三态：`ok` / `missing` / `unchecked` 分得开 —— 表不在是 `unchecked`，不是 `missing`；
3. legacy 读成旧形、不拒：裸号、`verifications/...#v-...`、`reports/...#V签`、
   `notes/...`、`documents:`、`conjecture:` 各一条；把任何一条判成非法，反真空那条红；
4. 不猜：一个裸稿号命中多个族 ⇒ `ambiguous`，不是"随便挑一个"。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import refvocab as RV
from agentflow import schema as S

#: 台账行：`(前缀, 表名, 主键列)`。与 `REF_NAMESPACES` 的断言分开写，
#: 是为了让"表里少一行/多一行"在这里就红，而不是靠调用方现场发现。
TABLE_CASES: tuple[tuple[str, str, str], ...] = (
    ("stmt", "statements", "stmt_id"),
    ("exp", "experiments", "experiment_id"),
    ("lit", "literature", "lit_id"),
    ("rel", "relations", "relation_id"),
    ("q", "research_questions", "question_id"),
    ("c", "conjectures", "conjecture_id"),
    ("doc", "documents", "doc_id"),
    ("eval", "eval_results", "eval_id"),
)

#: legacy 写法各一条（裸号 / 验证路径 / pending / reports / notes / 别名 / 裸 mss）。
LEGACY_SAMPLES: tuple[str, ...] = (
    "000007",
    "verifications/000001.jsonl#v-000003",
    "verifications/pending/" + "a" * 64 + ".jsonl#u-000001",
    "reports/f-proof-000001.md",
    "reports/f-proof-000001.md#V签",
    "reports\\f-proof-000001.md",
    "notes/f-proof-000001.md",
    "documents:000001",
    "conjecture:000001",
    "mss:000001",
)


def _table(root: pathlib.Path, name: str, rows: list) -> None:
    """写一张 `data/<name>.json`（形状与 store 的快照同形：`{schema_version, rows}`）。"""
    path = root / "data" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": rows},
                               ensure_ascii=False), encoding="utf-8")


def _jsonl(root: pathlib.Path, rel: str, rows: list) -> None:
    """写一份追加式 JSONL。"""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(one, ensure_ascii=False) for one in rows) + "\n",
                    encoding="utf-8")


def _file(root: pathlib.Path, rel: str) -> None:
    """造一份空文件（内容不重要；`mss:` 只判在不在盘上）。"""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 稿\n", encoding="utf-8")


@pytest.fixture()
def world(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个最小工作区：八张台账各一行 + 一份交接 + 一份验证 + 一份稿。

    刻意只放 `reports/f-proof-000001.md` 一份稿：这样 `mss:000001` 的"唯一族"路径
    可测；多族歧义另开一条（`test_a_bare_manuscript_id_with_two_families_is_ambiguous`）。
    """
    for prefix, table, field in TABLE_CASES:
        _table(tmp_path, table, [{field: "000001"}])
    _jsonl(tmp_path, "manuscripts/handoffs.jsonl", [{"id": "000007", "refs": []}])
    _jsonl(tmp_path, "verifications/000001.jsonl", [{"verification_id": "v-000003"}])
    _jsonl(tmp_path, "verifications/pending/" + "a" * 64 + ".jsonl",
           [{"verification_id": "u-000001"}])
    _file(tmp_path, "reports/f-proof-000001.md")
    return tmp_path


def test_every_table_namespace_round_trips(world: pathlib.Path) -> None:
    """正控：八张台账各一条往返 —— 写法 → 解析 → 在盘上找到。"""
    for prefix, table, field in TABLE_CASES:
        parsed = RV.parse_ref(f"{prefix}:000001")
        assert parsed["ok"], (prefix, parsed)
        assert parsed["namespace"] == prefix, (prefix, parsed)
        assert parsed["target"] == "000001", (prefix, parsed)
        assert parsed["kind"] == RV.KIND_TABLE, (prefix, parsed)
        assert parsed["legacy"] is False, (prefix, parsed)
        got = RV.ref_problem(f"{prefix}:000001", root=str(world))
        assert got["state"] == RV.STATE_OK, (prefix, got)
        assert got["checked"] is True and got["found"] is True, (prefix, got)
        assert RV.is_problem(got) is False, (prefix, got)


def test_table_namespaces_point_at_the_same_tables_as_citations() -> None:
    """一张表：台账行那一组必须与 `schema.CITATION_PREFIXES` 指向同一张表。

    模块本身不 import schema（B1 零依赖）；一致性在这里钉。`q:`/`c:` 不在 citations
    里（它们只活在手稿引用与 `OBJECT_REFS`），但必须在 `refvocab` 里。
    """
    got = {one.namespace: one.target for one in RV.REF_NAMESPACES
           if one.kind == RV.KIND_TABLE}
    for prefix, table in S.CITATION_PREFIXES.items():
        assert got.get(prefix) == table, (prefix, got.get(prefix), table)
    assert {"q", "c"} <= set(got), got
    assert set(got) == {prefix for prefix, _table, _field in TABLE_CASES}, got


def test_the_namespace_table_has_no_duplicate_keys() -> None:
    """反真空：词表键唯一、每行的 `namespace` 与键一致（否则"查表"会静默取到错行）。"""
    keys = [one.namespace for one in RV.REF_NAMESPACES]
    assert len(keys) == len(set(keys)), keys
    for key in keys:
        assert RV.REF_SPECS[key].namespace == key, (key, RV.REF_SPECS[key])


def test_a_manu_ref_and_a_bare_id(world: pathlib.Path) -> None:
    """`manu:` 与裸号：裸号是 legacy（历史上裸号一直指前序交接），读成 `manu:`。"""
    parsed = RV.parse_ref("manu:000007")
    assert parsed["ok"] and parsed["namespace"] == "manu" and not parsed["legacy"], parsed
    assert RV.ref_problem("manu:000007", root=str(world))["state"] == RV.STATE_OK

    legacy = RV.parse_ref("000007")
    assert legacy["legacy"] is True, legacy
    assert legacy["canonical"] == "manu:000007", legacy
    got = RV.ref_problem("000007", root=str(world))
    assert got["state"] == RV.STATE_LEGACY_OK, got
    assert got["found"] is True and RV.is_legacy(got) is True, got


def test_a_verification_path_is_read_as_verif(world: pathlib.Path) -> None:
    """真机那一形：`verifications/000001.jsonl#v-000003` ⇒ `verif:000001#v-000003`。

    这是 D10 的直接回归：旧写法必须读得通（legacy），不许再判"前序手稿不在盘上"。
    """
    parsed = RV.parse_ref("verifications/000001.jsonl#v-000003")
    assert parsed["ok"] is True, parsed
    assert parsed["namespace"] == "verif", parsed
    assert parsed["target"] == "000001", parsed
    assert parsed["anchor"] == "v-000003", parsed
    assert parsed["legacy"] is True, parsed
    assert parsed["canonical"] == "verif:000001#v-000003", parsed
    got = RV.ref_problem("verifications/000001.jsonl#v-000003", root=str(world))
    assert got["state"] == RV.STATE_LEGACY_OK, got
    assert got["found"] is True, got
    assert RV.is_problem(got) is False, got


def test_a_pending_verification_path_is_read_as_verif_pending(world: pathlib.Path) -> None:
    """pending 台账那一形：`verifications/pending/<sha>.jsonl#u-000001` ⇒ `verif:pending/...`。"""
    raw = "verifications/pending/" + "a" * 64 + ".jsonl#u-000001"
    parsed = RV.parse_ref(raw)
    assert parsed["ok"] is True, parsed
    assert parsed["canonical"] == "verif:pending/" + "a" * 64 + "#u-000001", parsed
    got = RV.ref_problem(raw, root=str(world))
    assert got["state"] == RV.STATE_LEGACY_OK, got
    assert got["found"] is True, got


def test_a_manuscript_path_is_read_as_mss(world: pathlib.Path) -> None:
    """`reports/…md` 与 `reports/…md#V签` 都读成 `mss:<family>-<id>`（legacy）。"""
    for raw in ("reports/f-proof-000001.md", "reports/f-proof-000001.md#V签"):
        parsed = RV.parse_ref(raw)
        assert parsed["ok"] is True, (raw, parsed)
        assert parsed["namespace"] == "mss", (raw, parsed)
        assert parsed["canonical"] == "mss:f-proof-000001", (raw, parsed)
        assert parsed["legacy"] is True, (raw, parsed)
        got = RV.ref_problem(raw, root=str(world))
        assert got["state"] == RV.STATE_LEGACY_OK, (raw, got)
        assert got["found"] is True, (raw, got)


def test_a_notes_path_is_read_as_mss_but_says_the_directory_is_not_canonical(
        world: pathlib.Path) -> None:
    """`notes/…md` 也读得通（历史稿在那里），但读数里要说明它不是规范目录。"""
    parsed = RV.parse_ref("notes/f-proof-000001.md")
    assert parsed["ok"] is True and parsed["legacy"] is True, parsed
    assert parsed["canonical"] == "mss:f-proof-000001", parsed
    assert "notes/" in parsed["why"], parsed
    got = RV.ref_problem("notes/f-proof-000001.md", root=str(world))
    assert got["state"] == RV.STATE_LEGACY_OK, got


def test_the_old_alias_prefixes_are_mapped(world: pathlib.Path) -> None:
    """`documents:` / `conjecture:` 是历史别名，映射到 `doc:` / `c:`，不是未知前缀。"""
    doc = RV.parse_ref("documents:000001")
    assert doc["ok"] and doc["canonical"] == "doc:000001" and doc["legacy"], doc
    assert RV.ref_problem("documents:000001", root=str(world))["state"] == RV.STATE_LEGACY_OK

    one = RV.parse_ref("conjecture:000001")
    assert one["ok"] and one["canonical"] == "c:000001" and one["legacy"], one
    assert RV.ref_problem("conjecture:000001", root=str(world))["state"] == RV.STATE_LEGACY_OK


def test_a_bare_mss_id_uses_the_unique_family(world: pathlib.Path) -> None:
    """裸 `mss:000001` 只命中一个族 ⇒ 读得通；多族时另测（ambiguous）。"""
    parsed = RV.parse_ref("mss:000001")
    assert parsed["ok"] and parsed["legacy"] is True, parsed
    got = RV.ref_problem("mss:000001", root=str(world))
    assert got["state"] == RV.STATE_LEGACY_OK, got
    assert got["found"] is True, got


def test_a_bare_manuscript_id_with_two_families_is_ambiguous(tmp_path: pathlib.Path) -> None:
    """一个裸稿号命中两个族 ⇒ `ambiguous`（不猜），而写全族的同一条引用照旧 ok。"""
    _file(tmp_path, "reports/f-proof-000001.md")
    _file(tmp_path, "reports/b-proof-000001.md")
    got = RV.ref_problem("mss:000001", root=str(tmp_path))
    assert got["state"] == RV.STATE_AMBIGUOUS, got
    assert got["code"] == RV.CODE_AMBIGUOUS, got
    assert RV.is_problem(got) is True, got
    assert RV.ref_problem("mss:f-proof-000001", root=str(tmp_path))["state"] == RV.STATE_OK


def test_a_four_digit_id_finds_a_six_digit_row(world: pathlib.Path) -> None:
    """宽度归一：`stmt:0001` 能找到台账里的 `000001`（历史 4 位引用不再被误判）。"""
    parsed = RV.parse_ref("stmt:0001")
    assert parsed["ok"] and parsed["canonical"] == "stmt:000001", parsed
    got = RV.ref_problem("stmt:0001", root=str(world))
    assert got["state"] == RV.STATE_OK, got
    assert got["found"] is True, got


def test_a_six_digit_ref_finds_a_four_digit_handoff(tmp_path: pathlib.Path) -> None:
    """反过来的宽度：旧账本里手稿号是 4 位（`0002`），新引用写 6 位也要找得到。"""
    _jsonl(tmp_path, "manuscripts/handoffs.jsonl", [{"id": "0002"}])
    for raw in ("manu:000002", "0002", "manu:0002"):
        got = RV.ref_problem(raw, root=str(tmp_path))
        assert got["state"] in (RV.STATE_OK, RV.STATE_LEGACY_OK), (raw, got)
        assert got["found"] is True, (raw, got)


def test_a_four_digit_verification_anchor_finds_a_six_digit_row(world: pathlib.Path) -> None:
    """`#v-3` / `#v-0003` / `#v-000003` 都能命中台账里的 `v-000003`。"""
    for anchor in ("v-3", "v-0003", "v-000003"):
        got = RV.ref_problem(f"verif:000001#{anchor}", root=str(world))
        assert got["state"] == RV.STATE_OK, (anchor, got)


def test_a_missing_target_is_missing_not_unchecked(world: pathlib.Path) -> None:
    """查过了、确实不在 ⇒ `missing`（`checked=True, found=False`），不是 `unchecked`。"""
    cases = (
        "stmt:000099",
        "manu:000099",
        "verif:000001#v-000099",
        "mss:f-proof-000099",
    )
    for raw in cases:
        got = RV.ref_problem(raw, root=str(world))
        assert got["state"] == RV.STATE_MISSING, (raw, got)
        assert got["checked"] is True and got["found"] is False, (raw, got)
        assert got["code"] == RV.CODE_TARGET_MISSING, (raw, got)
        assert RV.is_problem(got) is True, (raw, got)


def test_an_unreadable_workspace_is_unchecked_not_missing(tmp_path: pathlib.Path) -> None:
    """没有工作区根 / 表文件不在 / 读不出来 ⇒ `unchecked`（读不到 ≠ 没有）。"""
    assert RV.ref_problem("stmt:000001")["state"] == RV.STATE_UNCHECKED
    assert RV.ref_problem("stmt:000001", root=str(tmp_path))["state"] == RV.STATE_UNCHECKED
    assert RV.ref_problem("stmt:000001", root=str(tmp_path))["checked"] is False

    broken = tmp_path / "data" / "statements.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{ not json", encoding="utf-8")
    got = RV.ref_problem("stmt:000001", root=str(tmp_path))
    assert got["state"] == RV.STATE_UNCHECKED, got
    assert got["code"] == RV.CODE_UNCHECKED, got
    assert RV.is_problem(got) is False, got


def test_bad_rows_do_not_become_missing(tmp_path: pathlib.Path) -> None:
    """表里有坏行、目标又没找到 ⇒ 只能报 `unchecked`（坏行可能正是那一行）。"""
    _table(tmp_path, "statements", [{"stmt_id": "000001"}, "不是对象"])
    got = RV.ref_problem("stmt:000099", root=str(tmp_path))
    assert got["state"] == RV.STATE_UNCHECKED, got
    assert "坏" not in got["why"] and "不是对象" in got["why"], got


def test_a_bad_handoff_line_does_not_become_missing(tmp_path: pathlib.Path) -> None:
    """账本有读不出来的行、目标又没找到 ⇒ `unchecked`，不是 `missing`。"""
    path = tmp_path / "manuscripts" / "handoffs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json\n", encoding="utf-8")
    got = RV.ref_problem("manu:000007", root=str(tmp_path))
    assert got["state"] == RV.STATE_UNCHECKED, got


def test_a_path_like_reference_that_cannot_be_parsed_is_bad(tmp_path: pathlib.Path) -> None:
    """像路径、认不出族/号 ⇒ `bad`（点名 `mss:` 的写法），不是 `unchecked`。"""
    got = RV.ref_problem("reports/F-lemma42-sign.md", root=str(tmp_path))
    assert got["state"] == RV.STATE_BAD, got
    assert got["code"] == RV.CODE_BAD_ADDRESS, got
    assert "mss:" in got["why"], got


def test_unknown_namespace_and_bad_address_are_bad(world: pathlib.Path) -> None:
    """未知前缀 / 号形不对 / 缺锚 ⇒ `bad`；`why` 里给出正确写法。"""
    for raw, code in (
        ("z:0000", RV.CODE_UNKNOWN_NAMESPACE),
        ("stmt:abc", RV.CODE_BAD_ADDRESS),
        ("verif:000001", RV.CODE_BAD_ADDRESS),
        ("verif:000001#x-1", RV.CODE_BAD_ADDRESS),
        ("mss:b-proof-abc", RV.CODE_BAD_ADDRESS),
    ):
        got = RV.ref_problem(raw, root=str(world))
        assert got["state"] == RV.STATE_BAD, (raw, got)
        assert got["code"] == code, (raw, got)
        assert got["checked"] is False and got["found"] is None, (raw, got)
        assert RV.is_problem(got) is True, (raw, got)


def test_empty_text_is_not_a_problem() -> None:
    """空串是"没有引用"，不是"引用坏了"（调用方通常先过滤空串）。"""
    got = RV.ref_problem("", root="/no/such/workspace")
    assert got["state"] == RV.STATE_OK, got
    assert got["checked"] is False and got["found"] is None, got
    assert RV.is_problem(got) is False, got


def test_legacy_forms_are_all_parsed_and_never_illegal(world: pathlib.Path) -> None:
    """反真空：把任何一条 legacy 判成非法 ⇒ 红。

    这一条是"读成旧形、不拒"的机器判据：`LEGACY_SAMPLES` 里每一条都必须
    `ok=True` + `legacy=True`，且能读出规范形（不是原样返回）。
    """
    for raw in LEGACY_SAMPLES:
        parsed = RV.parse_ref(raw)
        assert parsed["ok"] is True, (raw, parsed)
        assert parsed["legacy"] is True, (raw, parsed)
        assert parsed["canonical"], (raw, parsed)
        # 裸 `mss:000001` 的规范形就是它自己（族要等存在性判据按"唯一族"裁定）；
        # 其余 legacy 必须真的被改写成规范形，而不是原样返回。
        if raw != "mss:000001":
            assert parsed["canonical"] != raw, (raw, parsed)


def test_canonical_forms_are_not_marked_legacy(world: pathlib.Path) -> None:
    """正控的另一半：规范形不许被误标成 legacy（否则 legacy 计数永远不收敛）。"""
    for raw in ("stmt:000001", "manu:000007", "verif:000001#v-000003",
                "mss:f-proof-000001"):
        parsed = RV.parse_ref(raw)
        assert parsed["ok"] is True, (raw, parsed)
        assert parsed["legacy"] is False, (raw, parsed)


def test_explain_says_unchecked_is_not_missing(world: pathlib.Path) -> None:
    """回执文案：`unchecked` 必须明说"没查成、不是不存在"（三态不许读成同一个样子）。"""
    unchecked = RV.ref_problem("stmt:000001", root="")
    assert "没查成" in RV.explain(unchecked) and "不是" in RV.explain(unchecked)
    legacy = RV.ref_problem("verifications/000001.jsonl#v-000003", root=str(world))
    assert "legacy" in RV.explain(legacy), RV.explain(legacy)


def test_cache_can_be_shared_across_calls(world: pathlib.Path) -> None:
    """缓存是可选加速，不是语义：同一份 cache 复用两次，结论不变。"""
    cache: dict = {}
    first = RV.ref_problem("stmt:000001", root=str(world), cache=cache)
    second = RV.ref_problem("stmt:000001", root=str(world), cache=cache)
    assert first == second, (first, second)

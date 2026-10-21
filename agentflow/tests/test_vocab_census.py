"""`G-26` 第一步：死取值普查的判据（正控 + 反真空负控）。

这一版只查"死取值"（词表里有、`src/` 里找不到产出点）。反向（漏词表）没实现，
由工具自己在输出里逐字声明 —— 所以这里也断言"它真的声明了"：一个不声明自己缺口的
普查器，读者会把"没报"读成"没有"。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools" / "vocab_census.py"


def _load():
    spec = importlib.util.spec_from_file_location("_vocab_census_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


V = _load()

_SCHEMA = '''
KIND_KINDS = ("produced", "never_produced")
OTHER_SCOPES = ("produced",)
THING_OUTCOMES = ("produced",)
'''


def _fake_root(tmp_path: Path, *, producer_body: str = 'X = "produced"\n' * 60) -> Path:
    """造一个最小世界：`src/agentflow/schema.py` + 一个产出模块。

    产出正文重复 60 行是为了过 `MIN_PRODUCER_LINES` 那道反真空下限 ——
    下限本身也有用例（见 `test_too_few_producers_is_unknown_not_clean`）。

    `claimanatomy.py` 也必须写出来：`draft/28` §168 的 `R-37` 把定义点从
    "只有 `schema.py`" 扩成 `VOCAB_DEFINITION_FILES` 里那几个，少一个就是"没查成"
    （那一格本身有负控）。它带一张自己的词表 `EXTRA_KINDS`，取值用 `produced`
    与产出模块对齐 —— 这样它不会给"哪些取值是死的"那几条断言添噪音。
    """
    (tmp_path / "src" / "agentflow").mkdir(parents=True)
    (tmp_path / "src" / "agentflow" / "schema.py").write_text(_SCHEMA, encoding="utf-8")
    (tmp_path / "src" / "agentflow" / "claimanatomy.py").write_text(
        'EXTRA_KINDS = ("produced",)\n', encoding="utf-8")
    (tmp_path / "src" / "agentflow" / "mod.py").write_text(producer_body, encoding="utf-8")
    return tmp_path


def test_a_defined_but_unproduced_value_is_reported(tmp_path: Path) -> None:
    """正控：登记了 `never_produced`、而 `src/` 里没有产出点 ⇒ 必须报出来。"""
    result = V.census(_fake_root(tmp_path))
    assert result["checked"] is True, result
    assert result["dead"] == {"KIND_KINDS": ["never_produced"]}, result["dead"]


def test_the_definition_site_does_not_count_as_a_producer(tmp_path: Path) -> None:
    """负控（这条普查最典型的假绿）：不排除定义点的话，每个取值都会"命中它自己"。"""
    root = _fake_root(tmp_path, producer_body="Y = 1\n" * 60)
    result = V.census(root)
    assert result["checked"] is True, result
    assert sorted(result["dead"]["KIND_KINDS"]) == ["never_produced", "produced"], result["dead"]


def test_too_few_vocabularies_is_unknown_not_clean(tmp_path: Path) -> None:
    """反真空：词表数低于下限 ⇒ 没查成（2），不是"没有死取值"。"""
    (tmp_path / "src" / "agentflow").mkdir(parents=True)
    (tmp_path / "src" / "agentflow" / "schema.py").write_text("NOT_A_VOCAB = 1\n", encoding="utf-8")
    # 定义文件必须齐（`R-37`）：少了它走的是"读不到定义文件"那一格，与本用例测的
    # "词表数低于下限"是两回事 —— 夹具要喂到被测那一格上。
    (tmp_path / "src" / "agentflow" / "claimanatomy.py").write_text("NOT_A_VOCAB = 1\n",
                                                                   encoding="utf-8")
    (tmp_path / "src" / "agentflow" / "mod.py").write_text("Z = 1\n" * 60, encoding="utf-8")
    result = V.census(tmp_path)
    assert result["checked"] is False, result
    assert "词表" in result["reason"], result


def test_too_few_producers_is_unknown_not_clean(tmp_path: Path) -> None:
    """反真空：产出点低于下限 ⇒ 没查成（2）。"""
    result = V.census(_fake_root(tmp_path, producer_body="W = 1\n"))
    assert result["checked"] is False, result
    assert "产出点" in result["reason"], result


def test_missing_schema_is_unknown_not_clean(tmp_path: Path) -> None:
    """反真空：读不到 `schema.py` ⇒ 没查成（2）。"""
    result = V.census(tmp_path)
    assert result["checked"] is False, result


def test_the_real_repo_reports_the_registered_dead_values() -> None:
    """对着真仓库：`P-22`/`P-23` 点名的那些值必须在 `reserved` 栏，且不在 `unclaimed` 栏。

    判据刻意不是"什么都不报"：那会变成真空通过（普查器一坏也全绿）。它也不是"仍在死的清单里"就够 —— 两栏的语义完全不同：`reserved` = 无产出但已登记（有理由）；`unclaimed` = 无产出且无人认领。
    一个已登记为预留的取值跑到 `unclaimed` 栏里去，与"它彻底消失"同属"审计不再看得见它"的失败形态。

    ## `E-10`（裁定 (b)，2026-09-27）：`FINDING_KINDS.quote_mismatch` 已经删掉

    它此前是本条点名的那批"已登记为预留"里的一个。裁定 (b) 的处置是删掉假承诺（它对一条做不到的承诺做预留）⇒ 它既不该出现在 `reserved`，也不该出现在 `unclaimed`，更不该还在词表里。
    本条因此多一条断言：那个取值必须已经不在词表里（"删掉了"本身要有机器判据，否则"登记表撤了一条"与"词表删了一个值"分不开）。
    """
    result = V.census(REPO)
    assert result["checked"] is True, result
    # 普查看得见它是死取值、且已登记 ⇒ 必须在 `reserved` 栏。
    for vocab, value in (("DOC_KINDS", "reproduction_report"),
                         ("DEP_KINDS", "proposition"),
                         ("DEP_KINDS", "prior_art")):
        assert value in result["reserved"].get(vocab, []), (vocab, value, result["reserved"])
        assert value not in result["unclaimed"].get(vocab, []), (vocab, value, result["unclaimed"])
    # `E-10` 裁定 (b)：`FINDING_KINDS` 里没有这个取值了 —— 词表、登记表、
    # 三栏输出里都不许再有它（"删掉了"要有判据，不能靠人记得）。
    _removed = "quote" + "_mismatch"
    assert _removed not in V._vocab_constants(REPO / "src" / "agentflow" / "schema.py").get(
        "FINDING_KINDS", []), "`E-10` 裁定 (b) 删掉的那个取值又回到 FINDING_KINDS 里了"
    for column in ("dead", "reserved", "unclaimed", "registered_not_dead"):
        values = V.census(REPO)[column].get("FINDING_KINDS", [])
        assert _removed not in values, (column, values)
    assert (("FINDING_KINDS", _removed)) not in V.RESERVED_VALUES, (
        "词表值已经删了，登记表里却还留着它 —— 那是一条『登记已过期』")
    # "同形不同义"的三条：普查看不见它们是死取值（字面量在别的命名空间里命中），
    # 所以它们落在 `registered_not_dead` 里 —— 但必须照样打印，不许静默。
    for vocab, value in (("DOC_KINDS", "survey"), ("DEP_KINDS", "lemma"),
                         ("DEP_KINDS", "dataset")):
        assert value in result["registered_not_dead"].get(vocab, []), (vocab, value, result["registered_not_dead"])
        assert value not in result["unclaimed"].get(vocab, []), (vocab, value, result["unclaimed"])
    # 两栏的合计必须仍然等于"死取值"总数 —— 分栏不许把取值漏掉一个，
    # 也不许无中生有（`reserved + unclaimed == dead` 是分栏正确性的恒等式）。
    assert result["reserved_total"] + result["unclaimed_total"] == result["dead_total"], result
    # 每一条预留都必须有理由：登记表的价值全在理由上，没有理由的登记是静默豁免。
    for vocab, value in (("DOC_KINDS", "reproduction_report"), ("DOC_KINDS", "survey")):
        why = result["reserved_reasons"].get(f"{vocab}.{value}", "")
        assert why.strip(), (vocab, value)


def test_unregistering_a_reserved_value_moves_it_to_unclaimed(monkeypatch) -> None:
    """负控（`P-22`/`P-23` 要求的那一条）：摘掉一条预留 ⇒ 它必须从 `reserved` 挪到 `unclaimed`。

    这条用例证明的是"判据可判"：两栏不是把同一个集合换个名字打印两遍 ——
    `RESERVED_VALUES` 真的决定一个取值落在哪一栏。没有它，
    上面那条正控在"登记表被清空"时也会绿（因为那时 `reserved` 是空字典，
    `in []` 为假……但它会被 `reserved_total` 那条抓住一部分）。所以这条负控是必需的。

    对象是 `DOC_KINDS.reproduction_report`（`E-10` 之后 `FINDING_KINDS` 那条登记
    已经随词表值一起删掉，拿它当夹具会失去对象）。
    """
    key = ("DOC_KINDS", "reproduction_report")
    value = key[1]
    assert key in V.RESERVED_VALUES, "登记表里没有这一条 ⇒ 本负控失去对象"
    before = V.census(REPO)
    assert value in before["reserved"]["DOC_KINDS"]

    monkeypatch.delitem(V.RESERVED_VALUES, key)
    after = V.census(REPO)
    assert value not in after["reserved"].get("DOC_KINDS", [])
    assert value in after["unclaimed"].get("DOC_KINDS", []), after["unclaimed"]

    monkeypatch.undo()
    restored = V.census(REPO)
    assert value in restored["reserved"]["DOC_KINDS"]
    assert value not in restored["unclaimed"].get("DOC_KINDS", [])


def test_the_unimplemented_direction_is_declared(tmp_path: Path) -> None:
    """反向（漏词表）没实现 ⇒ 必须在结果里显式声明，否则"没报"会被读成"没有"。"""
    result = V.census(_fake_root(tmp_path))
    assert "漏词表" in result["known_gap"], result
    assert "未实现" in result["known_gap"], result


@pytest.mark.parametrize("code,expect", [(0, False), (1, True)])
def test_exit_code_reflects_whether_dead_values_exist(tmp_path: Path, code: int, expect: bool) -> None:
    """退出码三态：有死取值 ⇒ 1；没查成 ⇒ 2（这一条只钉"有/无"那一半）。"""
    root = _fake_root(tmp_path) if code == 1 else _fake_root(tmp_path, producer_body='X = "produced"\nY = "never_produced"\n' * 30)
    assert V.main(["--root", str(root)]) == code

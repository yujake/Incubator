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

    ## 2026-10-22：`DEP_KINDS.proposition` 从 `reserved` 挪进 `registered_not_dead`

    旧期望错在哪：它把 `proposition` 钉在 `reserved`（"普查看得见它是死取值"）。
    普查判"死"看的是字面量有没有出现在 `src/` —— 这一批新增的
    `agent_b/register_statement.py:855` 的 `_CONTEXT_EDGE_KINDS`（严格规矩 B 的
    "上下文定理认哪几种 kind"）里就有 `"proposition"` 这个字面量。那一处是读侧
    （拿它去比 `Dependency.kind`），不是产出点，但普查的字面量判据分不出读写 ⇒
    它按 `lemma` 那条同样的口径落进 `registered_not_dead`（栏一附），
    仍然打印、仍然带理由，只是不再算"死取值"。
    所以本条现在按「两栏都算登记过」来判（`reserved` 或 `registered_not_dead` 之一），
    这不是放宽判据：`unclaimed` 那一条（真正要红的那一档）一条都没放松。

    ## 2026-11-13（业主裁定「清死代码」）：`reproduction_report` / `自证` / `未决` 已删

    三条都 0 行 / 无读点 / 无写入口 ⇒ 词表值与登记表条目一起删。`reserved` 栏的非真空
    当时改由「仍然死的两条」钉住（`CONJECTURE_FORMS.existential`、
    `CONJECTURE_STATUSES.known_in_literature`），条数写死到 2（不是删掉这条断言）。
    （2026-11-20 之后 `known_in_literature` 因读侧字面量挪进栏一附，见下一节；这里的 2 是
    2026-11-13 那天的历史计数。）
    为什么不是 3：并行路当晚落的 `conjectureledger.py:112`（`return "testing"`）让
    `testing` 从死取值里出来了 —— 那是一条真的产出点，属于好消息；本批的硬计数按
    当次 census 钉在 2，两路合流后按同一条口径复跑再钉一次（判据形态不变）。删掉的三个取值另有
    一条反向断言：它们不许在任何栏、任何词表、任何登记里留痕（与 `E-10` 同一条纪律）。

    ## 2026-11-20：`CONJECTURE_STATUSES.known_in_literature` 挪进栏一附（读侧字面量）

    旧期望把它和 `CONJECTURE_FORMS.existential` 一起钉在 `reserved`（"今天仍然死的两条"）。
    这一批 `src/agentflow/webui/readers.py` 新增了猜想状态的中文投影
    `CONJECTURE_STATUS_WORDS`（九个状态逐一给中文；`known_in_literature` 那一格是
    "文献已知"）—— 那是展示标签，不是产出点，但普查按带引号的字面量判"有没有产出"，
    分不出"写进数据"与"翻译给页面看" ⇒ 它按 `proposition` / `prior_art` 同样的口径
    落进 `registered_not_dead`（栏一附：照样打印、照样带登记理由，没有被静默豁免）。
    所以 `reserved` 的非真空改由 `CONJECTURE_FORMS.existential` 一条钉住；
    `known_in_literature` 挪进下面那圈"两栏都算登记过"的判据，`unclaimed` 那条不许松。

    ## 2026-10-26：`DEP_KINDS.prior_art` 按同一条口径从 `reserved` 挪进 `registered_not_dead`

    与上面 `proposition` 完全同形：`depsection.py` 的 `dep_kind_of()`（F 手稿依赖段
    读稿时把 `statements.kind` 翻成 `DEP_KINDS` 的那张表）里逐字有 `"prior_art"`，
    它是读侧映射、不是产出点，但普查的字面量判据分不出读写 ⇒ 它落进
    `registered_not_dead`（仍然打印、仍然带理由，`reserved_reasons` 里那条登记也还在）。
    处置同上：把它挪到下面那圈按"两栏都算登记过"判，`unclaimed` 那一刀不放松。
    """
    result = V.census(REPO)
    assert result["checked"] is True, result
    # 普查看得见它们是死取值、且已登记 ⇒ 必须在 `reserved` 栏。
    # 条数写死到 1：删掉/挪走一条预留之后，剩下的必须一条不少地仍然在栏一里
    # （业主口径：删的是其中一档，就改「剩下的都出现」并把数量写死，不是删掉断言）。
    _still_dead = (("CONJECTURE_FORMS", "existential"),)
    for vocab, value in _still_dead:
        assert value in result["reserved"].get(vocab, []), (vocab, value, result["reserved"])
        assert value not in result["unclaimed"].get(vocab, []), (vocab, value, result["unclaimed"])
    assert result["reserved_total"] == len(_still_dead), result["reserved"]
    # 已登记、而普查今天看不见它是死取值的那几条（同形不同义 / 读侧字面量）⇒
    # 落 `registered_not_dead`（栏一附），照样打印、照样带理由 —— 不许静默。见下面那一圈。
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
    # 2026-11-13 删掉的三个 C 值：同一套反向断言。
    _retired = (("DOC_KINDS", "reproduction_report"),
                ("CLAIM_SOURCE_KINDS", "自证"),
                ("CLAIM_SOURCE_KINDS", "未决"),
                ("DEP_KINDS", "dataset"))
    _vocabs = V._vocab_constants(REPO / "src" / "agentflow" / "schema.py")
    for vocab, value in _retired:
        assert value not in _vocabs.get(vocab, []), (vocab, value, _vocabs.get(vocab))
        assert (vocab, value) not in V.RESERVED_VALUES, (
            f"词表值 {vocab}.{value} 已经删了，登记表里却还留着它 —— 那是一条『登记已过期』")
        for column in ("dead", "reserved", "unclaimed", "registered_not_dead"):
            assert value not in result[column].get(vocab, []), (column, vocab, value, result[column])
    # "同形不同义 / 读侧字面量"的六条：普查看不见它们是死取值（字面量在别的命名空间
    # 或读侧命中），所以它们落在 `registered_not_dead` 里 —— 但必须照样打印，不许静默。
    for vocab, value in (("DOC_KINDS", "survey"), ("DEP_KINDS", "lemma"),
                         ("DEP_KINDS", "proposition"),
                         ("DEP_KINDS", "prior_art"),
                         # 2026-11-20：webui 的中文投影表（读侧展示标签，不是产出点）
                         ("CONJECTURE_STATUSES", "known_in_literature")):
        assert value in result["registered_not_dead"].get(vocab, []), (vocab, value, result["registered_not_dead"])
        assert value not in result["unclaimed"].get(vocab, []), (vocab, value, result["unclaimed"])
        assert value not in result["unclaimed"].get(vocab, []), (vocab, value, result["unclaimed"])
    # 两栏的合计必须仍然等于"死取值"总数 —— 分栏不许把取值漏掉一个，
    # 也不许无中生有（`reserved + unclaimed == dead` 是分栏正确性的恒等式）。
    assert result["reserved_total"] + result["unclaimed_total"] == result["dead_total"], result
    # 每一条预留都必须有理由：登记表的价值全在理由上，没有理由的登记是静默豁免。
    for vocab, value in (("CONJECTURE_STATUSES", "known_in_literature"), ("DOC_KINDS", "survey")):
        why = result["reserved_reasons"].get(f"{vocab}.{value}", "")
        assert why.strip(), (vocab, value)


def test_unregistering_a_reserved_value_moves_it_to_unclaimed(monkeypatch) -> None:
    """负控（`P-22`/`P-23` 要求的那一条）：摘掉一条预留 ⇒ 它必须从 `reserved` 挪到 `unclaimed`。

    这条用例证明的是"判据可判"：两栏不是把同一个集合换个名字打印两遍 ——
    `RESERVED_VALUES` 真的决定一个取值落在哪一栏。没有它，
    上面那条正控在"登记表被清空"时也会绿（因为那时 `reserved` 是空字典，
    `in []` 为假……但它会被 `reserved_total` 那条抓住一部分）。所以这条负控是必需的。

    对象是 `CONJECTURE_FORMS.existential`（`known_in_literature` 2026-11-20 起因 webui 的
    中文投影表落进栏一附，`reserved` 里不再有它；`reproduction_report` 已于 2026-11-13
    删掉，拿它当夹具会失去对象；`testing` 当晚因并行路新增产出点而离开死取值，也不能用）。
    """
    key = ("CONJECTURE_FORMS", "existential")
    vocab, value = key
    assert key in V.RESERVED_VALUES, "登记表里没有这一条 ⇒ 本负控失去对象"
    before = V.census(REPO)
    assert value in before["reserved"].get(vocab, [])

    monkeypatch.delitem(V.RESERVED_VALUES, key)
    after = V.census(REPO)
    assert value not in after["reserved"].get(vocab, [])
    assert value in after["unclaimed"].get(vocab, []), after["unclaimed"]

    monkeypatch.undo()
    restored = V.census(REPO)
    assert value in restored["reserved"].get(vocab, [])
    assert value not in restored["unclaimed"].get(vocab, [])


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

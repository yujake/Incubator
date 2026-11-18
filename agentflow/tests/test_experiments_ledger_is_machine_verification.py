# -*- coding: utf-8 -*-
"""`experiments` 的口径是「机器核验与实验台账」：E 写计算类，L 写 formal（Lean 核验）。

业主裁定（逐字）：「不新增，直接改口径」。L 的形式化行不新开一张表，而是落进
`experiments` —— 于是这张表同时收两类账：

- E 的 `numeric` / `symbolic` / `exhaustive_search`（数值与穷举实验）；
- L 的 `formal`（Lean 核验）。

三条判据（a 钉口径 / b 反真空 / c 结构未变）：

| # | 判据 | 改前红是什么形态 |
|---|---|---|
| a | 从 `schema.EXPERIMENT_METHODS` 的说明与 `Experiment` 的说明里读得到「机器核验」与「formal（Lean 核验）」两句；缺任一 ⇒ 红 | 改前那两处只写「实验方法（E）」「E 的一次实验记录」⇒ 两句都读不到 |
| b | 把这两句从同一份 schema 源码里删掉 ⇒ a 必须红（两句各删一次，各自点名缺的那一句） | a 的绿若来自别处（或判据根本没扫到），删掉之后它照样绿 |
| c | 结构一个字节没动：`Experiment` 的字段元组、`EXPERIMENT_METHODS` 的值、以及 `method="formal"` 的既有判据（formal 行不要求穷尽三件套；非 formal 行要）与基线逐字相等 | 顺手改了字段 / 词表 / 校验逻辑 ⇒ 这里红 |

c 的基线是 2026-11-04 改口径之前量到的值（不是"从代码里抄一遍再和代码比"——
那样永远相等，等于没判据）。
"""
from __future__ import annotations

import dataclasses
import pathlib

import pytest

from agentflow import schema as S

#: c 的基线：`Experiment` 的字段元组（2026-11-04 改口径之前实测，逐字）。
#: 2026-11-19（BATCH5 K11）：加两格行级归属 `owner_task` / `owner_instance`（在
#: `created_at` 之前）。两格都有默认值（空串 = 加列之前的老行）⇒ 老行逐字读得进来，
#: `SCHEMA_VERSION` 不抬（与 `Literature.pages` 同一先例）。方法词表与本条要守的
#: 「结构未变」那一半（除这两格）逐字未动。
_BASELINE_EXPERIMENT_FIELDS = (
    "experiment_id", "claim", "claim_key", "method", "evidence_kind", "result",
    "negation_kind", "code_path", "code_hash", "params", "observations",
    "exit_code", "runtime_sec", "artifact_paths", "counterexample",
    "verifier_output", "verifier_subject_key", "certificate", "search_bound",
    "for_question_id", "notes", "status", "voided_by", "voided_at",
    "void_reason", "void_reason_code", "voided_code_to",
    "owner_task", "owner_instance", "created_at",
    "created_by",
)

#: c 的基线：`EXPERIMENT_METHODS` 的值（2026-11-04 改口径之前实测，逐字）。
_BASELINE_EXPERIMENT_METHODS = ("numeric", "symbolic", "exhaustive_search", "formal")


# ---------------------------------------------------------------- 共用的读法


def _schema_source() -> str:
    """`schema.py` 的源码全文（说明块是注释，不在 `inspect` 的可见面上）。"""
    path = pathlib.Path(S.__file__)
    assert path.is_file(), f"schema 模块的落点不在盘上：{path}"
    return path.read_text(encoding="utf-8")


def _methods_note(source: str) -> str:
    """`EXPERIMENT_METHODS = (` 紧邻上方那一段连续注释 —— 词表自己的说明。"""
    lines = source.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("EXPERIMENT_METHODS"):
            j = i - 1
            block: list[str] = []
            while j >= 0 and lines[j].lstrip().startswith("#"):
                block.append(lines[j])
                j -= 1
            assert block, (
                "`EXPERIMENT_METHODS` 上方一段连续注释都没有 ⇒ 这个词表没有说明可读")
            return "\n".join(reversed(block))
    raise AssertionError("schema.py 里找不到 `EXPERIMENT_METHODS = (` 那一行")


def _experiment_note(source: str) -> str:
    """`class Experiment:` 到它的 `validate` 之前那一段 —— 表的说明（docstring ＋ 字段注释）。"""
    start = source.find("class Experiment:")
    assert start >= 0, "schema.py 里找不到 `class Experiment:`"
    end = source.find("\n    def validate(", start)
    assert end > start, "找不到 `Experiment.validate` —— 读法失效，不是口径通过"
    return source[start:end]


def _wording_problems(source: str) -> list[str]:
    """判据 a 的本体：表说明里要有「机器核验」，词表说明里要有「formal（Lean 核验）」。"""
    problems: list[str] = []
    if "机器核验" not in _experiment_note(source):
        problems.append(
            "`Experiment` 的说明里读不到「机器核验」—— 这张表的口径没有落到代码旁白里")
    if "formal（Lean 核验）" not in _methods_note(source):
        problems.append(
            "`EXPERIMENT_METHODS` 的说明里读不到「formal（Lean 核验）」—— "
            "L 的那一类没有在词表上被点名")
    return problems


def _without_lines_containing(source: str, needle: str) -> str:
    """删掉所有含 `needle` 的行（反真空用：模拟"这两句没写"）。"""
    lines = source.splitlines()
    kept = [line for line in lines if needle not in line]
    assert len(kept) < len(lines), f"反真空失效：schema 源码里一行含 {needle!r} 的都没有"
    return "\n".join(kept)


# ---------------------------------------------------------------- a 钉口径


def test_a_the_two_sentences_are_readable_from_the_schema() -> None:
    """a：`EXPERIMENT_METHODS` 与 `Experiment` 的说明里读得到那两句口径。

    改前红：那两处只写「实验方法（E）」「E 的一次实验记录」⇒
    既没有「机器核验」，也没有「formal（Lean 核验）」。
    """
    problems = _wording_problems(_schema_source())
    assert not problems, "；".join(problems)


# ---------------------------------------------------------------- b 反真空


def test_b_deleting_either_sentence_turns_a_red() -> None:
    """b 反真空：两句各删一次 ⇒ a 的本体必须红，并点名缺的那一句。

    它守的是 a 不是"恒绿"：a 的绿若来自别处、或读法根本没扫到那两处说明，
    删掉之后同一份判据照样绿 —— 那时 a 证明不了任何事。
    """
    source = _schema_source()
    assert not _wording_problems(source), "反真空的前提：今天 a 是绿的"

    without_machine = _wording_problems(_without_lines_containing(source, "机器核验"))
    assert any("机器核验" in p for p in without_machine), (
        f"删掉「机器核验」那一句之后 a 没有点名它：{without_machine}")

    without_formal = _wording_problems(_without_lines_containing(source, "formal（Lean 核验）"))
    assert any("formal（Lean 核验）" in p for p in without_formal), (
        f"删掉「formal（Lean 核验）」那一句之后 a 没有点名它：{without_formal}")


# ---------------------------------------------------------------- c 结构未变


def test_c_the_structure_is_byte_for_byte_unchanged() -> None:
    """c：字段元组 / 词表值 / `method="formal"` 的既有判据都与基线逐字相等。

    改口径只许动说明文字：`EXPERIMENT_METHODS` 的值、`Experiment` 的字段、
    以及"formal 行不要求穷尽三件套而计算类 proof 行要求"这条既有校验，
    一个字节都不许跟着变。
    """
    fields_now = tuple(f.name for f in dataclasses.fields(S.Experiment))
    assert fields_now == _BASELINE_EXPERIMENT_FIELDS, (
        f"`Experiment` 的字段集变了：多了 {set(fields_now) - set(_BASELINE_EXPERIMENT_FIELDS)}；"
        f"少了 {set(_BASELINE_EXPERIMENT_FIELDS) - set(fields_now)}")
    assert tuple(S.EXPERIMENT_METHODS) == _BASELINE_EXPERIMENT_METHODS, (
        f"`EXPERIMENT_METHODS` 的值变了：{tuple(S.EXPERIMENT_METHODS)!r}")
    assert "formal" in S.EXPERIMENT_METHODS, (
        "`formal` 不在词表里 ⇒ L 的形式化行没有可落的取值")

    # 既有判据（`Experiment.validate` 的硬约束 1）：formal 行不需要穷尽三件套就能拿 proof。
    formal_row = S.Experiment(
        experiment_id="0001", claim="一条真命题", claim_key="stmt:0001",
        method="formal", evidence_kind="proof", result="supports",
        negation_kind="not_proved", verifier_output="Lean: no errors",
        verifier_subject_key="stmt:0001")
    formal_row.validate()

    # 同一个形状换成计算类 ⇒ 必须仍被拒（改口径不许把这一条放宽）。
    calculation_row = S.Experiment(
        experiment_id="0002", claim="一条真命题", claim_key="stmt:0002",
        method="numeric", evidence_kind="proof", result="supports",
        negation_kind="not_proved")
    with pytest.raises(ValueError, match="不得声称 evidence_kind='proof'"):
        calculation_row.validate()

    # 词表外的取值仍被拒（词表本身不是"什么都收"）。
    bogus_row = S.Experiment(
        experiment_id="0003", claim="一条真命题", claim_key="stmt:0003",
        method="not_a_method", result="inconclusive", negation_kind="not_proved")
    with pytest.raises(ValueError, match="method 必须是"):
        bogus_row.validate()

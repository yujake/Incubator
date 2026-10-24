# -*- coding: utf-8 -*-
"""判据（D-54 ③）：形态检测 —— 同一趟里"把一条定理拆成多条独立命题"要报得出来。

## 这条判据守什么

业主 2026-10-24 在 `projects/sylow3` 看到：同一条 Sylow 定理被登记成三条独立命题
（`000000` 正规化子路线 / `000003` Wielandt 路线 / `000006` S3 归纳路线），
`proof_no` 恒 1、`path_group` 只有一组 ⇒ 多证明机制一次都没被触发，C 也就追不出
"不同的证明路径"。判重（`secretary` 的 `_same_proposition_candidate`）只比"同一次登记的
正文是否相同"，对"三条不同表述其实是同一条定理"这种形态没有任何读数。

`statementfission.suspected_splits` 补的就是这个读数：同一批命题里两两判同一性
（只读复用 `propositionkey.same_proposition`），命中成簇，簇内没有任何一条有
`proof_no > 1` ⇒ 报一条读数并点名是哪几条。只报不拦门（D-54 明确"先让它可见"）。

## 判据七条

1. ⑥ 正控：三条同一命题的不同写法、都只有 canonical 那一份证明 ⇒ 报一簇、点名三条；
2. 负控（⑦）：两条确实不同的命题 ⇒ 不报；
3. 有第 2 份证明 ⇒ 不报（进 `multi`，它不是拆命题，是多证明机制被用上了）；
4. 三态：文本太短判不了 ⇒ 进 `unknown`，不折成"不同"、也不折成"没有拆命题"；
5. 三态：可用命题少于 2 条 ⇒ `reason` 非空（没查成，不是"没有这种形态"）；
6. 不静默丢行：概念行、被否证/被取代的行、空正文、没号的行逐条进 `skipped` 并给理由；
7. 反真空：把 `same_proposition` 打桩成恒判"不同" ⇒ ⑥ 必红；反之恒判"同"
   ⇒ ⑦ 必红（证明判据真的在读那个判定，而不是在背夹具）。

另有一条确定性判据：把同一批行换个顺序喂进去，读数逐字相同（不依赖行的物理顺序）。
"""
from __future__ import annotations

from typing import Any

import pytest

from agentflow import propositionkey as PK
from agentflow import statementfission as SF

#: 三条"同一条定理的不同写法"（键相同：设/假设、是/为、编号前缀都被规范化掉）。
_SYLOW = (
    ("000001", "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在。"),
    ("000002", "假设 G 为有限群，p 为素数，于是 G 的 Sylow p-子群存在。"),
    ("000003", "定理 2.1：设 G 为有限群、p 为素数；则 G 的 Sylow p-子群存在。"),
)
#: 一条确实不同的命题（负控）。
_OTHER = ("000009", "设 H 是交换群；则 H 的每个子群都正规。")

_PROOF = "证明：由轨道-稳定子定理与模 p 的计数引理。"


def _row(stmt_id: str, text: str, *, kind: str = "theorem", status: str = "active",
         proof_text: str = _PROOF, proofs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """一条命题行（形状照 `statements` 表：正文 / 证明 / 证明清单 / 种类 / 状态）。"""
    row: dict[str, Any] = {
        "stmt_id": stmt_id, "kind": kind, "status": status,
        "statement_full": text, "proof_text": proof_text,
    }
    if proofs is not None:
        row["proofs"] = proofs
    return row


def _sylow_rows() -> list[dict[str, Any]]:
    return [_row(stmt_id, text) for stmt_id, text in _SYLOW]


# ---------------------------------------------------------------- ⑥ 正控


def test_three_wordings_of_one_theorem_are_reported() -> None:
    """⑥ 三条同一命题的不同写法、都只有一份证明 ⇒ 报一簇并点名那三条。

    若这条破了：真机上那种"一条定理拆成三条独立命题"的形态仍然没有任何读数，
    `proof_no` 恒 1、`path_group` 只剩一组这件事就永远没人看得见。
    """
    got = SF.suspected_splits(_sylow_rows(), scope="夹具")
    assert got["reason"] == "", got["reason"]
    assert got["checked"] == 3, got["checked"]
    readings = got["readings"]
    assert len(readings) == 1, readings
    reading = readings[0]
    assert reading["kind"] == SF.KIND_SUSPECTED_SPLIT, reading
    assert list(reading["stmt_ids"]) == ["000001", "000002", "000003"], reading["stmt_ids"]
    assert reading["max_proof_no"] == 1, reading
    assert all(no == [1] for no in reading["proof_nos"].values()), reading["proof_nos"]
    assert len(reading["pairs"]) == 3, reading["pairs"]
    assert all(pair["similarity"] >= 0.85 for pair in reading["pairs"]), reading["pairs"]


def test_the_reading_names_the_statements_in_plain_words() -> None:
    """⑥的人话：读数要能直接贴进汇报（点名哪几条、凭什么、缺什么）。"""
    got = SF.suspected_splits(_sylow_rows(), scope="夹具")
    text = SF.describe(got["readings"][0])
    for stmt_id in ("000001", "000002", "000003"):
        assert stmt_id in text, text
    assert "proof_no>1" in text, text
    summary = SF.summary(got)
    assert "疑似拆命题 1 簇" in summary, summary


# ---------------------------------------------------------------- ⑦ 负控


def test_two_genuinely_different_propositions_are_not_reported() -> None:
    """⑦ 负控：两条确实不同的命题 ⇒ 不报（否则每两条命题都会被报成"拆命题"）。"""
    got = SF.suspected_splits([_row(*_SYLOW[0]), _row(*_OTHER)], scope="夹具")
    assert got["readings"] == [], got["readings"]
    assert got["different_pairs"] == 1, got
    assert got["reason"] == "", got["reason"]
    assert "疑似拆命题 0 簇" in SF.summary(got), SF.summary(got)


# ---------------------------------------------------------------- 多证明那一档


def test_a_second_proof_turns_the_cluster_into_multi_not_a_report() -> None:
    """有第 2 份证明 ⇒ 不报（进 `multi`）：它不是拆命题，是多证明机制被用上了。"""
    rows = _sylow_rows()
    rows[2]["proofs"] = [{"proof_no": 2, "proof_text": "证明（第二路线）：用 Wielandt 计数。"}]
    got = SF.suspected_splits(rows, scope="夹具")
    assert got["readings"] == [], got["readings"]
    assert len(got["multi"]) == 1, got["multi"]
    entry = got["multi"][0]
    assert entry["kind"] == SF.KIND_ALREADY_MULTI, entry
    assert entry["max_proof_no"] == 2, entry
    assert entry["proof_nos"]["000003"] == [1, 2], entry["proof_nos"]


# ---------------------------------------------------------------- 三态


def test_too_short_texts_are_unknown_and_never_folded_into_different() -> None:
    """三态：判不了（文本太短）⇒ 进 `unknown`，不折成"不同"，也不折成"没有拆命题"。"""
    got = SF.suspected_splits([_row("000010", "x = 1"), _row("000011", "y = 1")], scope="夹具")
    assert got["readings"] == [], got["readings"]
    assert got["unknown_pairs"] == 1, got
    assert got["different_pairs"] == 0, got
    assert got["unknown"][0]["reason"], got["unknown"]
    assert "判不了 1 对" in SF.summary(got), SF.summary(got)


def test_a_batch_that_cannot_be_compared_says_it_could_not_check() -> None:
    """三态：可用命题少于 2 条 ⇒ `reason` 非空（"没查成"不是"没有这种形态"）。"""
    got = SF.suspected_splits([_row(*_SYLOW[0])], scope="夹具")
    assert got["reason"], got
    assert got["readings"] == [], got["readings"]
    assert "没查成" in SF.summary(got), SF.summary(got)


def test_skipped_rows_are_named_with_their_reason() -> None:
    """不静默丢行：概念行 / 弃用状态 / 空正文 / 没号的行逐条进 `skipped`。"""
    rows = [
        _row(*_SYLOW[0]),
        _row(*_SYLOW[1]),
        _row("000020", "设 X 是拓扑空间。", kind="concept"),
        _row("000021", "设 G 是有限群。", status="refuted"),
        _row("000022", ""),
        _row("", "设 G 是有限群。"),
    ]
    got = SF.suspected_splits(rows, scope="夹具")
    reasons = {item["stmt_id"]: item["why"] for item in got["skipped"]}
    assert set(reasons) == {"000020", "000021", "000022", "（空）"}, reasons
    assert "概念行" in reasons["000020"], reasons
    assert "refuted" in reasons["000021"], reasons
    assert "空" in reasons["000022"], reasons
    # 跳过的不影响正控：那两条仍然报成一簇。
    assert [list(r["stmt_ids"]) for r in got["readings"]] == [["000001", "000002"]], got["readings"]


# ---------------------------------------------------------------- 反真空


def test_stubbing_the_identity_judge_to_different_makes_the_positive_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把 `same_proposition` 打桩成恒判"不同" ⇒ ⑥ 必红（判据读的是那个判定）。"""
    def always_different(a: str, b: str, **_kw: Any) -> dict[str, Any]:
        return {"state": PK.STATE_DIFFERENT, "similarity": 0.0, "basis": ""}

    monkeypatch.setattr(PK, "same_proposition", always_different)
    got = SF.suspected_splits(_sylow_rows(), scope="夹具")
    assert got["readings"] == [], "打桩成恒判不同之后仍然报出拆命题 ⇒ ⑥ 没有读那个判定"
    assert got["different_pairs"] == 3, got["different_pairs"]


def test_stubbing_the_identity_judge_to_same_makes_the_negative_control_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把 `same_proposition` 打桩成恒判"同" ⇒ ⑦ 必红（否则负控是空转的）。"""
    def always_same(a: str, b: str, **_kw: Any) -> dict[str, Any]:
        return {"state": PK.STATE_SAME, "similarity": 1.0, "basis": "stub"}

    monkeypatch.setattr(PK, "same_proposition", always_same)
    got = SF.suspected_splits([_row(*_SYLOW[0]), _row(*_OTHER)], scope="夹具")
    assert [list(r["stmt_ids"]) for r in got["readings"]] == [["000001", "000009"]], got["readings"]


# ---------------------------------------------------------------- 确定性


def test_the_reading_does_not_depend_on_row_order() -> None:
    """确定性：同一批行换个顺序，读数逐字相同（不许按物理顺序挑"代表"）。"""
    rows = _sylow_rows() + [_row(*_OTHER)]
    forward = SF.suspected_splits(rows, scope="夹具")
    backward = SF.suspected_splits(list(reversed(rows)), scope="夹具")
    assert forward == backward, (forward, backward)

# -*- coding: utf-8 -*-
"""甲：V 维护 verification 时多写「产出方的父编码」（业主 2026-11-11 裁定 ①）。

业主逐字：
    「V 秘书手上有关于 V 父和子的名册编码对应表（由于 V 无出边，它只有父，父就是
      手稿产出方，可能是 E,F,B）。于是在维护 verification 时多写一个父的编码是可行的。」

## 这一份钉什么

| # | 造什么 | 期望 |
|---|---|---|
| a | 四族手稿各落一行 pending | 每行 `producer_role` 与路径族一致（f→F / b→B / e→E / e-num→E）；`producer_code` 原样带出 |
| b | 一条老行（没有 `producer_role`） | 读侧 `unknown`，不炸、不硬填 F |
| c | 坏路径（`notes/x.md` / `reports/f-proof-abc.md`） | `producer_role=unknown` + 受控理由，不猜 |
| d | 反真空：把「按路径判族」改成「按调用方自报」 | a 必须红（这里用 f-proof 路径 + 自报 B 造现场） |

## 事实来源（唯一）

手稿路径的族前缀（`manuscriptfamily.classify_manuscript`）。`producer_code` 来自
V 的秘书名册（`Secretary.parent_of` 的 `name`），只在对账那一格用；父名单从
`capabilities.ALLOWED_EDGES` 现算，不写死。
"""
from __future__ import annotations

import pathlib

import pytest
from agentflow import capabilities as CAP
from agentflow import manuscriptsubmission as MS
from agentflow import verifications as VR
from agentflow.store import Store

BODY = "1. 由定义直接得到。"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _row(st: Store, rel: str, *, code: str = "", roster_role: str = "") -> dict:
    return VR.record_pending_sign(
        st.root, proof_text=BODY, verdict={"verdict": "成立"},
        object_path=rel, producer_path=rel, producer_code=code,
        roster_role=roster_role,
        secretary_judge={"checked": True, "axis": "clean",
                         "decision": "没问题", "reason": "夹具：clean"})


# ============================================================ a：四族都对上路径
@pytest.mark.parametrize("rel,role", [
    ("reports/f-proof-000001.md", "F"),
    ("reports/b-proof-000001.md", "B"),
    ("reports/e-proof-000001.md", "E"),
    ("reports/e-num-000001.md", "E"),
])
def test_a_new_row_carries_the_path_family_role(tmp_path, rel, role):
    st = _ws(tmp_path)
    row = _row(st, rel, code=f"{role}1")
    assert row["producer_role"] == role, row
    assert row["producer_code"] == f"{role}1", row
    read = VR.producer_reading(row)
    assert read["producer_role"] == role and read["checked"] is True, read


def test_a_parent_roster_is_read_from_capabilities_not_a_literal():
    """父名单从 `ALLOWED_EDGES` 现算（形状是 `dict[str, frozenset[str]]`）。"""
    got = MS.parents_of("V")
    assert got["checked"] is True, got
    expected = sorted(frm for frm, tos in CAP.ALLOWED_EDGES.items() if "V" in tos)
    assert got["parents"] == expected, (got, expected)
    assert set(expected) == {"B", "E", "F"}, expected
    # 每个新行都拿这条真身校验：四族的产出方都在父名单里
    for rel, role in [("reports/f-proof-000001.md", "F"),
                      ("reports/b-proof-000001.md", "B"),
                      ("reports/e-proof-000001.md", "E"),
                      ("reports/e-num-000001.md", "E")]:
        prod = MS.producer_of(rel, child_role="V")
        assert prod["in_parent_roster"] is True, (rel, prod)
        assert role in (got["parents"] or []), (role, got)


# ============================================================ b：老行 unknown
def test_b_an_old_row_without_the_cell_reads_unknown(tmp_path):
    st = _ws(tmp_path)
    old = {"verification_id": "v-0001", "statement_id": "000001",
           "verdict": "成立", "proof_sha256": "a" * 64}
    read = MS.verification_producer_reading(old)
    assert read["checked"] is False, read
    assert read["producer_role"] == "unknown", read
    assert "老行" in read["why"], read
    # V 的公开读口也是同一份
    assert VR.producer_reading(old) == read
    # 读一条老行不会抛（旧台账仍然读得出来）
    assert VR.read_verdict(old) == "成立"


# ============================================================ c：坏路径受控 unknown
@pytest.mark.parametrize("rel", [
    "notes/f-proof-000001.md",       # 名字对、目录不对 ⇒ legacy
    "reports/f-proof-abc.md",        # 像手稿、号解析不出 ⇒ bad_name
    "reports/RESEARCH.md",           # 不是手稿
])
def test_c_a_bad_path_is_unknown_not_a_guess(tmp_path, rel):
    st = _ws(tmp_path)
    row = _row(st, rel)
    assert row["producer_role"] == "unknown", row
    assert row.get("producer_problem"), row
    read = VR.producer_reading(row)
    assert read["checked"] is False and read["producer_role"] == "unknown", read
    assert read["why"], read


# ============================================================ d：反真空
def test_d_path_family_beats_a_self_reported_role(tmp_path):
    """把「按路径判族」换成「按调用方自报」⇒ 这里拿到 B，而 a 要求 F ⇒ 红。"""
    st = _ws(tmp_path)
    row = _row(st, "reports/f-proof-000001.md", roster_role="B")
    assert row["producer_role"] == "F", (
        "自报的父角色 B 改写了路径族（那正是裁定 ① 不许的「让模型自报」）", row)
    assert "不一致" in str(row.get("producer_problem") or ""), row


def test_d_parent_roster_is_not_a_hardcoded_list(monkeypatch):
    """把 E 的入边摘掉 ⇒ 同一份 e-proof 的 `in_parent_roster` 必须跟着变。"""
    real = dict(CAP.ALLOWED_EDGES)
    monkeypatch.setitem(CAP.ALLOWED_EDGES, "E",
                        frozenset(x for x in real["E"] if x != "V"))
    prod = MS.producer_of("reports/e-proof-000001.md", child_role="V")
    assert prod["producer_role"] == "E", prod
    assert prod["in_parent_roster"] is False, (
        "父名单被写死成一张字面量表 ⇒ 摘掉 E→V 之后它仍说「在名单里」", prod)
    assert "父名单" in prod["why"], prod

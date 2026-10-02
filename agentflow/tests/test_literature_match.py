# -*- coding: utf-8 -*-
"""`literature.matched`：命中校验（`draft/37` §2 R1b）——数据面 + 审计两面。

## 这一栏解决的是哪个真实故障

真机实测（2026-10-01）：A 被派去找 Brown 1971，检索 + 下载都"成功"了 ——
569,776 字节的真 PDF —— 但那是 2022 年的另一篇 CLT 论文。
台账里没有任何一栏能表达"我下错了"，于是下游（B 建概念、D 建命题）会拿一篇
无关文献当依据，而没有任何地方会响。这一栏就是那个"会响"的落点。

## 判据两面

1. schema 面：词表内的取值写得进、拼错的取值当场炸、空串合法（= 还没核，
   "没查"不许折成"查过了没问题"）；
2. 审计面（`verify`）：`mismatch` + 已被消化 ⇒ error（必须撤或重取）；
   `partial` + 已被消化 ⇒ warning（停在中间态要被看见）；
   而 `mismatch` + 未消化 ⇒ 一条都不报（反真空：不许把"记下来了"当成"出事了"）。
"""
from __future__ import annotations

import pytest
from conftest import TS, sync_counters
from agentflow import schema as S
from agentflow.verify import verify_all


def _issues(store, *, level: str | None = None, kind: str | None = None):
    rep = verify_all(store)
    d = rep.to_dict()
    out = list(d["errors"]) + list(d["warnings"])
    if level is not None:
        out = [i for i in out if i["level"] == level]
    if kind is not None:
        out = [i for i in out if i["code"] == kind]
    return out


def _lit(store, lid: str, **kw) -> dict:
    base = dict(lit_id=lid, title="Random walks on chamber graphs", type="J",
                summary="一篇论文", path=None, added_at=TS)
    base.update(kw)
    row = S.Literature(**base)
    row.validate()
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict())
    sync_counters(store)
    return row.to_dict()


# ==================================================== 一、schema 面

def test_the_three_states_and_the_unset_state_are_accepted(store):
    """正控：`exact` / `partial` / `mismatch` 与空串（= 还没核）都写得进。"""
    store.init()
    for i, value in enumerate(("exact", "partial", "mismatch", "")):
        _lit(store, f"{i:04d}", matched=value)
    assert {r["matched"] for r in store.rows("literature")} == {"exact", "partial", "mismatch", ""}


def test_a_bogus_match_value_is_rejected_at_write_time(store):
    """负控：拼错的取值当场炸（与 `download.status` 同一族 —— 错拼只会静默放行）。"""
    store.init()
    for bad in ("content_mismatch", "MISMATCH", "none", "exact ", "是"):
        with pytest.raises(ValueError) as e:
            _lit(store, "0000", matched=bad)
        assert "matched" in str(e.value), (bad, str(e.value))
    # 反真空：同一条行把值改对就能进（否则"永远拒绝"会冒充严格）
    _lit(store, "0000", matched="exact")


def test_the_unset_state_is_not_a_synonym_for_ok(store):
    """三态纪律的结构面：空串与 `exact` 是两个值，不是一个值的两种写法。"""
    store.init()
    _lit(store, "0000")                      # 没做命中校验
    _lit(store, "0001", matched="exact")     # 核过了，是这一篇
    rows = {r["lit_id"]: r["matched"] for r in store.rows("literature")}
    assert rows == {"0000": "", "0001": "exact"}, rows


# ==================================================== 二、审计面

def test_a_mismatched_literature_that_was_digested_is_an_error(store):
    """R1b 的核心判据：`mismatch` 不许进 `processed`。"""
    store.init()
    _lit(store, "0000", matched="mismatch", processed=True)
    errs = _issues(store, level="error", kind="mismatch_literature_processed")
    assert len(errs) == 1, (errs, _issues(store))
    assert "mismatch" in errs[0]["message"] and "processed" in errs[0]["message"], errs[0]


def test_a_mismatch_that_was_not_digested_is_not_an_issue(store):
    """反真空：如实记下"下错了"、且没有拿去消化 ⇒ 一条都不许报。

    这一条是这组判据里最要紧的反面：如果"记下 mismatch"本身就要报错，
    那么正确的行为（如实登记）会被惩罚，于是 A 会学会不写它 —— 那是本末倒置。
    """
    store.init()
    _lit(store, "0000", matched="mismatch", processed=False)
    assert _issues(store, kind="mismatch_literature_processed") == []
    assert _issues(store, level="error") == []


def test_a_partial_match_that_was_digested_warns_once(store):
    """分级：`partial` 是"同一篇但元数据有出入" ⇒ 值得看一眼（warning），不是 error。"""
    store.init()
    _lit(store, "0000", matched="partial", processed=True)
    assert len(_issues(store, level="warning", kind="partial_match_processed")) == 1
    assert _issues(store, level="error") == []
    # 反真空：把它确认成 exact 之后 warning 必须消失
    with store.tx("literature", actor="test") as tx:
        row = dict(store.rows("literature")[0])
        row["matched"] = "exact"
        tx.upsert("literature", row)
    assert _issues(store, kind="partial_match_processed") == []


def test_the_vocabulary_is_exposed_to_callers(store):
    """词表必须暴露给调用方（不暴露 ⇒ 写进去谁都拦不住，只能在写盘期给一句异常）。"""
    from agentflow.tools import build_registry

    store.init()
    reg = build_registry(store=store, workspace_root=store.root).registry
    res = reg.call("table.schema", role="A")
    assert res.ok, res
    vocabs = res.data["tables"]["literature"]["vocabularies"]
    assert vocabs["matched"]["values"] == list(S.LIT_MATCH_STATUSES), vocabs.get("matched")
    assert "mismatch" in vocabs["matched"]["values"]
    # 反真空：down与它相邻的那个字段各有自己的词表，不许串
    assert vocabs.get("type", {}).get("values") == list(S.LIT_TYPES)

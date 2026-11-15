# -*- coding: utf-8 -*-
"""`salvaged` 收什么、不收什么 —— 2026-11-14 三个绕法 + 2026-11-15 业主语义更正。

## 2026-11-15：撤掉"必须早于被放弃的那一条"（业主逐字裁定）

> 「我明确一下因证明太困难放弃，后拆出可用引理这条的语义：以 difficulty 为理由放弃
>   命题，后按照正常流程注册新命题进行攻坚，这些新命题可以是对原命题在加强条件下的
>   证明，或是取出中间部分逻辑链整理成命题，或是陈述负面事实等等。总之不是机械的」

⇒ 引理比被放弃的命题晚注册不是罪证（那正是业主语义里的顺序），时间戳不作判据。
"现造"改由下面几条挡（都不看时间）：

| # | 形态 | 期望 |
|---|---|---|
| a | `table.update` patch `{"kind":"lemma"}` 把一条普通行"改"成引理，不碰任何证据 | `abandon_salvaged_kind_from_patch` |
| b | 引理登记在目标之后（仍早于放弃时刻 / 甚至晚于放弃时刻都行） | 过（2026-11-15 起；改前拒 `abandon_salvaged_after_the_abandoned_statement`） |
| c | 把被放弃那条自己的 `statement_full` 原样抄成另一行 | `abandon_salvaged_copies_the_abandoned_statement` |

空壳那几条（正文空 / 无证明 / 无人认领 / 不在册）在
`tests/test_salvaged_can_come_after_the_abandonment.py` 里判（那是一组正/负控）。

## 判据各自在承重（反真空）

对每一条判据：把它打桩成"恒通过" ⇒ 对应的负控变绿（断言失败）。这正是
`test_abandon_reason_is_structured.py::test_e_removing_the_salvaged_check_makes_c_red`
的同形做法：打桩的是判据，不是测试。

## 门没有被关死（正控）

`test_d_*`：真正独立、在册、active、`kind=lemma`（登记来的，没有 patch 史）、
正文与被放弃那条不同，且秘书语义判定 `genuine` + `salvaged_from_proof` ⇒ 仍然放行；
两条判据各自被打桩时也仍然放行。晚于目标的那条（b）同样放行。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import conductor as CND
from agentflow import statementabandon as SA
from agentflow.store import Store

T0 = "2026-11-14T20:50:00+08:00"        # 被放弃的那一条的登记时刻
EARLIER = "2026-11-14T19:00:00+08:00"   # 旧稿时期（早于目标）
LATER = "2026-11-14T21:30:00+08:00"     # 晚于目标、仍早于放弃时刻
AT = "2026-11-14T23:30:00+08:00"        # 放弃时刻
SID = "000001"
LEMMA = "000002"
BODY_TARGET = ("设 n ∈ N，a ∈ S^{n−1}。记 A_{n,∞}(a) 为 n 维立方体被以 a 为法向的"
               "过原点超平面所截得的 (n−1) 维体积。Ball 定理：对所有 n 与所有 a 成立 "
               "A_{n,∞}(a) ≤ A_{n,∞}(a^{(2)}) = √2。")
BODY_LEMMA = "引理：Ball 的 BL 型积分不等式对每个 n 一致成立。"
DIFF = dict(abandon_kind="difficulty",
            abandon_basis="缺 Ball 的 BL 型积分不等式，本地无全文、册内无引理",
            difficulty="卡在 Ball 的 Brascamp–Lieb 型积分不等式这一条引理上")


def _genuine(**_kw) -> dict:
    """秘书语义判定的替身：真困难 + 从原证明里拆出（两问都判"是"）。"""
    return {"checked": True, "genuine": True, "where": "缺 Ball 的 BL 型积分不等式",
            "salvaged_from_proof": True, "problems": [], "decision": "夹具：难度判定",
            "refused": "", "reason": "夹具：难度判定"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, sid: str, *, kind: str, body: str, created: str) -> dict:
    row = {"stmt_id": sid, "origin": "own_result", "kind": kind,
           "label": f"探针 {sid}", "statement_full": body, "statement_text": body,
           "proof_text": "证明：夹具正文。", "status": "active", "created_at": created,
           "created_by": "test", "bits": {}, "quote_verified": None,
           "quote_reason": "夹具：自产命题"}
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _row(st: Store, sid: str = SID) -> dict:
    return next(dict(x) for x in st.rows("statements") if str(x.get("stmt_id")) == sid)


def _patch_kind_to_lemma(st: Store, sid: str = LEMMA):
    """走生产的 `table.update` 改 kind（判据本体在秘书那一侧；本文件不替它）。"""
    from agentflow.tools import table_tools
    from agentflow.tools.base import ToolRegistry

    reg = ToolRegistry(name="tables")
    reg.bound_role = "B"
    table_tools.register(reg, store=st)
    with CND.calling_as("t-gs", "B"):
        return reg.call("table.update", table="statements", id=sid,
                        patch={"kind": "lemma"})


def _abandon(st: Store, *, salvaged=(), judge=_genuine) -> dict:
    return SA.apply_abandonment(
        st, statement_id=SID, reason="夹具：放弃标记", at=AT, actor="test",
        difficulty_judge=judge, salvaged=list(salvaged), **DIFF)


# ---------------------------------------------------------------- a 就地改 kind
def test_a_a_kind_patched_into_lemma_is_not_a_salvaged_remnant(tmp_path):
    """a 负控：`created_at` 早于目标、正文也不同，唯一的问题是 kind 是 patch 抬的 ⇒ 拒。"""
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", body=BODY_TARGET, created=T0)
    _put(st, LEMMA, kind="conjecture", body=BODY_LEMMA, created=EARLIER)
    got = _patch_kind_to_lemma(st)
    assert got.ok is True, (got.error, got.data)      # patch 本身办成了（这一格不在本文件改）
    assert _row(st, LEMMA)["kind"] == "lemma", _row(st, LEMMA)
    res = _abandon(st, salvaged=[{"label": "引理", "stmt_id": LEMMA}])
    assert res["checked"] is False, res
    assert res["refused"] == SA.ABANDON_SALVAGED_KIND_FROM_PATCH, res
    assert _row(st, SID)["status"] == "active", _row(st, SID)


def test_a_stubbing_the_kind_provenance_check_makes_it_green(tmp_path, monkeypatch):
    """a 反真空：把"kind 是 patch 抬的、没有证据"这一问打桩成恒通过 ⇒ 同一条负控变绿。"""
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", body=BODY_TARGET, created=T0)
    _put(st, LEMMA, kind="conjecture", body=BODY_LEMMA, created=EARLIER)
    assert _patch_kind_to_lemma(st).ok is True
    monkeypatch.setattr(SA, "_salvaged_kind_from_patch", lambda row: "")
    res = _abandon(st, salvaged=[{"label": "引理", "stmt_id": LEMMA}])
    assert res["checked"] is True, (
        "反真空失效：打桩掉 kind 来路那一问之后仍然拒 ⇒ 这条负控证明不了它在承重", res)


# ---------------------------------------------------------------- b 晚于目标 = 合法
def test_b_a_lemma_registered_after_the_abandoned_statement_is_accepted(tmp_path):
    """b 正控（2026-11-15 业主语义）：lemma 登记在目标之后 ⇒ 过。

    改前这一条拒 `abandon_salvaged_after_the_abandoned_statement`（要求引理比被放弃
    的那一条更早注册）。那恰好否掉业主语义的第 2 步："以 difficulty 为理由放弃命题，
    后按照正常流程注册新命题进行攻坚" —— 所以那一道锚点撤掉了，时间戳不作判据。
    """
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", body=BODY_TARGET, created=T0)
    _put(st, LEMMA, kind="lemma", body=BODY_LEMMA, created=LATER)
    res = _abandon(st, salvaged=[{"label": "引理", "stmt_id": LEMMA}])
    assert res["checked"] is True, res
    parsed = SA.parse_abandon_reason(_row(st, SID)["quote_reason"])
    assert parsed["salvaged"][0]["stmt_id"] == LEMMA, parsed
    assert _row(st, SID)["status"] == "abandoned", _row(st, SID)


# ---------------------------------------------------------------- c 抄被放弃命题自己的正文
def test_c_copying_the_abandoned_statement_body_is_refused(tmp_path):
    """c 负控：正文与被放弃那条逐字相同 ⇒ 拆出来的是同一条命题本身 ⇒ 拒。"""
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", body=BODY_TARGET, created=T0)
    _put(st, LEMMA, kind="lemma", body=BODY_TARGET, created=EARLIER)
    res = _abandon(st, salvaged=[{"label": "同一段文字", "stmt_id": LEMMA}])
    assert res["checked"] is False, res
    assert res["refused"] == SA.ABANDON_SALVAGED_COPIES_THE_STATEMENT, res
    assert _row(st, SID)["status"] == "active", _row(st, SID)


def test_c_stubbing_the_body_copy_check_makes_it_green(tmp_path, monkeypatch):
    """c 反真空：把"正文是不是抄的"这一问打桩成恒通过 ⇒ 同一条负控变绿。"""
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", body=BODY_TARGET, created=T0)
    _put(st, LEMMA, kind="lemma", body=BODY_TARGET, created=EARLIER)
    monkeypatch.setattr(SA, "_salvaged_copies_statement", lambda *a, **kw: False)
    res = _abandon(st, salvaged=[{"label": "同一段文字", "stmt_id": LEMMA}])
    assert res["checked"] is True, (
        "反真空失效：打桩掉正文比对之后仍然拒 ⇒ 这条负控证明不了它在承重", res)


# ---------------------------------------------------------------- d 正控：门没有被关死
def test_d_a_genuine_local_remnant_still_passes(tmp_path):
    """d 正控：独立、在册、active、登记来的 lemma、正文不同 ⇒ 仍然放行。"""
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", body=BODY_TARGET, created=T0)
    _put(st, LEMMA, kind="lemma", body=BODY_LEMMA, created=EARLIER)
    res = _abandon(st, salvaged=[{"label": "引理", "stmt_id": LEMMA}])
    assert res["checked"] is True, res
    parsed = SA.parse_abandon_reason(_row(st, SID)["quote_reason"])
    assert parsed["complete"] is True and parsed["abandon_kind"] == "difficulty", parsed
    assert parsed["salvaged"][0]["stmt_id"] == LEMMA, parsed


@pytest.mark.parametrize("name, value", [
    ("_salvaged_kind_from_patch", lambda row: ""),
    ("_salvaged_copies_statement", lambda *a, **kw: False),
])
def test_d_the_positive_control_stays_green_under_each_stub(tmp_path, monkeypatch,
                                                            name, value):
    """d 的反真空：两条判据各自被打桩成恒通过时，正控也照样放行（不许打成"什么都拒"）。"""
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", body=BODY_TARGET, created=T0)
    _put(st, LEMMA, kind="lemma", body=BODY_LEMMA, created=EARLIER)
    monkeypatch.setattr(SA, name, value)
    res = _abandon(st, salvaged=[{"label": "引理", "stmt_id": LEMMA}])
    assert res["checked"] is True, (name, res)

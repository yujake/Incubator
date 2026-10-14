# -*- coding: utf-8 -*-
"""「广告面 = 接受面」的判据：模型看得见的形状必须够它把事做成（`draft/37` §84 的 D1）。

## 这一组守什么（T1 实测撞出来的）

T1 那一趟里，`E.run_experiment` 被调 12 次 —— 「9 次被参数校验拒、3 次因硬约束失败」，
而每一次模型的行为都是「合理」的：它按自己看得见的形状调用。错在框架：

- `method="exhaustive_search"` 时 `schema.Experiment` 的硬约束 2c 要求 `certificate`，
  而 `certificate` / `search_bound` 「不在任何 schema 里」（动作表没有、工具 schema 没有、
  方法签名也没有）⇒ 模型不可能知道，「每一次尝试都注定失败」。
  `P-8` 只把通道接到了 `_support.build_experiment`，没接到公开入口。
- `name` / `imports` 是条件性参数（只对 `method='formal'` 有效），却被无条件广告
  ⇒ 模型给计算类方法传了它们，被拒三次。

判据分成两半，缺一不可：

1. 「可做性（正控）」：按广告的形状调用「必须真的能把事做成」 —— 带 `certificate` +
   `search_bound` 的 `exhaustive_search` 要落下一行 `experiments`；
2. 「可发现性（判据自己盯住广告面）」：那两格必须在「动作表」与「工具 schema」两处都出现，
   且方法签名真的收它们 —— 否则"广告了但收不下"或"收得下但没广告"都无人发现。

负控两条：不给 `certificate` 必须「如实拒绝」（而不是静默落一行没有证书的"穷举结论"）；
把 `certificate` 传给非穷举类方法必须被拒（与 `name`/`imports` 同一条纪律：不许静默忽略）。
"""
from __future__ import annotations

import inspect
import json
import pathlib
import sys

import pytest

from agentflow import capabilities as CAP
from agentflow import schema as S
from agentflow.agent_e import AgentE
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.tools import build_registry

#: 一个最小的"穷举类"脚本：打印约定的结构化结论行。
_SEARCH_SCRIPT = (
    "import json\n"
    "print('REPRO_RESULT: ' + json.dumps("
    "{'result': 'supports', 'observations': {'checked': 12, 'no_counterexample': True}}))\n"
)

_CERT = {"kind": "enumeration_bound", "note": "穷举 n<=12 的所有周期"}
_BOUND = {"n_max": 12, "domain": "periods with |v| <= 12"}


def _wired(tmp_path: pathlib.Path):
    """一个工作区 + 主控 + 工具层（与其余判据同一套接线）。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond, workspace_root=str(ws)).registry
    (ws / "search.py").write_text(_SEARCH_SCRIPT, encoding="utf-8")
    return st, reg, ws


def _run(reg, **kw):
    """按广告的形状调一次 `verify.run_experiment`。"""
    params = {"claim": "在 n<=12 内没有反例", "claim_key": "bound12",
              "script_path": "search.py", "method": "exhaustive_search"}
    params.update(kw)
    return reg.call("verify.run_experiment", role="E", **params)


# ---------------------------------------------------------------- 一、可做性

def test_an_exhaustive_search_with_a_certificate_is_recorded(tmp_path: pathlib.Path):
    """正控（T1 的缺陷在这里）：按广告的形状给证书 ⇒ 「真的落下一行实验」。

    修之前这一格永远做不到：`certificate` 不在任何 schema 里，而硬约束 2c 又要求它
    ⇒ 模型每一次 `exhaustive_search` 都必然失败（T1 实测 3 次）。
    """
    st, reg, _ws = _wired(tmp_path)
    res = _run(reg, certificate=_CERT, search_bound=_BOUND)
    assert res.ok, (res.error, res.meta)
    assert res.data.get("result") == "supports", res.data
    assert res.data.get("evidence_kind") in S.EVIDENCE_KINDS, res.data
    rows = st.rows("experiments")
    assert len(rows) == 1, rows
    assert rows[0].get("method") == "exhaustive_search"
    assert rows[0].get("certificate"), "证书没有落进实验行"


def test_an_exhaustive_search_without_a_certificate_is_refused_not_silently_recorded(
        tmp_path: pathlib.Path):
    """负控（不许把"没有证书的穷举结论"写成一行正常证据）。"""
    st, reg, _ws = _wired(tmp_path)
    res = _run(reg)
    assert not res.ok, res.data
    assert "certificate" in str(res.error), res.error
    assert st.rows("experiments") == [], "缺证书的那次调用居然落了行"


def test_a_certificate_on_a_non_search_method_is_refused(tmp_path: pathlib.Path):
    """负控（与 `name`/`imports` 同一条纪律）：非穷举类方法收到证书 ⇒ 拒绝，不静默忽略。"""
    st, reg, _ws = _wired(tmp_path)
    res = _run(reg, method="numeric", certificate=_CERT, search_bound=_BOUND)
    assert not res.ok, res.data
    assert "certificate" in str(res.error), res.error
    assert st.rows("experiments") == []


# ---------------------------------------------------------------- 二、可发现性

def test_the_search_certificate_fields_are_advertised_in_both_layers(tmp_path: pathlib.Path):
    """正控（判据自己盯住广告面）：动作表与工具 schema 都要广告这两格，且方法签名收它们。

    为什么必须两层都查：只查一层会漏掉"广告了但收不下"或"收得下但没广告"的那一半 ——
    T1 的 12 次失败正是这两种漏法的混合。
    """
    action = next(a for a in CAP.actions_for("E") if a.action == "run_experiment")
    props = (action.params or {}).get("properties") or {}
    for field in ("certificate", "search_bound"):
        assert field in props, f"动作表没广告 {field}：{sorted(props)}"
    # 工具 schema 从「真注册表」里读（不是再抄一份）：抄一份就测不到分发面
    _st, reg, _ws = _wired(tmp_path)
    tool_props = (reg.get("verify.run_experiment").params or {}).get("properties") or {}
    for field in ("certificate", "search_bound"):
        assert field in tool_props, f"工具 schema 没广告 {field}：{sorted(tool_props)}"
    sig = inspect.signature(AgentE.run_experiment).parameters
    for field in ("certificate", "search_bound"):
        assert field in sig, f"方法签名不收 {field}：{sorted(sig)}"


def test_the_conditional_formal_params_say_so_in_their_description():
    """负控（条件性参数要写明条件）：`name`/`imports` 的描述必须写出"仅 formal"。

    修之前它们是「光秃秃的」 `_S`（只声明类型）⇒ 模型给计算类方法传了它们、被拒三次，
    而"为什么被拒"要等它自己撞出来。
    """
    action = next(a for a in CAP.actions_for("E") if a.action == "run_experiment")
    props = (action.params or {}).get("properties") or {}
    for field in ("name", "imports"):
        desc = str((props.get(field) or {}).get("description") or "")
        assert "formal" in desc, f"{field} 的描述没写清只对 formal 有效：{desc!r}"


def test_check_formal_says_it_needs_source_or_script_path():
    """负控（沉默的必需）：`check_formal` 的摘要必须写明"二者必居其一"。

    T1 里它被调 3 次、三次都没给源码 ⇒ 落进 `no_script`（什么都没核），
    而那三次调用在模型看来都是"我调了形式化"。
    """
    action = next(a for a in CAP.actions_for("E") if a.action == "check_formal")
    summary = str(action.summary or "")
    assert "source" in summary and "script_path" in summary, summary


# ------------------------------- 三、`B.register_statement` 的条件阶梯（§87 的根因）

def _b_instance(tmp_path: pathlib.Path):
    """按装配路径造一个 B（替身抽取器就够：这一组不抽取，只登记命题）。"""
    from agentflow import host as host_mod

    ws = tmp_path / "bws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    reg = host_mod.build_role_registry(st, providers=[object()], config={},
                                       workspace_root=str(ws))
    return st, reg["B"][1](store=st)


#: 一条"除了被测的那一格之外都齐"的自产命题。
_OWN = dict(
    statement_full="本文的引理：对周期图 K(m)，稳定范数取整数值",
    statement_text="稳定范数取整数值",
    origin="own_result", kind="lemma", evidence_kind="heuristic",
    quote_reason="本轮还没做逐字比对（引文那一栏待核）",
)
_OWN_SOURCE = dict(doc_id="0000", proof_text="证明：由定义直接得到。")


def test_the_conditional_ladder_of_register_statement_is_advertised():
    """正控（§87 的根因）：那四级条件必须写在模型看得见的形状里。

    T1 第 2 趟实测：`origin='own_result'` 先撞 `doc_id`/`line_range`（8 次），
    改对之后再撞 `proof_text`（6 次），14 次召唤全废、`statements` 始终 0 行。
    四级分别是：① 出处（`doc_id` 或 `line_range`）；② `proof_text`；
    ③ `quote_verified` 不是 true ⇒ `quote_reason`；④ `doc_id` 的格式（4 位十进制）。
    """
    action = next(a for a in CAP.actions_for("B") if a.action == "register_statement")
    props = (action.params or {}).get("properties") or {}
    summary = str(action.summary or "")
    assert "proof_text" in summary and "quote_reason" in summary, summary
    assert "external_lit" in summary and "source_lit_id" in summary, summary
    for field, needle in (("origin", "proof_text"), ("doc_id", "6 位十进制"),
                          ("proof_text", "own_result"), ("source_lit_id", "external_lit"),
                          ("page_range", "external_lit"), ("quote_reason", "必需")):
        desc = str((props.get(field) or {}).get("description") or "")
        assert needle in desc, f"{field} 的描述没写清条件（缺 {needle!r}）：{desc!r}"


def test_a_complete_own_result_statement_lands_and_each_missing_rung_is_refused(
        tmp_path: pathlib.Path):
    """正控 + 逐级负控：齐了才落行；缺出处/引用理由/ID 形态任何一级都不落行。

    ## 第 ① 级（缺 `proof_text`）为什么是"落行 + 挂待办"而不是"拒收"

    `F-05`（主控裁定，2026-10-06）改判了这一档：以前它 `_refuse`，于是"证明还没做完"
    永远进不了库，`draft/53:181` 那个消费端永远拿不到一条待办。现在它落在库里、
    带 `pending` 待办与 `notes` 明写，等级由 `evidencebits.derive_grade` 现算（『猜想』）。
    所以本用例这一级断言的是两件事：①-a 它真的进去了且待办挂得住；
    ①-b 这条改判不许蔓延 —— `external_lit` 缺 `source_lit_id` 仍然必须拒。

    负控逐级来，是因为模型在 T1 里正是一级一级撞上去的：每个负控都对应
    它当时得到的那一种拒绝。
    """
    st, b = _b_instance(tmp_path)

    # 正控：四级都齐 ⇒ 落一行
    good = dict(_OWN)
    good.update(_OWN_SOURCE)
    res = b.register_statement(**good)
    assert res.get("ok"), res
    assert len(st.rows("statements")) == 1, st.rows("statements")

    def _bump(n: str) -> dict:
        return {**_OWN, "statement_full": _OWN["statement_full"] + f"（{n}）"}

    # 负控逐级：四级都要以 `ok=False` + 具名 `kind` 拒绝，不许从事务里抛异常。
    # 为什么这条也是判据：T1 里 8 次"被拒"与 6 次"失败"在模型看来是两种东西 ——
    # 前者的 `kind` 直接告诉它缺什么，后者只有一个异常；而"缺哪一级"这件事
    # 本来就不该靠异常表达（`Statement.validate()` 是兜第二道，不是第一道）。
    #
    # ---- 第 ① 级在 `F-05`（主控裁定，2026-10-06）被改判：缺 `proof_text` 不再拒收 ----
    #
    # 改前（本条判据原先钉的形态，逐字）：`ok is False and kind == "missing_proof_text"`。
    # 改后：这一笔落库（`ok is True`），但绝不静默接受 —— 返回里带一条 `pending`
    # 待办 + `note` 明写"缺 proof_text / 等级现算是『猜想』"，行里 `proof_text` 留空。
    # 为什么改判（`register_statement.py:155-161` 逐字）：以前这里 `_refuse`，于是
    # "证明还没做完"这一档永远进不了库，也就永远没有一条待办能被秘书消费
    # （`draft/53:181` 的消费端要的是"摆出来"，不是"拦住"）。判据于是改成两半：
    # ①-a 落库且挂待办（下面这段）＋ ①-b 不许蔓延（`external_lit` 缺出处仍必须拒）。
    r1 = b.register_statement(**_bump("①"), doc_id="0000")          # 缺 proof_text
    assert r1.get("ok") is True, r1
    pending = list(r1.get("pending") or [])
    assert [p.get("missing") for p in pending] == ["proof_text"], r1
    assert pending[0].get("kind") == "missing_proof" and pending[0].get("who") == "F", pending
    assert "缺 proof_text" in str(r1.get("note") or ""), r1
    landed_min = next(r for r in st.rows("statements") if r["stmt_id"] == r1["stmt_id"])
    assert not str(landed_min.get("proof_text") or "").strip(), landed_min
    assert landed_min.get("quote_verified") is None, landed_min

    # ①-a 的另一半：没给 `quote_reason` 时框架替它把理由写实（那正是"待办挂得住"
    # 的前提）—— 只留一个空字段等于把"没查"记成一笔没人能接手的账。
    # 进得去这一支的唯一入口是 `quote_verified=True`：`quote_verified is not True`
    # 且缺 `quote_reason` 会先被 `missing_quote_reason` 拦下（`register_statement.py:107`，
    # 实测：先写成本例时正是被它拦的）—— 所以这里显式给 `quote_verified=True`。
    r1b = b.register_statement(
        **{**{k: v for k, v in _bump("①b").items() if k != "quote_reason"},
           "quote_verified": True}, doc_id="0001")
    assert r1b.get("ok") is True, r1b
    landed_b = next(r for r in st.rows("statements") if r["stmt_id"] == r1b["stmt_id"])
    assert "证明还没做完" in str(landed_b.get("quote_reason") or ""), landed_b

    # ①-b 负控（新规则的边界）：改判只覆盖"自产命题的证明还没做完"这一档，
    # 不许蔓延成"出处也可以不给" —— `external_lit` 缺 `source_lit_id` 仍然必须拒，
    # 且 `kind` 具名。实测（`register_statement.py:103-106`）它走的是 `missing_source`。
    r1c = b.register_statement(**{**_bump("①c"), "origin": "external_lit",
                                  "page_range": {"label": "全文未分页"}})
    assert r1c.get("ok") is False and r1c.get("kind") == "missing_source", r1c

    r2 = b.register_statement(**_bump("②"), proof_text="证明")       # 缺 doc_id/line_range
    assert r2.get("ok") is False and r2.get("kind") == "missing_own_source", r2
    no_reason = {k: v for k, v in _bump("③").items() if k != "quote_reason"}
    r3 = b.register_statement(**no_reason, **_OWN_SOURCE)            # 缺 quote_reason
    assert r3.get("ok") is False and r3.get("kind") == "missing_quote_reason", r3
    r4 = b.register_statement(**_bump("④"), doc_id="doc:0000", proof_text="证明")  # ID 形态
    assert r4.get("ok") is False and r4.get("kind") == "bad_id", r4
    # 同一级的另一半：`source_lit_id` 走的是同一个谓词（两条路都要具名，不能只保一条）
    r5 = b.register_statement(**{**_bump("⑤"), "origin": "external_lit"},
                              source_lit_id="lit-1", page_range={"label": "全文未分页"})
    assert r5.get("ok") is False and r5.get("kind") == "bad_id", r5

    # 台账里只该有"齐了的那一条"与"①/①b 那两条挂待办的"，被拒的四条一条都不许落。
    assert len(st.rows("statements")) == 3, "被拒的那几条里有落进台账的"


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))

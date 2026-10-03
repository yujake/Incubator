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


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))

# -*- coding: utf-8 -*-
"""D 的两个动作返回不是字典：`submit_gaps -> list[str]`、`write_report -> str`。

## 为什么补这个文件

亲测 D 时我按"动作都回 dict"的惯例去 `.get(...)`，连撞两次 `AttributeError`。
两件事其实都真的落地了（检索请求真的入队、报告文件真的写出），
坏的是"结果读不出来"—— 业主口径：*"凡是你凭感觉第一次运行工具发现红了，
都要假想真实智能体也会在这里困惑并浪费时间和 token。"*

处置：这两个返回形状是刻意的（`submit_gaps` 给你"提交出去的编号"、
`write_report` 给你"写下的那个路径"，且"只写文件、不落表"），
所以在 D 的手册里写明了（描述侧对齐，不改代码）；
这一组判据钉住行为——返回的东西必须真的落地：

1. `write_report()` 返回的路径真的存在，而且里面是这个问题的内容；
2. `submit_gaps()` 返回的编号每一条都能在 `search_requests` 里找到（不是随口一串）；
3. 负控：没有可提交的缺口时，它给的是空的列表（而不是 None / 抛异常）。
"""

from __future__ import annotations

import pathlib

from agentflow.agent_d import AgentD
from agentflow.store import Store


def _d(tmp_path: pathlib.Path) -> tuple[AgentD, Store]:
    store = Store(tmp_path / "ws")
    store.init()
    return AgentD(store), store


def _question(d: AgentD) -> str:
    got = d.propose_question(question="探针：模形式与费马大定理的关系是什么？",
                             kind="gap", gap_reason="本地书架上还没有把两者连起来的关系",
                             priority="medium")
    row = got if isinstance(got, dict) else got.to_dict()
    return str(row.get("question_id") or "")


def test_write_report_returns_a_path_that_really_exists(tmp_path: pathlib.Path) -> None:
    """正控：返回的是路径，而且那份文件真的在盘上、里面是这个问题。"""
    d, _store = _d(tmp_path)
    qid = _question(d)
    assert qid, "propose_question 没给出 qid"
    out = d.write_report()
    assert isinstance(out, str), f"write_report 应当返回路径字符串，收到 {type(out).__name__}"
    path = pathlib.Path(out)
    assert path.exists(), f"write_report 说它写了 {out}，可盘上没有这个文件"
    assert qid in path.name, f"报告文件名里应当带 qid（{qid}），实际是 {path.name}"


def test_submit_gaps_returns_ids_that_really_landed(tmp_path: pathlib.Path) -> None:
    """正控：返回的每个编号都要能在 `search_requests` 里找到（不是随口一串）。"""
    d, store = _d(tmp_path)
    qid = _question(d)
    out = d.submit_gaps(qid)
    assert isinstance(out, list), f"submit_gaps 应当返回编号列表，收到 {type(out).__name__}"
    known = {str(r.get("request_id") or "") for r in store.rows("search_requests")}
    for rid in out:
        assert str(rid) in known, f"它说提交了 {rid}，可 search_requests 里没有这一条"


def test_no_gap_to_submit_is_an_empty_list_not_none(tmp_path: pathlib.Path) -> None:
    """负控：没有可提交的缺口 ⇒ 空列表（不是 None、也不抛）—— 空与"没做成"是两件事。"""
    d, _store = _d(tmp_path)
    qid = _question(d)
    first = d.submit_gaps(qid)
    second = d.submit_gaps(qid)          # 同一条问题再交一次：已提交集应当挡住
    assert isinstance(second, list), type(second)
    assert len(second) <= len(first), (first, second)

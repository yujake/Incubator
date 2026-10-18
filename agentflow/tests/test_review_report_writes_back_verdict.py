# -*- coding: utf-8 -*-
"""`review.report` 的**契约**：只写一个报告文件，**不碰任何数据表**。

## 为什么要有这一条（2026-10-18）

我曾试图让 `review.report` 把它的裁决**写回** `documents`，为的是消掉真机里
"`documents=accepted/成立` 而 `review.report` 判 `rejected`"的矛盾。
但 `tests/test_gates.py::test_agent_h_produces_a_hash_pinned_report_on_disk` 当场判红：
**`review.report` 改动了数据表 —— 它只该写一个报告文件**。这是刻意立的契约
（报告是"H 的书面意见"，台账是"机械检查的裁决"，两件事分开才查得清）。

所以这里把**真实契约**钉住：

1. `review.report` 跑完，`documents` 逐字节不变；
2. 它的 `verdict` 只出现在**报告文件**与返回值里；
3. 想改台账，必须走 `review.review_document` / `review.verify_fixes`（它们才登记了写集）。
"""
from __future__ import annotations

import json

import pytest

from test_agent_h import clean_claim, seed_document

from agentflow.agent_h import AgentH
from agentflow.store import Store
from agentflow.tools import review_tools as RV


@pytest.fixture()
def h_store(tmp_path):
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _docs_snapshot(st: Store) -> str:
    return json.dumps(st.rows("documents"), ensure_ascii=False, sort_keys=True)


def test_report_writes_only_the_report_file_and_never_the_tables(h_store: Store):
    """**正控**：`review.report` 只落一个 md，`documents` 逐字节不变。"""
    seed_document(h_store, "0001", [clean_claim()])
    h = AgentH(h_store, config={"max_review_rounds": 2})
    h.review("0001", dependencies=[])          # 机械全 0 ⇒ accepted/成立
    before = _docs_snapshot(h_store)

    rep = RV.review_report(
        h_store, "0001", own_errors=[], banned_words=["已形式化验证"],
        workspace_root=h_store.root, actor="agent-H",
        out_path="out/review/0001-review.md",
    )

    path = h_store.root / "out/review/0001-review.md"
    assert path.is_file(), "报告没落盘"
    assert str(rep.get("verdict") or ""), "返回值里必须带裁决"
    assert _docs_snapshot(h_store) == before, (
        "review.report 改了 documents —— 契约是「只写一个报告文件」")


def test_the_two_verdicts_are_deliberately_two_things(h_store: Store):
    """**说明性判据**：机械裁决（review_document）与门裁决（report）**可以不同**。

    真机读数（`projects/t1t`）：`review_document` 全 0 ⇒ `accepted/成立`，
    而 `review.report` 15 道门里 G7 挂了 ⇒ `rejected`。
    两者并存不是 bug —— 但**必须都能被读到**：机械裁决在台账，门裁决在报告。
    """
    seed_document(h_store, "0002", [clean_claim()])
    h = AgentH(h_store, config={"max_review_rounds": 2})
    mech = h.review("0002", dependencies=[])
    assert str(mech.get("verdict")) == "accepted"

    rep = RV.review_report(
        h_store, "0002", own_errors=[], banned_words=["已形式化验证"],
        workspace_root=h_store.root, actor="agent-H",
        out_path="out/review/0002-review.md",
    )
    gate = str(rep.get("verdict") or "")
    assert gate in ("rejected", "unverified"), rep
    assert (h_store.root / "out/review/0002-review.md").is_file()

# -*- coding: utf-8 -*-
"""`register_statement` 的拒信要一次把缺的出处字段说齐（业主 2026-10-16 亲测口径）。

## 为什么补这个文件

我按它的声明逐个补字段时，实测走了 三轮才凑齐：

```
bad_origin  →  missing_quote_reason  →  missing_page_range
```

业主口径（逐字）："凡是你凭感觉第一次运行工具发现红了，都要假想真实智能体也会在这里
困惑并浪费时间和 token。" ⇒ 一次只点名一条，等于让智能体多跑两趟。

这一条钉住修好之后的行为：kind 与原来一致（兼容既有判据），但消息里要把整份清单给出来。
"""

from __future__ import annotations

import pathlib

from agentflow.agent_b import AgentB
from agentflow.store import Store


def _b(tmp_path: pathlib.Path) -> AgentB:
    store = Store(tmp_path / "ws")
    store.init()
    return AgentB(store, extractor=None, extract_text=None)


def test_the_refusal_lists_every_missing_provenance_field(tmp_path: pathlib.Path) -> None:
    """正控：`external_lit` 缺三样时，一次就把三样都说出来。"""
    b = _b(tmp_path)
    out = b.register_statement(origin="external_lit", statement_full="探针命题：若 n≥3 则无解",
                               kind="theorem")
    got = out if isinstance(out, dict) else out.to_dict()
    assert got.get("ok") is False, got
    assert got.get("kind") == "missing_source", got           # kind 不许变（兼容既有判据）
    err = str(got.get("error") or "")
    for key in ("source_lit_id", "quote_reason", "page_range"):
        assert key in err, f"拒信里没点名 {key}（那智能体下一轮还得再来问一次）：{err}"
    assert "还缺" in err, err


def test_a_complete_call_does_not_carry_the_hint(tmp_path: pathlib.Path) -> None:
    """负控：字段给齐时不许再挂"还缺"那一行（否则它就成了噪声）。"""
    b = _b(tmp_path)
    out = b.register_statement(
        origin="own_result", statement_full="探针命题：自有结果一条", kind="lemma",
        proof_text="Proof. 探针。", line_range={"start": 1}, doc_id="000000",
        # `quote_reason` 是任何 origin 都必填的（`quote_verified` 不是 True 时）——
        # 我第一次的"完整"夹具漏了它，判据当场把它抓出来（这正是这条判据的用处）。
        quote_verified=False, quote_reason="探针：引文还没查",
    )
    got = out if isinstance(out, dict) else out.to_dict()
    # 这一笔可能因为别的理由被拒（例如稿件不存在），但不该再报"还缺出处字段"。
    assert "还缺" not in str(got.get("error") or ""), got

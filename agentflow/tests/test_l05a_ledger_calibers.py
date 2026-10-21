# -*- coding: utf-8 -*-
"""L-05a 的判据：模型管道三代记账口径收敛到同一本账（`usage_ledger`）。

`44` 的原始读数：`llm.py`+`modelclient.py`（服务"B 用模型读文献"）的 `scope="extract"` 真机 0 次；`runflow`
走 `modelcost.charge_reply`；只有 `agent_loop→llmseam→modelgw` 活着。裁定是"减（合并记账口径）"，并逐字附了一条红线：
不许删 `modelclient`/`extract`（真机 115 行花销、27 个工作区）。

## 收敛的判据形态：不是"只有一个函数"，而是"只有一本账"

三代各有各的 `scope` 与行构造，但写入口必须唯一（`tokenmeter.TokenMeter.charge_once` → `usage_ledger`）。三条判据各钉一代：

| 代 | 写入口 | 依据 |
|---|---|---|
| `llm.py`+`modelclient`（extract） | `modelcost.charge_reply` → `TokenMeter` | `modelclient.py:44/147` |
| `runflow` | `modelcost.charge_reply` → `TokenMeter` | `runflow.py` 的记账处 |
| `agent_loop→llmseam→modelgw` | `llmseam._charge_ledger` → 同一个 `TokenMeter.charge_once` | `llmseam.py`（B 的文件，
本条只读不改） |

一处已知的"不收敛"，如实登记（不擅自改）：`llmseam._charge_ledger` 刻意不走 `charge_reply` —— 它的 docstring 逐字说明了理由（`charge_reply`
自己拿 `reply` 重算 `usd_for(...)`，而 `SeamCall` 没有 `attempts` ⇒ 走它会让"网关重试过的调用"只按一次计价，于是与 `llm_call` 事件里的 `usd` 不等）。
合并那两处行构造要动 `llmseam.py`（B 线）⇒ 按纪律写需求单，不在这条线里改。"""
from __future__ import annotations

import json
import pathlib

from agentflow.modelclient import ModelClient
from agentflow.modelgw import ModelGateway, ModelSpec
from agentflow.store import Store
from agentflow.tokenmeter import TokenMeter

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"


def _src(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def test_l05a_extract_generation_writes_through_the_one_ledger_writer():
    """第一代（`llm.py` + `modelclient`）：记账经 `modelcost.charge_reply`，写进同一本账。"""
    body = _src("modelclient.py")
    assert "from .modelcost import charge_reply" in body, "extract 那一代不走 modelcost（两套算式）"
    assert "charge_reply(" in body and "self.meter" in body, body[:400]
    # 运行期：一次 `complete` 的账必须落在 `usage_ledger`，且 scope 是它声明的那一档
    st = Store(pathlib.Path(__file__).resolve().parent / "_l05a_ws")
    st.init()
    try:
        body_json = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "甲"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }, ensure_ascii=False)

        def _t(url, headers, data, timeout_sec):
            return 200, body_json

        c = ModelClient(gateway=ModelGateway(ModelSpec(api_key="k"), transport=_t),
                        meter=TokenMeter(st), task_id="t-0001", role="B")
        assert c.complete("你好") == "甲"
        rows = st.rows("usage_ledger")
        assert len(rows) == 1 and rows[0]["scope"] == "extract", rows
        assert rows[0]["task_id"] == "t-0001", rows
    finally:
        import shutil
        shutil.rmtree(st.root, ignore_errors=True)


def test_l05a_runflow_generation_shares_the_same_writer():
    """第二代（`runflow`）：它的记账也必须经 `modelcost`（不许自己拼账本行）。"""
    body = _src("runflow.py")
    assert "charge_reply" in body or "modelcost" in body, "runflow 的记账不在 modelcost 上"
    assert "usage_ledger\"" not in body or "charge_reply" in body, "runflow 自己拼账本行"


def test_l05a_llmseam_generation_lands_in_the_same_ledger():
    """第三代（`llmseam`）：落点也是 `TokenMeter.charge_once`（同一本账）——只读判据。

    它属 B 的文件：这一条只读源码证明"写入口唯一"，不改它。
    两处行构造的分工与"为什么刻意不走 charge_reply"见 `llmseam._charge_ledger` 的
    docstring（本模块 docstring 里也逐字引了）⇒ 合并它要动 B 的文件，走需求单。
    """
    body = _src("llmseam.py")
    assert "charge_once" in body, "llmseam 的落点不是 TokenMeter.charge_once（就不是同一本账）"
    assert "usage_ledger" not in body or "meter" in body, "llmseam 自己拼账本行？"
    assert "为什么不用 `modelcost.charge_reply`" in body, \
        "那处刻意的不收敛必须有逐字理由（否则它就是分叉）"

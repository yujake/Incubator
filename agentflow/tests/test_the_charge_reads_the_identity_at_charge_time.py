# -*- coding: utf-8 -*-
"""判据：`modelclient` 在**计费那一刻**读召唤上下文，不在**装配那一刻**写死。

## 现场（`temp/analysis/11-ledger-causes.md` ② A 组，2026-11-14 lp-ball 真机）

`run-agent` 那条路给 B 造抽取器走 `host._Builder._extractor_for` ⇒ `host.b_extractor`，
而它**装配期**逐字写死 `task_id=None`（`host.py:70-78`）。`ModelClient` 把这个 `None`
原样透传（`modelclient.py:149-153`），**从不读 `ambient_task_id()`**；对照 `llmseam`
同一件事读了两处（`llmseam.py:693-694`）。后果是 `scope=extract` 的 **13 笔**
（227,901 tokens / $0.108832）全部无主，占 6.9% 缺口的 **97.99%** ——
而它们发生在 B 的 `t-000017` 那一趟里（该趟的另外 45 笔账全部有声有号）。

时间线证据说明："这些调用没有召唤可挂"这句话在**收费那一刻**是假的，
它只在**装配那一刻**成立。所以判据钉的是**读数发生在哪一刻**，不是"有没有这个字段"。

## 这一组钉四件事

1. 正控：在 `Conductor.summon` 的 handler 里发一次 `ModelClient.complete`
   （装配期 `task_id` 缺省 `None`）⇒ 账本那一行的 `task_id` 必须是这一次召唤的号，
   且 `tasks.usd` 与账本该号汇总逐分相等、`reconcile_usage().unattributed` 为 0；
2. 三态：没有任何召唤上下文、调用方也没给号 ⇒ 那一行仍是 `None`，但 `note` 必须写明
   `unattributed`（"这一次本来就不属于任何 task"，不是"忘了填"）；
3. 显式号优先：调用方给了号时，ambient 不许覆盖它（两处优先级只有一份规则）；
4. 反真空：把 ambient 读口打桩成空 ⇒ 第 1 条必须变红（13 笔无主的那个形态回来）。

改前红：第 1、4 条（`task_id=None` 一路写进账本，`tasks.usd=0`、缺口=$0.00… 见下）；
3 条绿（第 2、3 条本来就该绿，改前改后都不能被这次改动带走）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import conductor as CO
from agentflow import modelclient as MC
from agentflow import tokenmeter as TM
from agentflow.modelclient import ModelClient
from agentflow.modelgw import ModelGateway, ModelSpec
from agentflow.store import Store
from agentflow.tokenmeter import TokenMeter


def _transport(status: int, body: str):
    def _t(url: str, headers, data: bytes, timeout_sec: float):
        del url, headers, data, timeout_sec
        return status, body

    return _t


def _body(text: str = "抽出结果", tin: int = 11, tout: int = 3) -> str:
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": tin, "completion_tokens": tout},
    }, ensure_ascii=False)


def _client(*, meter: Any = None) -> ModelClient:
    """抽取那一路的 client：**装配期不写号**（与 `host.b_extractor` 同形）。"""
    return ModelClient(gateway=ModelGateway(ModelSpec(api_key="fake-model-key"),
                                            transport=_transport(200, _body())),
                       meter=meter)


class _ExtractingB:
    """B 的抽取 handler：模型调用发生在 handler 里（生产上就是 `calling_as` 内）。"""

    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def run_once(self, **_kw: Any) -> dict[str, Any]:
        """与真机同形：B 的 `run_once` 里那些抽取调用就走这个 client。"""
        return {"outcome": "ok", "detail": "抽完了一篇",
                "payload": {"text": self.client.complete("读这一篇")}}


def _world(tmp_path: pathlib.Path) -> tuple[Store, ModelClient, Any]:
    store = Store(tmp_path / "ws")
    store.init()
    client = _client(meter=TokenMeter(store))
    conductor = CO.Conductor(store, registry={"B": ("object", _ExtractingB(client))},
                             backend="local")
    return store, client, conductor


def _charge_rows(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("usage_ledger") if str(r.get("scope")) == "extract"]


def _task_row(store: Store, task_id: str) -> dict:
    rows = [dict(r) for r in store.rows("tasks") if str(r.get("task_id")) == task_id]
    assert len(rows) == 1, rows
    return rows[0]


# ============================================================ 1 正控：计费那一刻的号
def test_the_charge_lands_on_the_summon_that_was_running(tmp_path: pathlib.Path) -> None:
    """判据 1：装配期没号，但收费发生在召唤里 ⇒ 账本那一行必须挂上召唤号。

    改前：`ModelClient` 只用装配期那个 `None` ⇒ 账本行 `task_id=None`、
    `tasks.usd` 停在 0、`reconcile_usage` 的 `unattributed` 多一笔 —— 正是
    真机那 13 笔（$0.108832 / 97.99% 缺口）的形态。
    """
    store, _client_obj, conductor = _world(tmp_path)
    got = conductor.summon("B", "run_once", {}, input_key="a")
    assert str(got.task_id or ""), got

    rows = _charge_rows(store)
    assert len(rows) == 1, rows
    assert str(rows[0].get("task_id") or "") == str(got.task_id), (
        "抽取这一笔的账没有挂在『收费那一刻真正在跑的那一次召唤』上："
        f"账本={rows[0].get('task_id')!r} 召唤={got.task_id!r}；note={rows[0].get('note')!r}")

    reading = TM.reconcile_usage(store)
    assert reading["unattributed"]["count"] == 0, reading
    assert reading["equal"] is True and reading["diff_usd"] == 0.0, reading
    assert reading["named_residual"] == [] and reading["dangling"] == [], reading

    row = _task_row(store, str(got.task_id))
    ledger_usd = round(sum(float(r.get("usd") or 0.0) for r in rows), 6)
    assert ledger_usd > 0
    assert float(row.get("usd") or 0.0) == ledger_usd, (
        f"回写没跟上：tasks.usd={row.get('usd')} 账本={ledger_usd}")


# ============================================================ 2 三态：说得出为什么空
def test_outside_every_summon_the_note_names_which_empty_this_is(
        tmp_path: pathlib.Path) -> None:
    """判据 2：不在任何召唤里、调用方也没给号 ⇒ 仍留 `None`，但 note 必须点名 `unattributed`。

    为什么这一条不要求红：这一档**本来就该是空的**。要钉的是"空"与"忘了填"分得开 ——
    账本行自己说得清"这一次本来就不属于任何 task"。
    """
    store = Store(tmp_path / "ws")
    store.init()
    client = _client(meter=TokenMeter(store))
    assert client.complete("读这一篇（没有召唤）") == "抽出结果"

    rows = _charge_rows(store)
    assert len(rows) == 1, rows
    assert rows[0].get("task_id") is None, rows[0]
    note = str(rows[0].get("note") or "")
    assert "unattributed" in note, f"空号的那一笔没有自行点名：{note!r}"
    assert "召唤" in note, f"note 没有说清为什么空：{note!r}"

    reading = TM.reconcile_usage(store)
    assert reading["unattributed"]["count"] == 1, reading
    assert reading["equal"] is False and reading["diff_usd"] > 0, reading


# ============================================================ 3 显式号优先
def test_an_explicit_task_id_is_not_overwritten_by_the_ambient_one(
        tmp_path: pathlib.Path) -> None:
    """判据 3：调用方显式给了号 ⇒ ambient 不许覆盖它（优先级只有一份规则）。"""
    store = Store(tmp_path / "ws")
    store.init()
    client = _client(meter=TokenMeter(store))
    client.task_id = "t-000900"
    with CO.calling_as("t-000017", "B"):
        client.complete("读这一篇")
    rows = _charge_rows(store)
    assert len(rows) == 1 and str(rows[0].get("task_id")) == "t-000900", rows


# ============================================================ 4 反真空
def test_stubbing_the_ambient_reader_puts_the_gap_back(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 4（反真空）：把 ambient 读口打桩成空 ⇒ 判据 1 的形态必须回来。

    没有这一条，判据 1 可能只是"两个数碰巧相等"（也许号是从别处飘进来的）。
    打桩的是 `modelclient` 的读口本身（`_ambient_task_id`），不动任何别的挂点。
    """
    store, _client_obj, conductor = _world(tmp_path)
    monkeypatch.setattr(MC, "_ambient_task_id", lambda: "", raising=False)
    got = conductor.summon("B", "run_once", {}, input_key="a")

    rows = _charge_rows(store)
    assert len(rows) == 1, rows
    assert rows[0].get("task_id") is None, (
        f"读口被打桩成空之后账本行还挂着号：{rows[0].get('task_id')!r} —— "
        "这一条没在测『计费那一刻读上下文』这件事")
    reading = TM.reconcile_usage(store)
    assert reading["unattributed"]["count"] == 1, reading
    assert reading["equal"] is False and reading["diff_usd"] > 0, reading
    assert float(_task_row(store, str(got.task_id)).get("usd") or 0.0) == 0.0, (
        "无主的那一笔不许回写到召唤行上")

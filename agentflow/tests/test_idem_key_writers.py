"""两条生产写入方是否真的把键填进了 `UsageEntry.idem_key` 字段。

## 这个文件补的是哪一段缺口

`docs/NOAI-REVIEW-REGISTER.md` §2.2.4 第 2 条如实登记过：

> 生产写入方仍未填 `idem_key`：`tokenmeter.charge_once` 目前只把标记写在 `note` 里。

后果是字段级防线（`schema.validate_table` 的唯一性断言、`verify.duplicate_idem_key`）在真实路径上永远没有输入 —— 它们在测试里常绿，在生产上从不生效。
本文件把"字段真的被填了"变成可判定的断言，并给出两条会红的负控。

两条写入方与它们的键来源：

| 写入方 | 键 | 语义 |
|---|---|---|
| `modelcost.charge_reply`（经 `TokenMeter.charge_once`） | `modelcost.idempotency_key(task_id, call_index)` | 第
i 次模型调用 |
| `conductor._charge_and_settle`（经 `TokenMeter.charge_once`） | `modelcost.settle_key(task_id)` | 一次召唤的汇总结算 |

两者都写同一个键到 `note` 的 token 与 `idem_key` 字段：少任何一层都有明确的后果（少 `note` ⇒ 回滚后判重失去依据；少字段 ⇒ 表级唯一性断言形同虚设）。"""

from __future__ import annotations

import json

import pytest

from agentflow import conductor as CO
from agentflow import schema as S
from agentflow.modelcost import charge_reply, idempotency_key, settle_key
from agentflow.modelgw import ModelReply
from agentflow.store import Store
from agentflow.tokenmeter import Charge, TokenMeter, marker_of, note_tokens
from agentflow.verify import verify_all

TS = "2026-01-01T00:00:00+00:00"


# --------------------------------------------------------------------- 夹具


class _FakeE:
    """E 的替身：只回报一个 token 花销，不碰任何真依赖。"""

    def run_experiment(self, claim, claim_key, script_path, **_: object) -> dict:
        return {"outcome": "ok", "detail": f"{claim} 跑完", "tokens": 7,
                "payload": {"claim": claim}}


def _conductor(store: Store) -> CO.Conductor:
    return CO.Conductor(store, registry={"E": ("object", _FakeE())}, backend="local")


def _usage_rows(store: Store) -> list[dict]:
    return store.rows("usage_ledger")


def _reply(**kw: object) -> ModelReply:
    return ModelReply(**kw)  # type: ignore[arg-type]


def _doc(*rows: dict) -> dict:
    return {"schema_version": S.SCHEMA_VERSION, "rows": list(rows)}


def _raw(usage_id: str, *, idem_key: str | None = None, note: str = "测试") -> dict:
    """直接构造快照 dict；`idem_key=None` = 模拟"这一行根本没有这个键"。"""
    row = {
        "usage_id": usage_id, "scope": "search", "role": "A", "task_id": None,
        "tokens_in": 1, "tokens_out": 2, "tokens_total": 3, "usd": 0.0,
        "attempts": 1, "at": TS, "note": note,
    }
    if idem_key is not None:
        row["idem_key"] = idem_key
    return row


def _write_snapshot(store: Store, *rows: dict) -> None:
    """绕过事务直接改快照 —— 模拟"另一个写入方/外部脚本写下的第二行"。"""
    (store.data / "usage_ledger.json").write_text(
        json.dumps(_doc(*rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# ============================================================ 字段真的被填了


def test_charge_reply_fills_the_idem_key_field(store: Store):
    """正控（真实路径）：模型调用入账后，那一行的 `idem_key` 非空且等于派生的键。"""
    meter = TokenMeter(store)
    out = charge_reply(meter, _reply(ok=True, tokens_in=10, tokens_out=5),
                       task_id="t-0001", call_index=2, scope="reason", now=TS)
    assert out["charged"] is True
    rows = _usage_rows(store)
    assert len(rows) == 1
    row = rows[0]
    want = idempotency_key("t-0001", 2)
    assert row["idem_key"] == want, (
        "字段必须由真实写入方填上 —— 空字段会让表级唯一性断言与 "
        "verify.duplicate_idem_key 在真实路径上永远没有输入"
    )
    assert row["idem_key"], "非空是硬要求（空键不受唯一性约束）"
    assert row["idem_key"] in note_tokens(row["note"]), "B 层（note 标记）不许撤"


def test_charge_once_fills_the_field_and_keeps_the_note_token(store: Store):
    """正控（账本层）：`charge_once` 两层都写，且幂等语义逐字不变。"""
    meter = TokenMeter(store)
    key = marker_of("idem", "t-0009", 0)
    charge = Charge(role="A", scope="search", tokens_in=1500, note="检索")
    first = meter.charge_once(charge, idem_key=key, now=TS)
    again = meter.charge_once(charge, idem_key=key, now=TS)

    rows = _usage_rows(store)
    assert len(rows) == 1, "同一幂等键只许落一行"
    assert rows[0]["idem_key"] == key
    assert key in note_tokens(rows[0]["note"])
    assert again["recorded"] is False and again["duplicate"] is True
    assert again["usage_id"] == first["usage_id"], "重放必须指向同一行"


def test_conductor_settle_fills_the_idem_key_field(store: Store):
    """正控（第二条写入方）：召唤级结算那一行的字段等于 `settle_key(task_id)`。"""
    c = _conductor(store)
    res = c.summon("E", "run_experiment",
                   {"claim": "a", "claim_key": "ka", "script_path": "s.py"},
                   input_key="k1")
    assert res.tokens == 7
    rows = [u for u in _usage_rows(store) if str(u.get("task_id")) == res.task_id]
    assert len(rows) == 1
    assert rows[0]["idem_key"] == settle_key(str(res.task_id))
    assert rows[0]["idem_key"], "非空是硬要求"
    assert rows[0]["idem_key"] in note_tokens(rows[0]["note"])


def test_charge_without_a_key_leaves_the_field_empty(store: Store):
    """负控（不误报的前提）：没有幂等身份的行字段为空，且不参与唯一性。

    `charge()` 是刻意保留的非幂等入口（`task_id` 为空时构不成键，
    见 `_charge_and_settle` 的说明）。它的行必须保持空字段 ——
    否则"没有幂等身份"与"有幂等身份"就分不开了。
    """
    meter = TokenMeter(store)
    meter.charge(Charge(role="A", scope="search", tokens_in=1, note="a"), now=TS)
    meter.charge(Charge(role="A", scope="search", tokens_in=2, note="b"), now=TS)
    rows = _usage_rows(store)
    assert [r["idem_key"] for r in rows] == ["", ""]
    S.validate_table("usage_ledger", _doc(*rows))
    assert [i for i in verify_all(store).issues if i.code == "duplicate_idem_key"] == []


# ============================================================ 负控：绕过幂等检查


def test_negative_control_schema_rejects_the_second_row_with_the_same_key(store: Store):
    """负控①（会红）：绕过 `charge_once` 的判重直接写第二行 ⇒ 表级断言必须抓到。

    判重（锁内）与唯一性（表级）是两道独立的门。这里刻意把第一道门绕过，
    证明第二道门自己会响 —— 否则"字段级唯一性"只是文档里的一句话。
    """
    meter = TokenMeter(store)
    key = marker_of("idem", "t-0007", 0)
    meter.charge_once(Charge(role="A", scope="search", tokens_in=1500, note="检索"),
                      idem_key=key, now=TS)
    dup = dict(_usage_rows(store)[0])
    dup["usage_id"] = "0001"
    with pytest.raises(ValueError, match="重复的幂等键"):
        with store.tx("usage_ledger", actor="test") as tx:
            tx.upsert("usage_ledger", dup, note="绕过判重")
    assert len(_usage_rows(store)) == 1, "失败事务不许留下半成品"


def test_negative_control_verify_reports_what_the_store_assertion_also_sees(store: Store):
    """负控②（会红）：快照里被塞进两行同键 ⇒ `verify` 的 `duplicate_idem_key` 必须报。

    同时断言既有判据看不见它：两行的 `usage_id` 本来就不同，
    所以 `duplicate_id` 不响（这正是这条新判据存在的理由）。
    """
    _write_snapshot(store, _raw("0000", idem_key="idem-dup"),
                    _raw("0001", idem_key="idem-dup"))
    codes = {i.code for i in verify_all(store).issues}
    assert "duplicate_idem_key" in codes
    assert "duplicate_id" not in codes


def test_negative_control_historical_rows_without_the_key_are_never_reported(store: Store):
    """负控③：历史行（连这个键都没有）与空键行都不许被误报，也不许互相冲突。

    未升级进程写的行落在这一档。把它们算进唯一性会让整表提交直接炸
    （所有历史行互相"重复"），那是比原缺陷更糟的形态。
    """
    _write_snapshot(store, _raw("0000"), _raw("0001"), _raw("0002", idem_key=""))
    assert [i for i in verify_all(store).issues if i.code == "duplicate_idem_key"] == []


def test_distinct_keys_from_both_writers_coexist(store: Store):
    """负控（装置本身能写进去）：两条写入方在同一张表里各写各的键，谁也不挡谁。

    没有这一条，"唯一性断言全绿"可能只是因为表里根本写不进第二行。
    """
    meter = TokenMeter(store)
    charge_reply(meter, _reply(ok=True, tokens_in=1, tokens_out=1),
                 task_id="t-0001", call_index=0, scope="reason", now=TS)
    meter.charge_once(Charge(role="E", scope="summon", tokens_out=3, note="结算",
                             task_id="t-0002"),
                      idem_key=settle_key("t-0002"), now=TS)
    keys = [r["idem_key"] for r in _usage_rows(store)]
    assert len(keys) == 2 and all(keys)
    assert keys[0] != keys[1]
    assert keys[0].startswith("idem-") and keys[1].startswith("settle-")
    S.validate_table("usage_ledger", _doc(*_usage_rows(store)))
    assert [i for i in verify_all(store).issues if i.code == "duplicate_idem_key"] == []

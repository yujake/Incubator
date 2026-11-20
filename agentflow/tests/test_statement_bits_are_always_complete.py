# -*- coding: utf-8 -*-
"""判据 c / d(c)：新写一条命题 ⇒ 盘上 `bits` 是完整的 10 键、没有一格是 `None`。

## 这条判据钉的是哪一处缺陷

`temp/rmk90-audit/REPORT-R-mk-infinite-90-20261105.md` ② / §A-3：

- `data/statements.json:1423`（命题 000019）的 `bits` 是 `{}`；
- 同一路径写其余 20 行都是 10 键齐的 dict；
- `data/events.jsonl:3671` 是写入那一刻：`2026-11-05T20:54:32`、`actor=secretary-B`、
  `note=record_statement`、`sid=000019`、`grade=None / proof=None / reviewed=None`。

根因两处（都在写侧，不在读侧）：

| 位置 | 改前 | 症状 |
|---|---|---|
| `secretary._statement_from`（`bits=dict(body.get("bits") or {})`） | 调用方没交 `bits` ⇒ 落盘 `{}` | B 那一次走的是 `table.create(table="statements")`（`row` 里没有 `bits`），被路由到秘书正路 ⇒ 路由对了、内容少了一格 |
| `evidencebits.bits_shape_problems({})` | 返回 `[]`（空表 = 没有形状问题） | `schema.Statement.validate` 那道闸对"整块没填"没有牙 |

修法两半（「拒或补全」）：`_complete_statement_bits` 把缺的键补出来（没交 bits 就按这一行
自己的字段现算），`_record_statement_tx` 再核一遍"10 键齐、无 None"，不齐就整笔不写。

## 判据怎么才算红（反真空）

`test_negative_control_without_the_completion_step` 把补全那一步摘掉（打桩成改前的
`dict(body.get("bits") or {})`）⇒ 这一笔必须被写侧拒掉（`write_failed` + 原话点名
`bits`），一条 `bits` 空的行都不许落盘。正控那一组断言在注入下必红 —— 这就是
"补全那一步确实是这条判据的来源"的证据。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import conductor as CO
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import STATEMENT_BITS_KEYS, Secretary
from agentflow.store import Store
from agentflow.tools import build_registry
import _secretary_home as HOME  # 打桩打在定义处（搬家后 SEC 那一格只是再导出）

#: 000019 那一行的形状（逐字取 `events.jsonl:3671` 的载荷：B 用 `table.create` 交的那一份）。
#: 刻意不带 `bits` —— 这就是现场。
_ROW_000019: dict[str, Any] = {
    "origin": "own_result",
    "kind": "proposition",
    "label": "字典积族 H[K_2]（奇数档 m=2d+1≥5）",
    "statement_full": (
        "设 d ≥ 2 为整数，H 是 d-正则、无三角、连通、简单图。令 G = H[K_2] 为字典积。"
        "则 G 是简单、连通、(2d+1)-正则图。"),
    "statement_text": "设 d ≥ 2 为整数，H 是 d-正则、无三角、连通、简单图。",
    "proof_text": "",
    "line_range": {"start": None, "end": None,
                   "label": "reports/f-proof-000019.md §命题（含全部假设）"},
    "quote_verified": None,
    "quote_reason": ("中间态（2026-11-05，P3/手稿 000019）：本行为我方自产结果，"
                     "不来自文献 ⇒ 无逐字文献引文可回验，quote_verified 留空 = 还没查"),
    "evidence_kind": "heuristic",
}


# --------------------------------------------------------------------- 夹具


def _world(tmp_path: pathlib.Path) -> tuple[Store, Any]:
    """一个工作区 + 一张真工具面（`table.create` 那条路就是现场那条路）。"""
    st = Store(tmp_path / "ws")
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    built = build_registry(store=st, conductor=cond, workspace_root=str(st.root))
    return st, built.registry


def _create_via_table_tool(registry: Any, row: dict[str, Any]) -> Any:
    """按现场的身份调 `table.create(table="statements")`（B 在 t-000001 里那一笔）。"""
    with CO.calling_as("t-000001", role="B"):
        return registry.call("table.create", role="B", table="statements", row=dict(row))


def _statement_rows(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("statements")]


def _missing_keys(bits: Any) -> list[str]:
    got = dict(bits or {})
    return [k for k in STATEMENT_BITS_KEYS if k not in got or got[k] is None]


def _events_of(store: Store, table: str) -> list[dict]:
    path = pathlib.Path(str(store.root)) / "data" / "events.jsonl"
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001 —— 坏行不是本判据的对象
            continue
        if str(row.get("table")) == table and str(row.get("op")) == "upsert":
            out.append(row)
    return out


# ================================================================ c：正控


def test_the_000019_write_path_lands_a_complete_bits_block(tmp_path: pathlib.Path):
    """判据 c 的正控：现场那条路（`table.create` ⇒ 秘书）写出来的行，`bits` 必须 10 键齐。

    这一条刻意复现「现场那一条」：B 用 `table.create(table="statements")` 交一份
    `row`（没有 `bits`），被路由到 `Secretary.record_statement` 落盘。改前它落成
    `bits={}`，于是 000019 的档位与等级同时"读不出来"。
    """
    st, registry = _world(tmp_path)
    res = _create_via_table_tool(registry, _ROW_000019)
    assert res.ok is True, (res.error, res.meta)
    assert "record_statement" in json.dumps(res.meta, ensure_ascii=False), res.meta

    rows = _statement_rows(st)
    assert len(rows) == 1, rows
    bits = dict(rows[0].get("bits") or {})
    assert sorted(bits) == sorted(STATEMENT_BITS_KEYS), (
        f"新写的 statements 行必须带完整的 10 键 bits（现场是空表）：{sorted(bits)}")
    assert _missing_keys(bits) == [], f"任何一格都不许是 None：{bits}"
    # 档位与等级必须读得出来 —— 这就是"bits 空 ⇒ 两格都读不出"的反面。
    assert bits["grade"] == "conjecture", bits
    assert bits["origin"] == "own_result", bits
    assert bits["proof"] is False and bits["reviewed"] is False, bits
    assert EB.bits_shape_problems(bits, kind=str(rows[0].get("kind") or "")) == [], bits
    # 写入的那一刻（events 里的 upsert 行）也必须是同一份 10 键 —— 读快照与读事件同结论。
    upserts = [e for e in _events_of(st, "statements")
               if str((e.get("row") or {}).get("stmt_id")) == str(rows[0]["stmt_id"])]
    assert upserts, "这一笔没有任何 statements upsert 事件（落盘没留痕）"
    assert sorted((upserts[-1].get("row") or {}).get("bits") or {}) == sorted(
        STATEMENT_BITS_KEYS), upserts[-1].get("row", {}).get("bits")


def test_a_proofed_statement_keeps_its_own_bits(tmp_path: pathlib.Path):
    """正控②：调用方交了 `bits` ⇒ 那一份必须被保留（补全只补不删）。

    这一条防的是"为了消掉空表，把所有 bits 都重算一遍"——那会把 B 现算的五元位
    （第 2 位 true + `evidence.proof_process`）洗掉，等于换一个方向分家。
    """
    st = Store(tmp_path / "ws")
    st.init()
    sec = Secretary("B", root=st.root, store=st)
    proof = "第 1 步：由定义直接得到。"
    supplied = EB.bits_of(proof=True, proof_process=proof, origin="own_result")
    out = sec.record_statement({"statement_full": "若 H 是 d-正则无三角连通图，则 H[K_2] 是 (2d+1)-正则图。",
                                "kind": "proposition", "origin": "own_result",
                                "proof_text": proof, "bits": supplied,
                                "quote_verified": None,
                                "quote_reason": "自产结果"}, role="B")
    assert out.get("checked") and out.get("created"), out
    row = _statement_rows(st)[0]
    bits = dict(row["bits"])
    assert _missing_keys(bits) == [], bits
    assert bits["proof"] is True, bits
    assert bits["evidence"].get("proof_process") == proof, bits["evidence"]
    assert bits["grade"] == EB.derive_grade(bits, kind=row["kind"]), bits


# =============================================================== d(c)：反真空


def test_negative_control_without_the_completion_step_refuses_the_write(
        tmp_path: pathlib.Path, monkeypatch):
    """判据 c 的反真空：把补全那一步摘掉 ⇒ 写侧必须拒，一条空 bits 的行都不许落。

    注入的是改前那一行（`bits=dict(body.get("bits") or {})`）。正控那组断言
    （10 键齐 / 无 None / 等级读得出）在注入下全数落空 —— 这就是
    "绿来自补全那一步"的直接证据。
    """
    from agentflow import secretary as SEC

    HOME.patch(monkeypatch, "_complete_statement_bits",
        lambda body, *, kind, origin: dict(body.get("bits") or {}),
        raising=True)
    st, registry = _world(tmp_path)
    res = _create_via_table_tool(registry, _ROW_000019)
    assert res.ok is False, (res.error, res.meta)
    meta = json.dumps(res.meta, ensure_ascii=False)
    assert "bits" in meta and "10 键" in meta, meta
    assert _statement_rows(st) == [], "被拒的一笔不许留下半行（空 bits 的行更不许）"


def test_negative_control_a_none_in_one_bit_is_refused(tmp_path: pathlib.Path,
                                                       monkeypatch):
    """判据 c 的反真空②：10 个键都在、但有一格是 `None` ⇒ 同样拒（`None` 算缺）。

    `grade=None` 与"没有 grade"在读侧长得一样 —— 两者都让"等级读不出来"重新成立，
    所以写侧不许只数键、不数 `None`。
    """
    from agentflow import secretary as SEC

    def _with_a_none(body, *, kind, origin):  # noqa: ANN001
        bits = {k: ({} if k in ("evidence", "voided_by") else False)
                for k in STATEMENT_BITS_KEYS}
        bits["numeric"] = "pending"
        bits["grade"] = None          # ← 这一格是 None
        return bits

    HOME.patch(monkeypatch, "_complete_statement_bits", _with_a_none, raising=True)
    st, registry = _world(tmp_path)
    res = _create_via_table_tool(registry, _ROW_000019)
    assert res.ok is False, (res.error, res.meta)
    assert "grade" in json.dumps(res.meta, ensure_ascii=False), res.meta
    assert _statement_rows(st) == []

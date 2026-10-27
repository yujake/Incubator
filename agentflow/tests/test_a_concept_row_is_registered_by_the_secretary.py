# -*- coding: utf-8 -*-
"""D14：概念行必须经秘书那一笔（五元位 / 洗名 / 概念同一性由它做）。

## 真机证据（`projects/mp3-r3`，2026-10-26，36 行 statements）

```
30 行 concept 全部 created_by = agent-B、bits 空、非平凡度无记录
写入口：conceptrows.py 的 tx.upsert("statements", …)（note="concept_upsert" /
        "concept_sync:*"），created_by 来自 concept_statement 的缺省 agent-B
        ⇒ 绕过了 Secretary.record_statement
对照：secretary-B 落的那 1 行（000002 theorem）bits 有 —— 正路是好的
```

所以这一份钉的不是"秘书能不能写概念"，而是"另外那三个写口有没有绕过它"。

## 五条判据

| 条 | 它要证明的事 | 改前为什么是红的 |
|---|---|---|
| a | 一条概念经 `upsert_legacy_shaped`（真机那条路）登记 ⇒ `bits` 非空、`created_by` 是 `secretary-*`、等级是"不适用" | 改前 `created_by=agent-B`、`bits={}` |
| a2 | 另一条写口 `upsert`（独立写一条概念）走的是同一份实现 | 同上 |
| a3 | 洗名（`wash_working_name`）与概念同一性（`propositionkey.same_concept`）真的在这一笔里跑过，且判词可读 | 改前这一层一份判据都没有（直写） |
| b | 正控：概念行仍然能升档（定义到了回 `active`）与能合并（老表墓碑 ⇒ `superseded`） | 这一条改前改后都该绿（护栏：接线不许把既有行为弄丢） |
| c | 反真空：把接线打桩成"直写回去" ⇒ a 必红 | 它证明 a 的绿是这一笔接线给的 |

## 边界

全部 tmp 工作区、零真实模型调用、不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from agentflow import conceptrows as CR
from agentflow import propositionkey as PK
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.store import Store

#: 一条老形状的概念行（`agent_b/run_once.py` 交上来的就是这个形状）。
LEGACY = {"concept_id": "0000", "name": "有限维李代数",
          "definition": "概念（有限维李代数）：设 K 为特征 0 的域，g 为 K 上的 Lie 代数；"
                        "称 g 有限维，若 dim_K g < ∞。",
          "aliases": [], "related_concepts": [], "normalized_name": "有限维李代数"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _one(st: Store) -> dict:
    rows = _rows(st)
    assert len(rows) == 1, [(r.get("stmt_id"), r.get("label")) for r in rows]
    return rows[0]


def _problems(row: dict) -> list[str]:
    """一条概念行"经秘书那一笔"缺了什么（空列表 = 它确实是秘书落的）。

    这三条就是判据 a 的入场读数：五元位非空、写的是秘书、等级按概念那一档算。
    反真空那一条拿同一个函数打红（判据不经两套口径）。
    """
    problems: list[str] = []
    if not dict(row.get("bits") or {}):
        problems.append("bits 是空的（五元位没算：概念行没有人替它算过）")
    if not str(row.get("created_by") or "").startswith("secretary-"):
        problems.append(f"created_by={row.get('created_by')!r}（落盘的不是秘书）")
    grade = str((row.get("bits") or {}).get("grade") or "")
    if grade != "not_applicable":
        problems.append(f"bits.grade={grade!r}（概念行的等级是'不适用'，不是猜想）")
    return problems


# ============================================================ a) 真机那条写口

def test_a_concept_written_by_upsert_legacy_shaped_carries_bits_and_the_secretary(
        store: Store) -> None:
    """a：`upsert_legacy_shaped`（`agent_b` 与夹具共用的那一格）落下的概念行经秘书。

    改前红：这一笔是 `conceptrows.write_concept` → `tx.upsert("statements", …)` 直写，
    `created_by` 来自 `concept_statement` 的缺省 `agent-B`、`bits` 是 `{}`。
    """
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        out = CR.upsert_legacy_shaped(tx, LEGACY, actor="agent-B")
    assert out is not None and str(out.get("stmt_id")) == "0000", out
    row = _one(store)
    assert _problems(row) == [], _problems(row)
    assert row["created_by"] == "secretary-B", row["created_by"]
    assert dict(row["bits"]), row["bits"]
    # 五元位里的那两格也要对得上（不是随便一个非空字典）
    assert row["bits"]["grade"] == "not_applicable", row["bits"]
    # 这条老行没有出处 ⇒ `origin` 按推断是"我们自己定义的新概念"，位里那一格要一致
    assert row["bits"]["origin"] == row["origin"] == "own_result", row["bits"]
    # 正文一个字不动（秘书只补它该补的那几格）
    assert row["statement_full"] == LEGACY["definition"], row["statement_full"]
    assert row["label"] == LEGACY["name"], row["label"]


def test_a_concept_written_by_upsert_takes_the_same_route(store: Store) -> None:
    """a2：另一个写口（`upsert`：独立写一条概念）落的是同一份实现。"""
    out = CR.upsert(store, label="谱", definition="矩阵的谱：使 A - λI 不可逆的那些 λ。")
    assert out.get("checked") is True, out
    row = _one(store)
    assert _problems(row) == [], _problems(row)
    assert str(row["stmt_id"]) == str(out["stmt_id"]), (row["stmt_id"], out)
    # 号仍然由分配器给、计数器仍然抬到号之后（既有行为一个字不动）
    counters = dict(store.read("counters")["counters"])
    assert counters["stmt"] == int(out["stmt_id"]) + 1, counters


# ============================================================ a3) 洗名与同一性

def test_the_write_washes_a_working_name_through_the_secretary(store: Store) -> None:
    """a3（洗名）：内部工作名在秘书那一笔里被洗掉（`conceptrows` 里没有第二份实现）。

    真机 mp3-r3 的概念行里那类标签是「F 攻坚 000000 子目标 S2」——`conceptrows`
    直写时它会被原样写进 `label`（改前这一层一次 `wash_working_name` 都没调）。
    """
    legacy = dict(LEGACY, concept_id="0001", name="F 攻坚 000000 子目标 S2",
                  normalized_name="f 攻坚 000000 子目标 s2")
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        CR.upsert_legacy_shaped(tx, legacy, actor="agent-B")
    row = _one(store)
    assert row["label"] == "有限维李代数", row["label"]
    assert "攻坚" not in row["label"], row["label"]
    # 洗名之后这一行仍然是同一个概念、仍然是秘书落的（洗名不是另一次写）
    assert row["created_by"] == "secretary-B" and dict(row["bits"]), row


def test_the_write_asks_the_concept_identity_criterion(store: Store,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """a3（概念同一性）：这一笔真的问了 `propositionkey.same_concept`，判词可读。

    打桩的是判据本体（不是另写一份假代码）：它记下被问了几次、问的是哪两个标签 ——
    于是"这一层有没有第二份同一性实现"变成一个可数的读数。
    第一条概念在空表上写（没有对手可问，问零次是对的）；第二条才是"问不问"的判据。
    """
    readings: dict = {}
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        CR.write_concept(tx, stmt_id="0000", label="有限维李代数",
                         definition=LEGACY["definition"], out=readings)
    first_identity = dict(readings.get("concept_identity") or {})
    assert first_identity.get("state") in (PK.STATE_DIFFERENT, PK.STATE_UNKNOWN), first_identity

    seen: list[tuple[str, str]] = []
    real = PK.same_concept

    def _spy(a_label, a_full="", b_label="", b_full=""):
        seen.append((str(a_label), str(b_label)))
        return real(a_label, a_full, b_label, b_full)

    monkeypatch.setattr(PK, "same_concept", _spy)
    readings2: dict = {}
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        CR.write_concept(tx, stmt_id="0001", label="finite-dimensional Lie algebra",
                         definition=LEGACY["definition"], out=readings2)
    assert seen, "写第二条概念却一次都没问同一性判据 ⇒ 这一层在直写"
    identity2 = dict(readings2.get("concept_identity") or {})
    assert identity2.get("state") == PK.STATE_SAME, identity2
    assert identity2.get("same_as") == "0000", identity2
    assert len(_rows(store)) == 2, [r.get("stmt_id") for r in _rows(store)]


# ============================================================ b) 既有行为不许退化


def test_a_duplicate_verdict_leaves_a_trace_even_without_an_out_reader(store: Store) -> None:
    """a3（同一性判词落得住）：调用方不要读数时，判到"同一个概念"也要留痕。

    为什么单列一条：`conceptrows` 那三个写口不传 `out`，于是判词没有活口 ——
    而"判过、判的是哪一行"必须留在秘书的台账上（`out/secretary/<role>.jsonl`），
    否则这一层判了等于没判（改前连判据都没有）。
    """
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        CR.upsert_legacy_shaped(tx, LEGACY, actor="agent-B")
    twin = dict(LEGACY, concept_id="0001", name="finite-dimensional Lie algebra")
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        CR.upsert_legacy_shaped(tx, twin, actor="agent-B")
    ledger = pathlib.Path(store.root) / "out" / "secretary" / "B.jsonl"
    assert ledger.is_file(), f"秘书台账没落：{ledger}"
    rows = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
    hits = [r for r in rows if str(r.get("decision")) == "concept_duplicate"]
    assert hits, rows
    target = dict(hits[-1].get("target") or {})
    assert target.get("concept") == "0001" and target.get("same_as") == "0000", target

def test_a_synced_concept_still_upgrades_and_still_merges(store: Store) -> None:
    """b（护栏）：定义到了回 `active`；老表墓碑 ⇒ `superseded` + 理由。

    两件事都是 `sync_from_legacy` 的既有行为（`D12` 甲的升档、`draft/97` §13.2 的合并）。
    接线到秘书之后它们一个字都不许丢 —— 丢了的话，概念行会在"定义已经抽到"之后
    永远停在 `pending_definition`，而合并过的那条会被下游继续当成活节点。
    """
    pending = dict(LEGACY, concept_id="0002", name="群", definition="")
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        first = CR.upsert_legacy_shaped(tx, pending, actor="agent-B")
    assert first["status"] == "pending_definition", first["status"]
    # 升档：定义到了 ⇒ active（同一行、同一个号、bits 仍在）
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        upgraded = CR.upsert_legacy_shaped(
            tx, dict(pending, definition="带运算的集合", aliases=["group"]), actor="agent-B")
    assert upgraded["status"] == "active", upgraded["status"]
    assert upgraded["aliases"] == ["group"], upgraded["aliases"]
    assert upgraded["stmt_id"] == first["stmt_id"], (upgraded, first)
    assert dict(upgraded["bits"]), upgraded["bits"]

    # 合并：老表的墓碑落成新标准的 superseded（且理由写得出来）
    dead = dict(LEGACY, concept_id="0003", name="阿贝尔群", definition="交换群",
                merged_into="0002", merge_reason="结构等价 + 名字侧证据")
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        merged = CR.upsert_legacy_shaped(tx, dead, actor="agent-B")
    assert merged["status"] == "superseded", merged["status"]
    assert "0002" in merged["quote_reason"], merged["quote_reason"]
    assert merged["status"] in S.STATEMENT_UNUSABLE_STATUSES, merged["status"]


# ============================================================ c) 反真空

def test_stubbing_the_route_back_to_a_direct_write_turns_the_reading_red(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """c（反真空）：把接线打桩成"直写回去"（= 改前那一笔）⇒ a 的断言必红。

    打桩的就是"经秘书"这件事本身（`Secretary.write_concept_row` 换成改前那句
    `tx.upsert("statements", concept_statement(...))`），所以 a 的绿只能由接线带来，
    不是"这些字段本来就是满的"。
    """
    def _old_direct_write(self, tx, *, stmt_id, label, definition="", aliases=(),
                          source_lit_id="", doc_id="", origin="", self_authored=False,
                          mirror=False, existing=None, status="", quote_reason="",
                          proof_text="", out=None):
        # 改前那一笔逐字：构造 + 直写（没有 bits、没有洗名、没有同一性）
        data = CR.concept_statement(stmt_id=stmt_id, label=label, definition=definition,
                                    aliases=aliases, source_lit_id=source_lit_id,
                                    doc_id=doc_id, actor="agent-B", origin=origin,
                                    self_authored=self_authored).to_dict()
        tx.upsert("statements", data, note="concept_sync:create")
        return data

    monkeypatch.setattr(SEC.Secretary, "write_concept_row", _old_direct_write, raising=True)
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        CR.upsert_legacy_shaped(tx, LEGACY, actor="agent-B")
    row = _one(store)
    problems = _problems(row)
    assert problems != [], "直写回去之后 a 的断言居然还是绿的 ⇒ 那组断言不是对着接线"
    assert any("bits" in p for p in problems), problems
    assert any("created_by" in p for p in problems), problems
    assert row["created_by"] == "agent-B", row["created_by"]

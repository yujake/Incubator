# -*- coding: utf-8 -*-
"""SYSGUARD：系统自动产物的写点自己保证每一格（业主 2026-11-21 推论）。

## 这一份钉的是什么

业主裁定：「V 或 V 秘书理论上不会亲自写 V 签，所以 V 签几乎是系统自动操作」；
推论（SIGNMAL 事故证实）：系统自己自动产出的字段与文件，必须由系统保证每一格 ——
不能让模型补，也不能靠读侧宽容。

SIGNMAL 的形态是：框架在写口漏写一格（`object_sha256` 没传），模型全程没有机会
发现异常，而三处签读口全放行。本文件守的是同一形态在另外四个写口上的复现：

| 判据 | 写点 | 改前（静默） | 改后 |
|---|---|---|---|
| a1 | `artifacts.record` | 框架现算的 `sha256` / `bytes` / `at` 坏了照写 | 受控拒（`artifact_entry_bad`） |
| a2 | `litstage.clear_delegation` | `cleared_at` / `clear_reason` 空着也落盘 | 受控拒（`clear_cells_incomplete`） |
| a3 | `secretary_retire.retire` | 调用方没给 `reason` ⇒ 销号行 `reason=""` | 同处补值（`retired_reason_derived`） |
| a4 | `agent_b._finish_reprocess` | 改 `quote` 只重算 `dedup_key`，`quote_normalized` 留旧值 | 受控拒（`relation_derived_cell_stale`） |
| a5 | `modelcost.charge_reply` | 省 `call_index` ⇒ 缺省 0 ⇒ 第二笔静默判成重放 | 首笔补 0、其余受控拒（`call_index_missing`） |

每一条都配：b 正控（正常写入照旧，盘上不多字段）、c 三态（读不到读数记
`unchecked`，不折成 ok）、d 反真空（把判据打桩掉 ⇒ 对应夹具变回静默）。

## 为什么断言落在"读数"上

写点拒了/补了之后，下一次读的人（人、`stats errors`、验收）要看得见它。所以每一
条都断言 `out/sysguard/write-readings.jsonl` 那一行的 `state` / `code`，而不只看
返回值 —— 一条"拒了但没留痕"的写点，与"没拒"在下一次盘点时长得一模一样。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import artifacts as ART
from agentflow import litstage as L
from agentflow import modelcost as MC
from agentflow import schema as S
from agentflow import secretary_retire as SR
from agentflow import sysguard as SG
from agentflow.agent_b import core as bcore
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.errorstats import _read_aux, error_action_stats_from
from agentflow.extract import extract_text
from agentflow.secretary import Secretary, retired_path
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry
from agentflow.agent_b.core import AgentB

from conftest import TS, add_literature, write_library_file

LIT = "000000"
QUOTE = "An abelian group is a group in which the commutative law holds."
RID = "r-000001"


# ====================================================================== 读数（c）

def test_c_a_missing_ledger_is_empty_not_unchecked(tmp_path: pathlib.Path) -> None:
    """c1：台账不存在 = 这一趟没有写点判据落过痕（empty，checked=True）。"""
    rows, bad, state = SG.read_readings(tmp_path)
    assert (rows, bad, state) == ([], [], "empty")
    assert SG.readings_summary(tmp_path)["checked"] is True


def test_c_an_unreadable_ledger_is_unchecked_not_ok(tmp_path: pathlib.Path) -> None:
    """c2：文件在、读不出来 ⇒ `unreadable` + checked=False（绝不折成 ok/empty）。"""
    path = SG.readings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00 not utf-8")
    rows, bad, state = SG.read_readings(tmp_path)
    assert state == "unreadable" and bad, (rows, bad, state)
    assert SG.readings_summary(tmp_path)["checked"] is False


def test_c_a_bad_line_is_reported_and_good_lines_still_count(tmp_path: pathlib.Path) -> None:
    """c3：坏行逐条报出，好行照数（与 `artifacts.summarize` 同一手法）。"""
    ok, problem = SG.record_reading(tmp_path, SG.refused("x.record", code="c1", where="w"))
    assert problem == "" and ok["state"] == SG.REFUSED
    path = SG.readings_path(tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{这不是 JSON\n")
    rows, bad, state = SG.read_readings(tmp_path)
    assert len(rows) == 1 and len(bad) == 1 and state == "malformed", (rows, bad, state)


# ============================================================ ① artifacts.record

def _artifact_file(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    target = root / "reports" / "r.md"
    target.write_text("内容一", encoding="utf-8")
    return root


def test_b_artifacts_record_writes_all_framework_cells_from_one_read(
        tmp_path: pathlib.Path) -> None:
    """b（正控）：正常登记照旧；sha/bytes 同一次读，盘上不多字段。"""
    root = _artifact_file(tmp_path)
    entry = ART.record(root, path="reports/r.md", producer="G", kind="report")
    assert set(entry) == set(ART.FIELDS), sorted(set(entry) ^ set(ART.FIELDS))
    assert len(entry["sha256"]) == 64 and entry["sha256"] == ART.sha256_of(
        root / "reports" / "r.md")
    assert entry["bytes"] == len("内容一".encode("utf-8"))
    assert ART.verify_entries(root)[0]["status"] == "ok"
    # 正常路径不写读数（台账不被正常写入灌满）
    assert SG.read_readings(root)[0] == []


def test_a1_a_broken_framework_cell_is_refused_with_a_code(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a（改前静默）：框架现算的 sha 坏了 ⇒ 受控拒 + 理由码，台账一个字节不写。"""
    root = _artifact_file(tmp_path)
    monkeypatch.setattr(ART, "_fingerprint", lambda p: ("", 0))
    with pytest.raises(ART.ArtifactError) as exc:
        ART.record(root, path="reports/r.md", producer="G")
    assert "sha256" in str(exc.value), str(exc.value)
    assert not ART.ledger_path(root).exists(), "被拒的登记不许落盘"
    rows = SG.read_readings(root)[0]
    assert [(r["state"], r["code"]) for r in rows] == [("refused", "artifact_entry_bad")], rows


def test_d1_stubbing_the_entry_guard_brings_back_the_silent_bad_line(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d（反真空）：把 `entry_problems` 打桩成"永远合格" ⇒ 空 sha 照写（= 改前）。"""
    root = _artifact_file(tmp_path)
    real_fp = ART._fingerprint
    monkeypatch.setattr(ART, "_fingerprint", lambda p: ("", 0))
    monkeypatch.setattr(ART, "entry_problems", lambda entry: [])
    entry = ART.record(root, path="reports/r.md", producer="G")
    assert entry["sha256"] == "" and entry["bytes"] == 0
    monkeypatch.setattr(ART, "_fingerprint", real_fp)
    assert ART.verify_entries(root)[0]["status"] == "changed", "空 sha 竟然被判成 ok"


# ====================================================== ② litstage.clear_delegation

def _candidates(store: Store, *, n: int = 2) -> list[str]:
    """造一张本委托的待新增表（`admitted` 行仍可能没清表 —— MALFORM 的那 38 条）。"""
    slots = []
    with store.tx("lit_candidates", actor="test", note="fx:sysguard") as tx:
        for i in range(n):
            slot = f"{i + 1:06d}"
            row = S.LitCandidate(slot=slot, batch=1, status="admitted", title=f"题名 {i}",
                                 request_id=RID, lit_id=f"{i:06d}",
                                 relevance="与本次检索相关", admitted_at=TS)
            row.validate()
            tx.upsert("lit_candidates", row.to_dict())
            slots.append(slot)
    return slots


def _cand(store: Store, slot: str) -> dict:
    return next(dict(r) for r in store.rows("lit_candidates") if r.get("slot") == slot)


def test_b_clear_writes_both_cells_and_keeps_the_archive_in_step(store: Store) -> None:
    """b（正控）：正常清表照旧 —— 两格都写上，归档覆盖整份行，不多字段。"""
    slots = _candidates(store)
    got = L.clear_delegation(store, RID, reason="本批已交报告并入库")
    assert got["cleared"] == 2 and got["archived"]["count"] == 2, got
    for slot in slots:
        row = _cand(store, slot)
        assert row["cleared_at"] and row["clear_reason"] == "本批已交报告并入库", row
        assert "clear_reason" in row
    path = L.archive_path(store, RID)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert SG.read_readings(store.root)[0] == []


def test_a2_an_empty_clear_cell_is_refused_before_anything_is_written(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """a（改前静默）：`reason` 与默认理由同时为空 ⇒ 受控拒，盘上一个字节不动。"""
    slots = _candidates(store)
    monkeypatch.setattr(L, "CLEAR_REASON", "")
    with pytest.raises(L.LitStageError) as exc:
        L.clear_delegation(store, RID, reason="")
    assert exc.value.kind == "clear_incomplete", exc.value.kind
    for slot in slots:
        assert _cand(store, slot)["cleared_at"] == "", "被拒的清表不许改盘"
    assert not L.archive_path(store, RID).exists(), "被拒的清表不许先写归档"
    rows = SG.read_readings(store.root)[0]
    assert [(r["state"], r["code"]) for r in rows] == [("refused", "clear_cells_incomplete")]


def test_d2_stubbing_the_clear_guard_brings_back_the_empty_cells(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """d（反真空）：把清表判据打桩掉 ⇒ 空 `clear_reason` 照落盘（= 改前）。"""
    _candidates(store)
    monkeypatch.setattr(L, "CLEAR_REASON", "")
    monkeypatch.setattr(L, "_cleared_cells_problems", lambda rows: [])
    L.clear_delegation(store, RID, reason="")
    assert _cand(store, "000001")["clear_reason"] == "", "打桩之后应当是静默空串"
    assert _cand(store, "000001")["cleared_at"], "时间那一格仍在（只漏了理由）"


# =================================================== ③ secretary_retire 的 reason

def _workspace(tmp_path: pathlib.Path) -> dict[str, object]:
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：销号理由写点"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, parent: str) -> str:
    return cond._write_new_row({
        "role": "D", "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2,
        "input_key": "fx2:D:done:retire-reason", "status": "done",
        "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "夹具子代理", "error": None, "started_at": TS, "ended_at": TS,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="fixture:sysguard-retire")


def _rows_at(path: pathlib.Path) -> list[dict]:
    import json

    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _retire(env: dict[str, object], **kwargs: object) -> dict:
    reg = ToolRegistry(name="fx3")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(str(env["owner"]), "M"):
        got = reg.call("conductor.retire_child", dict(kwargs), role="M")
    return dict(got.data or {})


def test_a3_a_retire_without_a_reason_fills_it_at_the_write_point(
        tmp_path: pathlib.Path) -> None:
    """a（改前静默空串）：调用方没给 reason ⇒ 销号行那一格由写点补，且留读数。"""
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    child = _child(env["cond"], owner)          # type: ignore[arg-type]
    name = str(env["sec"].roster_add(owner=owner, role="D", task_id=child,   # type: ignore[union-attr]
                                     brief="写研究报告")["name"])
    data = _retire(env, child_name=name)
    assert data.get("state") == "retired", data
    rows = _rows_at(retired_path(env["root"], owner))
    assert rows and all(str(r.get("reason") or "").strip() for r in rows), rows
    assert "销号退场" in str(rows[0]["reason"]), rows[0]["reason"]
    readings = SG.read_readings(env["root"])[0]
    assert [(r["state"], r["code"]) for r in readings] == [
        ("derived", "retired_reason_derived")], readings


def test_b_an_explicit_reason_is_used_verbatim_and_adds_no_noise(
        tmp_path: pathlib.Path) -> None:
    """b（正控）：调用方给了理由就照用；不多一个字段、不多一条读数。"""
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    child = _child(env["cond"], owner)          # type: ignore[arg-type]
    name = str(env["sec"].roster_add(owner=owner, role="D", task_id=child,   # type: ignore[union-attr]
                                     brief="写研究报告")["name"])
    data = _retire(env, child_name=name, reason="活交完了，不再需要")
    assert data.get("state") == "retired", data
    rows = _rows_at(retired_path(env["root"], owner))
    assert [r["reason"] for r in rows] == ["活交完了，不再需要"], rows
    assert set(rows[0]) == {"owner", "name", "task_id", "role", "at", "reason",
                            "branch", "seq"}, rows[0]
    assert SG.read_readings(env["root"])[0] == []


def test_d3_stubbing_the_reason_fill_brings_back_the_empty_reason() -> None:
    """d（反真空）：补值函数被绕开时，销号行的理由回到空串（= 改前形态）。"""
    assert SR.retire_reason("child_stopped", "t-000001")
    assert SR.retire_reason("", "") == "销号退场：父决定销号"


# ============================================== ④ reprocess 的派生两格（relations）

def _reprocess_relation(store: Store) -> dict:
    add_literature(store, LIT, title="仅题录", path=None,
                   download={"status": "failed", "fulltext": "metadata_only"})
    row = S.Relation(relation_id="0000", concept_ids=[LIT, "000001"],
                     description="阿贝尔群是交换群", lit_id=LIT,
                     page_range=S.PageRange(1, 1, "p. 1"), quote="旧引文",
                     quote_normalized="", quote_verified=None,
                     statement="阿贝尔群是交换群", concept_group_key=f"{LIT}|000001",
                     dedup_key="k-stale", status="active", created_at=TS)
    row.validate()
    with store.tx("relations", actor="test") as tx:
        tx.upsert("relations", row.to_dict())
    with store.tx("reprocess_requests", actor="test") as tx:
        tx.upsert("reprocess_requests", S.ReprocessRequest(
            reprocess_id="p-0001", timestamp=TS, reason="quote_unverifiable",
            submitted_by="agent-C", relation_ids=["0000"], status="pending",
            touched_relation_ids=[]).to_dict())
    return row.to_dict()


def _outcome(store: Store, upd: dict) -> dict:
    live = next(dict(r) for r in store.rows("relations") if r["relation_id"] == "0000")
    return {"result": "found", "note": "夹具", "updates": {"0000": dict(upd)},
            "fingerprints": {"0000": {k: live.get(k) for k in
                                      ("quote", "statement", "description")}}}


def _request_row(store: Store) -> dict:
    return next(dict(r) for r in store.rows("reprocess_requests")
                if r["reprocess_id"] == "p-0001")


def _relation_now(store: Store) -> dict:
    return next(dict(r) for r in store.rows("relations") if r["relation_id"] == "0000")


def test_a4_a_quote_change_that_leaves_the_derived_cell_stale_is_refused(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """a（改前静默）：改 `quote` 而 `quote_normalized` 没跟着重算 ⇒ 整笔不写 + 读数。

    注入方式：让 `normalize_for_quote` 在"写点重算"那一次给对、在"判据复核"那一次
    给空 —— 等价于框架漏了重算那一行。
    """
    _reprocess_relation(store)
    agent = AgentB(store, extractor=object(), extract_text=extract_text)
    real = bcore.T.normalize_for_quote
    calls = {"n": 0}

    def _flaky_via_core(text: str) -> str:
        calls["n"] += 1
        return real(text) if calls["n"] <= 1 else ""

    monkeypatch.setattr(bcore.T, "normalize_for_quote", _flaky_via_core)
    out = agent._finish_reprocess(_request_row(store), _outcome(store, {"quote": QUOTE}))
    row = _relation_now(store)
    assert out["touched_relation_ids"] == [], out
    assert row["quote"] == "旧引文", "被拒的那一笔不许改行"
    assert out["refused_targets"], out
    codes = [(r["state"], r["code"]) for r in SG.read_readings(store.root)[0]]
    assert ("refused", "relation_derived_cell_stale") in codes, codes


def test_b_a_quote_change_recomputes_both_derived_cells(
        store: Store) -> None:
    """b（正控）：正常改 `quote` ⇒ 两格同源重算，读侧不必再靠 `or 现算` 兜底。"""
    _reprocess_relation(store)
    agent = AgentB(store, extractor=object(), extract_text=extract_text)
    out = agent._finish_reprocess(_request_row(store), _outcome(store, {"quote": QUOTE}))
    assert out["touched_relation_ids"] == ["0000"], out
    row = _relation_now(store)
    assert row["quote"] == QUOTE
    assert row["quote_normalized"] == bcore.T.normalize_for_quote(QUOTE)
    assert row["dedup_key"] == bcore.D.relation_dedup_key(f"{LIT}|000001", QUOTE)
    assert SG.read_readings(store.root)[0] == []


def test_d4_stubbing_the_derived_guard_brings_back_the_stale_cell(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """d（反真空）：把派生格判据打桩掉 ⇒ 旧值留在行上（= 改前）。"""
    _reprocess_relation(store)
    agent = AgentB(store, extractor=object(), extract_text=extract_text)
    real = bcore.T.normalize_for_quote
    calls = {"n": 0}

    def _flaky_via_core(text: str) -> str:
        calls["n"] += 1
        return real(text) if calls["n"] <= 1 else ""

    monkeypatch.setattr(bcore.T, "normalize_for_quote", _flaky_via_core)
    monkeypatch.setattr(bcore, "_relation_derived_cells_problems", lambda row: [])
    out = agent._finish_reprocess(_request_row(store), _outcome(store, {"quote": QUOTE}))
    assert out["touched_relation_ids"] == ["0000"], out
    row = _relation_now(store)
    assert row["quote_normalized"] == "", "打桩之后应当是静默空串（= 改前）"


# ================================================= ⑤ usage_ledger 的 call_index

def _reply(tokens_in: int = 10, tokens_out: int = 5):
    from agentflow.modelgw import ModelReply

    return ModelReply(ok=True, text="ok", tokens_in=tokens_in, tokens_out=tokens_out,
                      model="m", scope="reason")


def test_b_the_first_charge_without_an_index_fills_zero_and_says_so(
        store: Store) -> None:
    """b（正控 + 补值唯一确定的情形）：账上没有账 ⇒ 序号 0 确定，补它并留读数。"""
    from agentflow.tokenmeter import TokenMeter

    meter = TokenMeter(store)
    out = MC.charge_reply(meter, _reply(), task_id="t-0001", scope="reason", now=TS)
    assert out["charged"] is True, out
    assert len(store.rows("usage_ledger")) == 1
    readings = [(r["state"], r["code"]) for r in SG.read_readings(store.root)[0]]
    assert readings == [("derived", "call_index_derived")], readings


def test_a5_a_second_charge_without_an_index_is_refused_not_read_as_a_replay(
        store: Store) -> None:
    """a（改前静默）：第二笔省序号 ⇒ 受控拒 + 读数；账上不多不少一行。"""
    from agentflow.tokenmeter import TokenMeter

    meter = TokenMeter(store)
    MC.charge_reply(meter, _reply(), task_id="t-0001", scope="reason", now=TS)
    with pytest.raises(ValueError) as exc:
        MC.charge_reply(meter, _reply(), task_id="t-0001", scope="reason", now=TS)
    assert "call_index" in str(exc.value), str(exc.value)
    assert len(store.rows("usage_ledger")) == 1, "被拒的那一笔不许入账"
    codes = [(r["state"], r["code"]) for r in SG.read_readings(store.root)[0]]
    assert ("refused", "call_index_missing") in codes, codes


def test_b_explicit_indices_still_land_two_rows(store: Store) -> None:
    """b（正控）：显式给序号 ⇒ 两笔各一行，不多读数。"""
    from agentflow.tokenmeter import TokenMeter

    meter = TokenMeter(store)
    for i in (0, 1):
        out = MC.charge_reply(meter, _reply(), task_id="t-0001", call_index=i,
                              scope="reason", now=TS)
        assert out["charged"] is True, out
    assert len(store.rows("usage_ledger")) == 2
    assert SG.read_readings(store.root)[0] == []


def test_d5_stubbing_the_index_guard_brings_back_the_silent_duplicate(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """d（反真空）：把序号判据打桩回旧的缺省 0 ⇒ 第二笔静默判成重放（不入账）。"""
    from agentflow.tokenmeter import TokenMeter

    monkeypatch.setattr(MC, "resolve_call_index",
                        lambda meter, scope, call_index: int(call_index or 0))
    meter = TokenMeter(store)
    first = MC.charge_reply(meter, _reply(), task_id="t-0001", scope="reason", now=TS)
    second = MC.charge_reply(meter, _reply(), task_id="t-0001", scope="reason", now=TS)
    assert first["charged"] is True
    assert second["charged"] is False and second["reason"] == "duplicate", second
    assert len(store.rows("usage_ledger")) == 1, "旧口径下第二笔根本没收钱"


# ============================================== 读数进 errorstats（过程读数那格）

def test_the_write_point_readings_are_visible_in_errorstats(tmp_path: pathlib.Path) -> None:
    """读数看得见：拒收/补值进 `write_point_guarded`（过程读数，不进错误合计）。"""
    root = tmp_path / "ws"
    root.mkdir()
    SG.record_reading(root, SG.refused("litstage.clear_delegation",
                               code="clear_cells_incomplete", where="w"))
    SG.record_reading(root, SG.derived("secretary_retire.retire",
                               code="retired_reason_derived", where="w"))
    stats = error_action_stats_from([], {"checked": True}, [], {"checked": True},
                                    aux=_read_aux(root))
    assert stats.process.get("（系统）", {}).get("write_point_guarded") == 2, stats.process
    assert stats.class_state["write_point_guarded"]["state"] == "checked"
    # 它不进"错误动作发生次数"
    assert "write_point_guarded" not in stats.categories()


def test_without_the_aux_source_the_new_category_is_unknown(tmp_path: pathlib.Path) -> None:
    """三态：不传辅助源 ⇒ 这一类是 unknown，不是 0。"""
    stats = error_action_stats_from([], {"checked": True}, [], {"checked": True})
    assert stats.class_state["write_point_guarded"]["state"] == "unknown"
    assert stats.class_state["write_point_guarded"]["checked"] is False

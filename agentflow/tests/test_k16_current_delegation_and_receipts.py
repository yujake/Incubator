# -*- coding: utf-8 -*-
"""K16 判据：A 的「当前委托」按实例、回读回执落盘且带实例、报告写者按实例落。

## 三条读数（`MASTER-INVENTORY` K16：AL-02 / AL-06 / AL-07+AL-08）

| # | 判据 | 改前为什么红 |
|---|---|---|
| c | 第二个 A 实例的「当前委托」不是第一个实例的那一份；它自己点名过的委托才算它的 | `litstage.current_request_id` 取全表槽位最大那一行 ⇒ 谁最后暂存谁说了算，第二个实例读到的永远是第一个的委托 |
| c′ | 反真空：把实例过滤打桩成"返回全部委托" ⇒ c 的读数必红（第二个实例又读到第一个的） | 证明 c 的绿来自实例过滤，不是来自"夹具恰好只造了一份委托" |
| d | 回读回执跨进程可见：写回执的进程退出之后，另一个进程按 `(实例, 委托)` 读得到 | 回执是 `_READBACKS[(root, request_id)]` 进程内字典，另一个进程读到 `None` |
| d′ | 回执按实例分开：另一个实例读同一委托 ⇒ 读不到我的回执 | 键里没有实例轴（AL-06 的交错形态：A2 的 `stage_add` 会作废 A1 的回执） |
| e | 报告写者按实例落：报告头写着 `- 写者：agent-A-<实例>`，回执给出 `writer` / `previous_writer` | 报告头只有委托号 / 状态 / 时间，回答不了"这一版是谁渲染的"（AL-08） |
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

from agentflow import identity as IDENT
from agentflow import litstage as L
from agentflow import schema as S
from agentflow.conductor import calling_as
from agentflow.store import Store

WORKER = pathlib.Path(__file__).resolve().parent / "_k16_mp_worker.py"

#: 两个 A 实例（真机 lp-ball-8 的两个写者：`agent-A-lit` / `agent-A-A2`）。
INST_A = "lit"
INST_B = "A2"


# --------------------------------------------------------------------- 夹具


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _request(st: Store, rid: str, *, submitted_by: str) -> None:
    """一行检索请求（「这个实例名下有哪几个委托」的唯一来源是它）。"""
    with st.tx("search_requests", actor=submitted_by, note="K16 夹具") as tx:
        tx.upsert("search_requests", S.SearchRequest(
            request_id=rid, timestamp="2026-11-19T00:00:00+08:00",
            topic=f"K16 夹具 {rid}", mode="broad", submitted_by=submitted_by).to_dict())


def _entries(tag: str, n: int = 2) -> list[dict]:
    return [{"title": f"{tag} 候选 {i}", "doi": f"10.9/{tag}/{i}", "provider": "stub",
             "year": 2020 + i, "type_code": "J",
             "relevance": f"与本次检索相关（{tag}-{i}）"} for i in range(n)]


def _stage(st: Store, rid: str, tag: str, n: int = 2) -> list[str]:
    got = L.stage_entries(st, _entries(tag, n), request_id=rid, actor="agent-A")
    return [str(row.get("slot") or "") for row in got["staged"]]


# --------------------------------------------------------------------- c


def test_c_second_instance_does_not_read_the_first_instances_delegation(
        tmp_path: pathlib.Path):
    """A1 的委托 r-000001 有行；A2 的 r-000002 还没有行 ⇒ A2 的当前委托不是 r-000001。"""
    st = _ws(tmp_path)
    _request(st, "r-000001", submitted_by=f"agent-A-{INST_A}")
    _request(st, "r-000002", submitted_by=f"agent-A-{INST_B}")
    first = _stage(st, "r-000001", "甲")

    with calling_as("t-a-lit", "A", instance=INST_A):
        mine = L.list_candidates(st)
        assert mine["current_request_id"] == "r-000001", mine["current_request_id"]
        assert [r["slot"] for r in mine["rows"]] == first

    with calling_as("t-a-a2", "A", instance=INST_B):
        other = L.list_candidates(st)
        assert other["current_request_id"] == "", (
            "第二个实例把第一个实例的委托当成了自己的当前委托："
            f"{other['current_request_id']!r}")
        assert other["rows"] == [], f"第二个实例读到了第一个实例的候选：{other['rows']}"
        # 点过自己的委托之后，当前委托就是它自己的那一份。
        second = _stage(st, "r-000002", "乙")
        after = L.list_candidates(st)
        assert after["current_request_id"] == "r-000002", after["current_request_id"]
        assert [r["slot"] for r in after["rows"]] == second


def test_c_prime_anti_vacuum_the_instance_filter_is_load_bearing(
        tmp_path: pathlib.Path, monkeypatch):
    """反真空：把实例过滤打桩成"返回全部委托" ⇒ c 的读数必红。"""
    st = _ws(tmp_path)
    _request(st, "r-000001", submitted_by=f"agent-A-{INST_A}")
    _request(st, "r-000002", submitted_by=f"agent-A-{INST_B}")
    _stage(st, "r-000001", "甲")
    # `_resolve_request` 也走同一处：没有自己的委托时它是受控拒，不是借用别人的。
    with calling_as("t-a-none", "A", instance="nobody"):
        try:
            L._resolve_request(st, None)
        except L.LitStageError as exc:
            assert exc.kind == "no_delegation", exc.kind
        else:  # pragma: no cover - 不借用别人的委托是这一条的不变量
            raise AssertionError("没有自己委托的实例居然解析出了一个委托")

    monkeypatch.setattr(
        L, "_instance_request_ids",
        lambda _store, _instance: {"r-000001", "r-000002"})
    with calling_as("t-a-a2", "A", instance=INST_B):
        got = L.list_candidates(st)
    assert got["current_request_id"] == "r-000001", (
        "把实例过滤打桩成「返回全部委托」之后 c 仍然绿 ⇒ c 量的不是实例过滤")


# --------------------------------------------------------------------- d


def _read_receipt_in_another_process(ws: pathlib.Path, rid: str, instance: str,
                                     tmp_path: pathlib.Path) -> dict:
    result = tmp_path / f"receipt-{instance or 'none'}.json"
    log = (tmp_path / f"receipt-{instance or 'none'}.log").open("wb")
    with log:
        proc = subprocess.Popen(  # noqa: S603 - 脚本与参数都是本文件给的字面量
            [sys.executable, str(WORKER), "--root", str(ws),
             "--request-id", rid, "--instance", instance, "--result", str(result)],
            stdout=log, stderr=subprocess.STDOUT)
    assert proc.wait(timeout=120) == 0, (
        (tmp_path / f"receipt-{instance or 'none'}.log").read_text(
            encoding="utf-8", errors="replace")[-2000:])
    assert result.is_file(), "工作进程没有留下结果文件"
    return json.loads(result.read_text(encoding="utf-8"))


def test_d_readback_receipt_survives_the_writing_process(tmp_path: pathlib.Path):
    """写回执的进程退出之后，另一个进程按 `(实例, 委托)` 读得到它。"""
    st = _ws(tmp_path)
    _request(st, "r-000001", submitted_by=f"agent-A-{INST_A}")
    slots = _stage(st, "r-000001", "甲")
    with calling_as("t-a-lit", "A", instance=INST_A):
        rows = L.list_candidates(st)["rows"]
        rec = L.note_readback(st, "r-000001", rows)
        assert rec.get("instance") == INST_A, rec

    got = _read_receipt_in_another_process(st.root, "r-000001", INST_A, tmp_path)
    assert got["ok"] and got["found"], got
    assert got["instance"] == INST_A, got
    assert got["slots"] == sorted(slots), got


def test_d_prime_a_receipt_belongs_to_the_instance_that_read_it(tmp_path: pathlib.Path):
    """另一个实例读同一委托 ⇒ 读不到我的回执（回执的键带实例轴）。"""
    st = _ws(tmp_path)
    _request(st, "r-000001", submitted_by=f"agent-A-{INST_A}")
    _request(st, "r-000002", submitted_by=f"agent-A-{INST_B}")  # B 有它自己的委托
    _stage(st, "r-000001", "甲")                                # A 读的这一份
    _stage(st, "r-000002", "乙")                                # B 也有行（夹具用）
    with calling_as("t-a-lit", "A", instance=INST_A):
        L.note_readback(st, "r-000001", L.list_candidates(st)["rows"])
        assert L.readback_receipt(st, "r-000001") is not None
    with calling_as("t-a-a2", "A", instance=INST_B):
        assert L.readback_receipt(st, "r-000001") is None, (
            "另一个实例读到了我的回读回执 ⇒ 回执的键没有实例轴")
        # 它自己的 stage_add 也只作废自己的回执，不动别人的。
        L._drop_readback(st, "r-000001")
    with calling_as("t-a-lit", "A", instance=INST_A):
        assert L.readback_receipt(st, "r-000001") is not None, (
            "另一个实例的 stage_add 把我（A1）的回执作废了 —— AL-06 的交错形态")


# --------------------------------------------------------------------- e


def test_e_the_report_header_names_the_instance_that_rendered_it(tmp_path: pathlib.Path):
    """报告头写着这一版的写者；回执给出 writer / previous_writer。"""
    st = _ws(tmp_path)
    _request(st, "r-000001", submitted_by=f"agent-A-{INST_A}")
    _stage(st, "r-000001", "甲")

    with calling_as("t-a-lit", "A", instance=INST_A):
        first = L.write_report(st, "r-000001", phase="draft")
        assert first["writer"] == f"agent-A-{INST_A}", first
        assert first["writer_instance"] == INST_A, first
        text = pathlib.Path(first["path"]).read_text(encoding="utf-8")
        assert f"- 写者：agent-A-{INST_A}" in text, text[:400]

    with calling_as("t-a-a2", "A", instance=INST_B):
        again = L.write_report(st, "r-000001", phase="draft")
        assert again["writer"] == f"agent-A-{INST_B}", again
        assert again["previous_writer"] == f"agent-A-{INST_A}", (
            f"回执没说这一版覆盖了谁那一版：{again}")
        text = pathlib.Path(again["path"]).read_text(encoding="utf-8")
        assert f"- 写者：agent-A-{INST_B}" in text, text[:400]
        assert f"- 写者：agent-A-{INST_A}" not in text, "重渲染之后旧写者还留在报告头上"


def test_e_prime_no_identity_is_recorded_as_unrecorded_not_invented(tmp_path: pathlib.Path):
    """没有身份的那一档（直调 / 夹具）报告头写"未记"，不编一个实例出来。"""
    st = _ws(tmp_path)
    _request(st, "r-000001", submitted_by=f"agent-A-{INST_A}")
    _stage(st, "r-000001", "甲")
    IDENT.set_current_instance("")
    got = L.write_report(st, "r-000001", phase="draft")
    text = pathlib.Path(got["path"]).read_text(encoding="utf-8")
    assert "- 写者：agent-A" in text, text[:400]
    assert "- 写者实例：（未记）" in text, text[:400]

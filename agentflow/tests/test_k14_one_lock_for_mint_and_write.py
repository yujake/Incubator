# -*- coding: utf-8 -*-
"""K14 判据：取号与读-改-写必须在同一把跨进程锁里；并发豁免不许按角色给。

## 这一簇的五条读数（`MASTER-INVENTORY` K14：VJ-02 / HR-01 / SH-05）

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 两个真进程同时往同一份 pending 台账落签 ⇒ 两个号、两轮（1 / 2），不许撞号、不许丢轮 | `verifications.record_pending_sign` 是「读行 → 取号 → 追加」三段，全在锁外：两个进程都读到空台账、都发 `u-000001`、round 都写 1 |
| a′ | 反真空：把修后那把跨进程锁换成 `nullcontext` ⇒ a 的读数必红（撞号复现） | 证明 a 的绿来自那把锁，不是来自"装置没把窗口拉开" |
| b | 同一角色、两个不同实例、写集相交在一张没有行级互斥的表上 ⇒ 两波（不许按角色豁免） | `policy._same_role_other_instance` 只看角色/实例两格，`estimate_write_conflict` 因此返回 False，两个 H 实例会同时改同一份稿的 `review_findings` |
| b′ | 有行级互斥的正控：两个 E 实例（`experiments` 行级归属）仍然同波 | 修法不是"全串行"：豁免要以「行级互斥确实存在」为条件（SH-05 的原话） |
| c | 两个真进程同时复审同一份稿 ⇒ `review_rounds` 1 → 2（不丢轮）、同键发现只落一行 | `_advance_review_round` 读 `current` 在事务外、`record_finding` 的判重在事务外：两个进程各读 0、各写 1；各读"没有这条"、各落一行 |

a / c 用的是真进程（`tests/_k14_mp_worker.py`）：这两个洞的形态就是"两个进程各有一份
内存视图"，用同进程的线程替身证明不了跨进程锁真的在起作用（`store.tx` 的 `FileLock`
在同一个解释器里的行为与跨进程不同）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agentflow import policy as P
from agentflow import scheduler as SC
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.store import Store

WORKER = Path(__file__).resolve().parent / "_k14_mp_worker.py"

#: 取号窗口放大的时长（秒）：持锁的进程睡够这么久，另一个进程必然已经走到取号点。
HOLD = 1.5


# --------------------------------------------------------------------- 读数


def _pending_rows(ws: Path) -> list[dict]:
    """pending 目录下全部行（跨文件摊平；行序按文件名 + 追加序）。"""
    base = VR.pending_dir(ws)
    out: list[dict] = []
    if not base.is_dir():
        return out
    for path in sorted(base.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _a_problems(ws: Path, payloads: list[dict]) -> list[str]:
    """a 的读数：撞号 / 丢轮。空列表 = 成立。"""
    problems: list[str] = []
    if not all(p.get("ok") for p in payloads):
        problems.append(f"有进程没写成（装置故障不是结论）：{payloads}")
        return problems
    ids = [str(p.get("verification_id") or "") for p in payloads]
    if len(set(ids)) != len(ids):
        problems.append(f"两个进程发了同一个 pending 号：{ids}")
    rounds = sorted(int(p.get("round") or 0) for p in payloads)
    if rounds != [1, 2]:
        problems.append(f"轮次不是 1 / 2（丢了一轮）：{rounds}")
    rows = _pending_rows(ws)
    if len(rows) != 2:
        problems.append(f"盘上 pending 行数 {len(rows)} ≠ 写成的份数 2")
    row_ids = [str(r.get("verification_id") or "") for r in rows]
    if len(set(row_ids)) != len(row_ids):
        problems.append(f"盘上出现同号两行：{row_ids}")
    return problems


# --------------------------------------------------------------------- 装置


def _run_pair(base: Path, *, mode: str, extra: list[str] | None = None,
              tag: str = "") -> tuple[Path, list[dict]]:
    """起两个真进程跑同一个工作区，返回 `(工作区, 各进程结果)`。

    结果与同步信号一律走文件（受限执行环境里管道是明确的失败面）。
    """
    ws = base / f"ws{tag}"
    ws.mkdir(parents=True, exist_ok=True)
    results = base / f"results{tag}"
    results.mkdir(parents=True, exist_ok=True)
    barrier = base / f"barrier{tag}"
    procs: list[subprocess.Popen] = []
    for i in range(2):
        cmd = [sys.executable, str(WORKER),
               "--mode", mode,
               "--root", str(ws),
               "--barrier-dir", str(barrier),
               "--result", str(results / f"r{i}.json"),
               "--n", "2"]
        cmd += list(extra or [])
        log = (results / f"r{i}.log").open("wb")
        with log:
            procs.append(subprocess.Popen(  # noqa: S603 - 脚本与参数都是本文件给的字面量
                cmd, stdout=log, stderr=subprocess.STDOUT))
    for p in procs:
        p.wait(timeout=240)
    payloads: list[dict] = []
    for i in range(2):
        rf = results / f"r{i}.json"
        assert rf.is_file(), (
            f"工作进程 {i}（pid={procs[i].pid}）没有留下结果文件，退出码 "
            f"{procs[i].returncode}。日志尾部：\n"
            + (results / f"r{i}.log").read_text(encoding="utf-8", errors="replace")[-3000:])
        payloads.append(json.loads(rf.read_text(encoding="utf-8")))
    return ws, payloads


# --------------------------------------------------------------------- a


def test_a_two_processes_mint_distinct_pending_ids_and_rounds(tmp_path: Path):
    """两个真进程同时落同一份 pending 台账 ⇒ `u-000001` / `u-000002`，round 1 / 2。"""
    ws, payloads = _run_pair(tmp_path, mode="pending",
                             extra=["--hold-after-id", str(HOLD)])
    problems = _a_problems(ws, payloads)
    assert problems == [], problems
    assert sorted(str(p["verification_id"]) for p in payloads) == ["u-000001", "u-000002"], (
        payloads)
    assert sorted(int(p["round"]) for p in payloads) == [1, 2], payloads


def test_a_prime_anti_vacuum_the_cross_process_lock_is_load_bearing(tmp_path: Path):
    """反真空：把跨进程锁换成 `nullcontext` ⇒ a 的读数必红（同号 + 同轮）。"""
    ws, payloads = _run_pair(tmp_path, mode="pending", tag="-nolock",
                             extra=["--hold-after-id", str(HOLD), "--no-lock"])
    assert all(p.get("ok") for p in payloads), (
        "工作进程没写成（装置故障 ≠ 反真空成立）：" + str(payloads))
    problems = _a_problems(ws, payloads)
    assert problems != [], (
        "把 pending 的跨进程锁打桩掉之后 a 仍然绿 ⇒ a 量的不是那把锁")
    ids = [str(p["verification_id"]) for p in payloads]
    assert len(set(ids)) == 1, f"没有撞号（窗口没被拉开）：{ids}"


# --------------------------------------------------------------------- b


def _calls() -> list[SC.TaskCall]:
    return [SC.TaskCall("H", "review", {"doc_id": "0001"}, instance="h1"),
            SC.TaskCall("H", "review", {"doc_id": "0001"}, instance="h2")]


def test_b_same_role_instances_are_not_exempt_without_row_level_mutex(tmp_path: Path):
    """同角色两实例写同一张没有行级互斥的表（`review_findings`）⇒ 分波，不许豁免。"""
    calls = _calls()
    assert P.estimate_write_conflict(calls[0], calls[1]) is True, (
        "同一角色、两个不同实例、写集相交在一张没有行级互斥的表上，"
        "仍然被豁免成交叉并发")
    assert len(P.waves_of(calls, limit=4)) == 2


def test_b_prime_row_level_mutex_keeps_the_instance_axis(tmp_path: Path):
    """正控：`experiments` 有行级归属 ⇒ 两个 E 实例仍然同波（豁免不是全删）。"""
    calls = [SC.TaskCall("E", "run_experiment", {}, instance="e1"),
             SC.TaskCall("E", "run_experiment", {}, instance="e2")]
    assert P.estimate_write_conflict(calls[0], calls[1]) is False
    assert len(P.waves_of(calls, limit=4)) == 1


# --------------------------------------------------------------------- c


def _c_problems(ws: Path, payloads: list[dict]) -> list[str]:
    """c 的读数：轮次丢没丢、同键发现是不是两行。空列表 = 成立。"""
    problems: list[str] = []
    if not all(p.get("ok") for p in payloads):
        problems.append(f"有进程没写成（装置故障不是结论）：{payloads}")
        return problems
    rounds = sorted(int(p.get("round") or 0) for p in payloads)
    if rounds != [1, 2]:
        problems.append(f"复审轮次不是 1 / 2（丢了一轮）：{rounds}")
    st = Store(Path(ws))
    docs = [r for r in st.rows("documents") if str(r.get("doc_id")) == "0000"]
    assert docs, "夹具稿不见了"
    if int(docs[0].get("review_rounds") or 0) != 2:
        problems.append(
            f"盘上 review_rounds = {docs[0].get('review_rounds')!r}（应为 2）")
    findings = st.rows("review_findings")
    if len(findings) != 1:
        problems.append(f"同键发现落了 {len(findings)} 行（应 1 行）")
    return problems


def test_c_two_processes_reviewing_one_draft_do_not_lose_a_round_or_a_finding(
        tmp_path: Path):
    """两个真进程同时复审同一份稿 ⇒ 轮次 1→2、同键发现一行。"""
    ws, payloads = _run_pair(tmp_path, mode="h")
    problems = _c_problems(ws, payloads)
    assert problems == [], problems


# --------------------------------------------------------------------- 反真空（c 的读法自证）


def test_c_reading_is_not_vacuous(tmp_path: Path):
    """c 的读数确实分得开"丢一轮"与"没丢"：手写一份 1 轮 / 2 行的盘面 ⇒ 必报。"""
    ws = tmp_path / "ws-probe"
    st = Store(ws)
    st.init()
    with st.tx("documents", actor="fixture", note="读法自证：造稿") as tx:
        tx.upsert("documents", S.Document(
            doc_id="0000", kind="paper", title="读法自证", status="draft",
            claims=[{"claim_id": "claim-1", "text": "读法自证：一条断言",
                     "citations": ["rel:0000"], "evidence_kind": "cross_check",
                     "disclaimer": "不构成证明", "section": "主要结果",
                     "is_negative": False}],
            content_sha256="c" * 64,
            review_rounds=1, created_at="2026-11-19T00:00:00+08:00",
            created_by="fixture").to_dict())
    with st.tx("review_findings", actor="fixture", note="读法自证：两行同键") as tx:
        for i in (1, 2):
            tx.upsert("review_findings", S.ReviewFinding(
                finding_id=f"{i:04d}", doc_id="0000", kind="unsupported_claim", level="warning",
                target="claim-1", message="同一条发现", evidence="读法自证",
                round=1).to_dict())
    payloads = [{"ok": True, "round": 1}, {"ok": True, "round": 1}]
    assert _c_problems(ws, payloads) != [], "丢一轮 / 两行同键居然读成了成立"


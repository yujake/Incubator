# -*- coding: utf-8 -*-
"""判据：V 稿的号不许撞、不许复用（跨进程 + 盘上漏记两条）。

## 这两条缺陷是什么

AN1 在核查 A 稿号时顺带读出来的（与 A 稿无关，但同族）：

```text
① vreviews.py:79-86  用的是进程内 `threading.Lock`，不是跨进程锁
   ⇒ 两个进程同时记录 V 稿时会各发一个号、各写一份索引
   （A 的号照 manuscripts.py:489-490「取号在 FileLock 内」+ secretary.py:528 的
   "两层都要"形态）
② next_review_id 无上限，且索引追加失败后不跳盘上已有号 ⇒ 会复用号覆盖正文
```

## 五条判据（各自量一个具体读数）

- a：两个真进程同时取号 ⇒ 不许撞号（同号不许发两次、索引不许两行同号、
  盘上正文份数不许少于写成的份数）。
- b：盘上已有 `v-review-000003.md` 而索引里没有它（索引追加失败留下的那一份）
  ⇒ 下一个号必须 > 3，那一份正文一个字都不许被覆盖。
- c：反真空 —— 把"跳盘上已有号"（`_on_disk_ids`）打桩关掉 ⇒ b 的读数必变红。
- d：反真空 —— 把跨进程锁换回 `threading.Lock`（修前的形态）⇒ a 的读数必变红。
- e：号有上界（`store.MAX_ID`）⇒ 到顶时受控抛 `ReviewIdExhausted`，
  不折回 `000001`、不覆盖已经到顶的那一份。

c / d 用的是 a / b 的同一段读数函数（`_a_problems` / `_b_problems`）：
反真空不另写一份判据，它就是 a / b 的断言在打桩之后的读数。d 同时是装置自证 ——
同一份正文被覆盖这件事只可能在"取号窗口真的被拉开"时发生。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agentflow import vreviews as VRV

from _vreview_mp_worker import _review_kwargs

#: 工作进程脚本（不是 pytest 收集目标）。
WORKER = Path(__file__).resolve().parent / "_vreview_mp_worker.py"

#: 索引追加失败留下的那一份正文的哨兵（覆盖过它就不再出现）。
SENTINEL = "盘上正文：这一份的索引行没有追加成功（b 的哨兵，被覆盖就是复用号）\n"

#: 取号窗口放大的时长：持锁 / 持读的进程睡够这么久，另一个进程必然读到同一份索引。
HOLD = 1.5


# --------------------------------------------------------------------- 读数

def _index(ws: Path) -> list[dict]:
    path = VRV.reviews_index_path(ws)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _reviews(ws: Path) -> list[Path]:
    gate = Path(ws) / VRV.REVIEWS_DIR
    return sorted(gate.glob(f"{VRV.PREFIX}*.md")) if gate.is_dir() else []


def _a_problems(ws: Path, payloads: list[dict]) -> list[str]:
    """a 的读数：撞号 / 索引同号 / 正文份数对不上。空列表 = 成立。"""
    problems: list[str] = []
    if not all(p.get("ok") and p.get("written") for p in payloads):
        problems.append(f"有进程没写成：{payloads}")
    ids = [str(p.get("review_id") or "") for p in payloads]
    if len(set(ids)) != len(ids):
        problems.append(f"两个进程发了同一个号：{ids}")
    rows = _index(ws)
    row_ids = [str(r.get("review_id") or "") for r in rows]
    if len(rows) != len(payloads):
        problems.append(f"索引行数 {len(rows)} ≠ 写成的份数 {len(payloads)}：{row_ids}")
    if len(set(row_ids)) != len(row_ids):
        problems.append(f"索引里出现同号两行：{row_ids}")
    files = [p.name for p in _reviews(ws)]
    if len(files) != len(payloads):
        problems.append(f"盘上正文 {files} 少于写成的份数 {len(payloads)}（同号覆盖过？）")
    return problems


def _b_problems(stray: Path, got: dict) -> list[str]:
    """b 的读数：号必须大于盘上那一份，且那一份正文不许被覆盖。空列表 = 成立。"""
    problems: list[str] = []
    rid = str(got.get("review_id") or "")
    tail = rid[len(VRV.PREFIX):] if rid.startswith(VRV.PREFIX) else ""
    num = int(tail) if tail.isdigit() else 0
    if num <= 3:
        problems.append(f"下一个号是 {rid or '（没发号）'}（≤ 盘上已有的 000003）⇒ 会覆盖那一份正文")
    if stray.read_text(encoding="utf-8") != SENTINEL:
        problems.append("盘上 v-review-000003.md 的正文被覆盖了")
    return problems


# --------------------------------------------------------------------- 夹具

def _seed_stray_disk(ws: Path) -> Path:
    """索引只有 1、2，盘上多一份 3 —— "正文先落、索引追加失败"留下的那一份。"""
    gate = Path(ws) / VRV.REVIEWS_DIR
    gate.mkdir(parents=True, exist_ok=True)
    ledger = "verifications/000007.jsonl"
    for n in (1, 2):
        rid = f"{VRV.PREFIX}{n:06d}"
        (gate / f"{rid}.md").write_text(f"# 旧稿 {rid}\n", encoding="utf-8")
        row = {"review_id": rid, "at": "2026-11-16T00:00:00+08:00",
               "path": f"{VRV.REVIEWS_DIR}/{rid}.md", "ledger": ledger,
               "verification_id": f"v-{n:06d}"}
        with VRV.reviews_index_path(ws).open("a", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    stray = gate / f"{VRV.PREFIX}000003.md"
    stray.write_text(SENTINEL, encoding="utf-8")
    return stray


def _record(ws: Path, verification_id: str) -> dict:
    """在本进程里落一份 V 稿（与工作进程用同一份 kwargs）。"""
    return VRV.record_review(
        ws, **_review_kwargs("verifications/000007.jsonl", verification_id))


def _run_pair(base: Path, *, no_cross_lock: bool = False,
              tag: str = "") -> tuple[Path, list[dict]]:
    """起两个真进程跑同一个工作区，返回 (工作区, 各进程结果)。

    与 `tests/test_usage_ledger_idempotency_mp.py` 同一形状：结果与就绪信号一律走
    文件（受限执行环境里管道是明确的失败面）；读不到结果文件就把日志贴进断言。
    """
    ws = base / f"ws{tag}"
    ws.mkdir(parents=True, exist_ok=True)
    results = base / f"results{tag}"
    results.mkdir(parents=True, exist_ok=True)
    barrier = base / f"barrier{tag}"

    procs: list[subprocess.Popen] = []
    for i in range(2):
        cmd = [
            sys.executable, str(WORKER),
            "--root", str(ws),
            "--barrier-dir", str(barrier),
            "--result", str(results / f"r{i}.json"),
            "--n", "2",
            "--ledger", "verifications/000007.jsonl",
            # 两个不同的台账锚点（同一个锚点会走幂等支，量不到发号）
            "--verification-id", f"v-00000{i + 1}",
        ]
        if no_cross_lock:
            cmd.append("--no-cross-lock")
        if i == 0:
            cmd += ["--hold-after-read", str(HOLD)]
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

def test_a_two_processes_never_mint_the_same_number(tmp_path: Path):
    """两个真进程同时在同一个工作区取号 ⇒ 两个号、两份正文、两行索引。"""
    ws, payloads = _run_pair(tmp_path)
    problems = _a_problems(ws, payloads)
    assert problems == [], problems
    assert sorted(str(p["review_id"]) for p in payloads) == [
        f"{VRV.PREFIX}000001", f"{VRV.PREFIX}000002"], payloads
    assert [p.name for p in _reviews(ws)] == [
        f"{VRV.PREFIX}000001.md", f"{VRV.PREFIX}000002.md"], _reviews(ws)


# --------------------------------------------------------------------- b

def test_b_next_number_skips_the_one_already_on_disk(tmp_path: Path):
    """盘上有 000003、索引没有它 ⇒ 下一个号 = 000004，那一份正文一个字节也不动。"""
    ws = tmp_path / "ws"
    stray = _seed_stray_disk(ws)
    got = _record(ws, "v-000009")
    problems = _b_problems(stray, got)
    assert problems == [], problems
    assert got["written"] is True, got
    assert got["review_id"] == f"{VRV.PREFIX}000004", got
    rows = [r["review_id"] for r in _index(ws)]
    assert rows == [f"{VRV.PREFIX}000001", f"{VRV.PREFIX}000002",
                    f"{VRV.PREFIX}000004"], rows
    assert (ws / VRV.REVIEWS_DIR / f"{VRV.PREFIX}000004.md").is_file()


# --------------------------------------------------------------------- e

def test_e_ids_have_a_ceiling_and_refuse_instead_of_wrapping(tmp_path: Path):
    """号到 `MAX_ID` ⇒ 受控抛错，不折回 000001、不覆盖到顶的那一份。"""
    ws = tmp_path / "ws"
    gate = ws / VRV.REVIEWS_DIR
    gate.mkdir(parents=True, exist_ok=True)
    top = f"{VRV.PREFIX}{VRV.MAX_ID:06d}"
    (gate / f"{top}.md").write_text(SENTINEL, encoding="utf-8")

    with pytest.raises(VRV.ReviewIdExhausted):
        VRV.next_review_id([], {VRV.MAX_ID})
    with pytest.raises(VRV.ReviewIdExhausted):
        VRV.next_review_id([{"review_id": top}], set())

    got = _record(ws, "v-000009")
    assert got["written"] is False and got["checked"] is False, got
    assert got["review_id"] == "", f"号用尽之后仍然发了一个号：{got['review_id']}"
    assert "上界" in str(got["reason"]), got["reason"]
    assert (gate / f"{top}.md").read_text(encoding="utf-8") == SENTINEL, (
        "到顶的那一份正文被覆盖了")
    assert [p.name for p in _reviews(ws)] == [f"{top}.md"], _reviews(ws)


# --------------------------------------------------------------------- 反真空

def test_c_anti_vacuum_disk_skip_is_load_bearing(tmp_path: Path, monkeypatch):
    """把"跳盘上已有号"打桩关掉 ⇒ b 的读数必红（000003 被复用、正文被覆盖）。"""
    ws = tmp_path / "ws"
    stray = _seed_stray_disk(ws)
    monkeypatch.setattr(VRV, "_on_disk_ids", lambda _root: frozenset())

    got = _record(ws, "v-000009")
    problems = _b_problems(stray, got)
    assert problems != [], (
        "把「跳盘上已有号」打桩关掉之后 b 仍然绿 ⇒ b 量的不是这件事")
    assert got["review_id"] == f"{VRV.PREFIX}000003", got
    assert stray.read_text(encoding="utf-8") != SENTINEL, (
        "打桩关掉之后那一份正文没有被覆盖 —— b 的反真空没量到覆盖这件事")


def test_d_anti_vacuum_cross_process_lock_is_load_bearing(tmp_path: Path):
    """把跨进程锁换回 `threading.Lock` ⇒ a 的读数必红（两个进程同号）。

    这一条同时是装置自证：同一份正文被覆盖只可能在"取号窗口真的被拉开"时发生。
    """
    ws, payloads = _run_pair(tmp_path, no_cross_lock=True, tag="-nolock")
    problems = _a_problems(ws, payloads)
    assert problems != [], (
        "把跨进程锁换回 threading.Lock 之后 a 的读数仍然绿 ⇒ a 量的不是那把锁")
    ids = [str(p["review_id"]) for p in payloads]
    assert len(set(ids)) == 1, f"没有撞号（窗口没被拉开）：{ids}"

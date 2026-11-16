"""V 稿号源的跨进程判据工作进程（刻意不叫 `test_*.py`，不被 pytest 收集）。

## 为什么是独立脚本 + 文件通信，而不是 `multiprocessing`

与 `tests/_mp_idem_worker.py` 同一口径：

1. 跨平台：Windows 是 `spawn` 起点，子进程要重新导入模块；pytest 的测试模块在
   子进程里被重新导入会连带碰到 `conftest` 的 `sys.path` 注入与 fixture 发现。
   可被 `python <脚本>` 直接执行的顶层脚本没有这个问题。
2. 不走管道：本项目的受限执行环境里管道是明确的失败面（子进程用管道存输出会
   EPERM）。结果与"就绪"信号一律走文件。

## 它如何把竞态窗口确定性地放大

`--hold-after-read` 会在 `vreviews._on_disk_ids` 上装一个钩子：把盘上已用号读完之后先睡这么久再返回。于是"号源的两边（索引 + 盘上文件名）都读完了 → 写正文 →
追加索引"之间的窗口从"几微秒、看运气"变成"必现"。

`--read-barrier-dir` 是同一个钩子上的汇合点：读完号源之后先写一张票，等齐
`--n` 张票再往下走 —— 于是"两个读者都读完了，才有第一个写者动笔"不再靠"谁先被
调度、谁的墙钟睡够"，而是由文件屏障保证。`--hold-after-read` 只保证"读者自己
读完到写盘之间有一段墙钟"（有跨进程锁时靠它就够：另一个进程会卡在锁上）；
没有那把锁时，墙钟挡不住"另一个进程抢先读完并写完"这一档 —— 那一档正是
反真空要量的东西，所以它走 `--read-barrier-dir`，不走墙钟。

- 有跨进程锁时：先拿到锁的那个进程在钩子里睡满，另一个进程在锁上等；醒来之后
  读到的是已经追加过的那一行、且盘上已经多了一份正文 ⇒ 两个号。
- `--no-cross-lock`（反真空：把跨进程锁换回"进程内一把 `threading.Lock`"）时：
  两个进程都在对方写盘之前读完了号源 ⇒ 同一个号，后写的覆盖先写的正文。

钩子挂在 `_on_disk_ids` 而不是 `_read_index` 上，是因为它是发号前最后一次读：
挂在更早的位置，另一个进程仍可能在"盘上文件名"那一步读到前一份正文而跳号 ——
那条路是另一道防线（`test_b`），不是这把锁，在这里会把它测成"锁也多余"。

用同一个装置跑出两种结局，才说明修复真的改变了那个窗口，而不是测试运气变了。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

#: 与 `tests/conftest.py` 同一口径：注入 `src/`，不要求安装包。
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import vreviews as VRV  # noqa: E402

#: 固定时间戳：索引行要求 `at` 非空，而判据不许依赖当前时间。
TS = "2026-11-16T00:00:00+08:00"


def _barrier(directory: Path, name: str, n: int, timeout: float) -> None:
    """文件屏障：写自己的票，然后等齐 `n` 张票。

    与 `_mp_idem_worker._barrier` 同一条纪律：超时必须抛而不是静默继续 ——
    静默继续会让"没等齐"变成"看起来没撞号"，那是把装置故障伪装成修复生效。
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.{os.getpid()}").write_text("1", encoding="utf-8")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(list(directory.glob(f"{name}.*"))) >= n:
            return
        time.sleep(0.005)
    got = len(list(directory.glob(f"{name}.*")))
    raise TimeoutError(f"屏障 {name!r} 超时：只等到 {got}/{n} 个进程")


def _review_kwargs(ledger: str, verification_id: str) -> dict:
    """一份形态完整的 V 稿（内容不重要 —— 判据量的是号，不是正文）。"""
    return dict(
        statement_id="000007", manuscript="reports/f-proof-000007.md",
        manuscript_family="f-proof", manuscript_id="000007",
        proof_sha256="a" * 64, verdict="有毛病", defect_step=2,
        findings=[{"level": "error", "step": 2, "kind": "k", "detail": "d"}],
        reason="r", fault_kind="math", at=TS,
        ledger=ledger, verification_id=verification_id)


def run(args: argparse.Namespace) -> dict:
    root = Path(args.root)
    if args.no_cross_lock:
        # 反真空：把跨进程那把锁换回"进程内一把 `threading.Lock`"（修前的形态）。
        # 每个进程各有一把，跨进程等于没有锁。
        VRV._cross_process_lock = lambda _path: threading.Lock()  # type: ignore[assignment]
    _barrier(Path(args.barrier_dir), "pre", args.n, args.timeout)
    if args.read_barrier_dir or args.hold_after_read:
        real = VRV._on_disk_ids
        hold = float(args.hold_after_read or 0.0)
        read_dir = Path(args.read_barrier_dir) if args.read_barrier_dir else None
        n, timeout = int(args.n), float(args.timeout)

        def _slow(root_):  # noqa: ANN001, ANN202 - 钩子签名与 `_on_disk_ids` 一致
            got = real(root_)
            if read_dir is not None:
                # 两个读者都读完号源之后才放行 ⇒ 之后无论谁先动笔，"先读后写"
                # 这件事已经发生完了（不依赖调度顺序，也不依赖墙钟）。
                _barrier(read_dir, "read", n, timeout)
            if hold:
                time.sleep(hold)
            return got

        VRV._on_disk_ids = _slow  # type: ignore[assignment]
    got = VRV.record_review(root, **_review_kwargs(args.ledger, args.verification_id))
    return {"pid": os.getpid(), "review_id": str(got.get("review_id") or ""),
            "checked": bool(got.get("checked")),
            "written": bool(got.get("written")),
            "idempotent": bool(got.get("idempotent")),
            "reason": str(got.get("reason") or "")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="V 稿号源的跨进程判据工作进程")
    ap.add_argument("--root", required=True, help="工作区根（verifications/ 的父目录）")
    ap.add_argument("--barrier-dir", required=True)
    ap.add_argument("--result", required=True, help="本进程结果的落盘路径")
    ap.add_argument("--n", type=int, required=True, help="参与者总数（屏障用）")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--ledger", default="verifications/000007.jsonl")
    ap.add_argument("--verification-id", default="v-000001")
    ap.add_argument("--hold-after-read", type=float, default=0.0,
                    help="读到索引之后睡多久再返回（放大取号窗口）")
    ap.add_argument("--read-barrier-dir", default="",
                    help="读号源之后的文件屏障目录：等齐 --n 个读者再往下走")
    ap.add_argument("--no-cross-lock", action="store_true",
                    help="反真空：把跨进程锁换回进程内 threading.Lock")
    args = ap.parse_args(argv)

    payload: dict
    try:
        payload = {"ok": True, **run(args)}
    except BaseException as e:  # noqa: BLE001 —— 异常也要落盘，否则父进程只看得到"没结果"
        payload = {"ok": False, "pid": os.getpid(),
                   "error": f"{type(e).__name__}: {e}"}
    Path(args.result).parent.mkdir(parents=True, exist_ok=True)
    Path(args.result).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""时钟单例不许跨判据泄漏（`R3-10` 的 chunk-1 顺序依赖）。

## 这一条防的是什么

`test_clock_governs_all_timed_work.py::test_e2_framework_waits_are_on_the_ledger` 里
`C.use(fake)` 之后没有收尾；同一进程里随后跑的 `test_store_r3_commit_order.py` 测的是
`store._atomic_write` 在 `os.replace` 连续失败时的退避 —— 那条退避走 `CLK.await_io`。
假时钟下 `await_io` 立即返回，0.62s 的退避被压成 0.016s ⇒ 全量里红、单跑绿
（2026-11-01 的 chunk-1 实测；单跑 12 passed）。

修法在 `tests/conftest.py` 的逐条还原面（与 156 ④ 的钩子基线同一类），
不在 `store` 或判据里加 sleep / 重试。

## 三条读数

1. 负控：本用例故意留下假时钟（证明 `current()` 真的会变）；
2. 下一条判据必须从真时钟出发（去掉 conftest 的还原面，这一条会红）；
3. 同一进程按全量顺序跑「时钟文件那一格 + store 退避那一格」⇒ 必须绿
   （去掉还原面，这一条会红）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agentflow import clock as C

ROOT = Path(__file__).resolve().parents[1]


def test_a_fake_clock_left_behind_is_visible_to_the_next_test() -> None:
    """负控：装上假时钟且不收尾 —— 若还原面消失，下一条会看到它。"""
    fake = C.FakeClock(wall="2026-01-01T00:00:00+00:00", monotonic=1.0)
    C.use(fake)
    assert C.current() is fake, "假时钟没装上 ⇒ 这条负控没有对象"


def test_the_next_test_starts_from_the_real_clock() -> None:
    """上一条故意没收尾；conftest 的逐条还原面必须把它清掉。"""
    assert isinstance(C.current(), C.RealClock), (
        "上一条留下的假时钟活到了这一条 ⇒ 同一进程里后面的 store 退避会被压成 0（`R3-10`）"
    )


def test_the_two_files_in_one_process_are_green() -> None:
    """按全量顺序把「留下假时钟的那一格」+「store 退避」放进同一进程跑 ⇒ 必须绿。"""
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "tests/test_clock_governs_all_timed_work.py::test_e2_framework_waits_are_on_the_ledger",
            "tests/test_store_r3_commit_order.py::test_the_backoff_comment_matches_the_measured_wait",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")

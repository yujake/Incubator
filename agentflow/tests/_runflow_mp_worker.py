"""`run_topic` 多进程并发测试的工作进程（刻意不叫 `test_*.py`，不被 pytest 收集）。
## 为什么是独立脚本 + 文件通信

与 `tests/_mp_idem_worker.py` 同一口径：Windows 是 `spawn` 起点，pytest 的测试模块在子进程里重新导入会连带碰到 `conftest` 的 `sys.path` 注入与 fixture 发现；受限执行环境里管道是明确的失败面（子进程用管道存输出会 EPERM）。结果一律走文件 —— 那也正是 `Store` 自己一直在用的通道。

## 为什么必须用真进程（而不是线程/内存里的假 store）

`R5-AN-1` 的缺陷形态是"两个进程各自读一份无锁快照、各自取号"：同一进程里 `store` 的缓存与同一把进程内锁会掩盖那个窗口。只有两个真进程（各自一个解释器、各自一份快照、共用同一个工作区目录）才复现得出来。

## 起跑屏障：把"取号窗口重叠"从看运气变成必现

`--barrier` 指向一个目录：本进程把 `ready.<pid>` 写出来，然后等 `go.<n>`（父测试写的那张放行票）。父测试等齐 n 张 `ready.*` 才放行 ⇒ 两个 `run_topic` 的取号窗口真的重叠。没有这一步，第二个进程可能在第一个进程已经写完行之后才开跑，"并发"就退化成了"先后"，测试会得到一个恒绿的假象。

`--delay` 让传输层睡一会儿（模型调用在飞），把窗口进一步放大：修复前的实现里两个进程都会在这段时间里取完号、还没写行。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

#: 与 `tests/conftest.py` 同一口径：注入 `src/`，不要求安装包。
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow.modelgw import ModelSpec  # noqa: E402
from agentflow.runflow import run_topic  # noqa: E402
from agentflow.store import Store  # noqa: E402

ABSTRACT = "An abelian group is a group in which the commutative law holds."


def _wait_for_go(directory: Path, n: int, timeout: float) -> None:
    """起跑屏障：写自己的 ready 票，然后等父测试写 `go.<n>`。

    超时必须抛而不是静默继续 —— 静默继续会让"没等齐"变成"看起来没撞号"，
    那是把装置故障伪装成修复生效（与 `_mp_idem_worker._barrier` 同一条纪律）。
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"ready.{os.getpid()}").write_text("1", encoding="utf-8")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if (directory / f"go.{n}").exists():
            return
        time.sleep(0.005)
    raise TimeoutError(
        f"起跑屏障超时：没等到 {directory / f'go.{n}'}（父测试没放行？）"
    )


def _body() -> str:
    return json.dumps({
        "choices": [{"message": {"role": "assistant",
                                 "content": f"- 阿贝尔群是交换群 || {ABSTRACT}\n"}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3},
    }, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="run_topic 并发撞号的工作进程")
    ap.add_argument("--ws", required=True, help="工作区根（data/ 的父目录）")
    ap.add_argument("--out", required=True, help="产物目录（每一跑一个）")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--now", required=True, help="显式时间戳：并发两跑必须各给一个")
    ap.add_argument("--barrier", required=True)
    ap.add_argument("--n", type=int, required=True, help="参与者总数（屏障用）")
    ap.add_argument("--result", required=True, help="本进程结果的落盘路径")
    ap.add_argument("--delay", type=float, default=0.0, help="传输层睡觉的秒数")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args(argv)

    def _transport(url: str, headers: dict, data: bytes,
                   timeout_sec: float) -> tuple[int, str]:  # noqa: ARG001
        # 让这一跑"在飞"足够久：另一进程才有机会在它写行之前也取号。
        if args.delay:
            time.sleep(args.delay)
        return 200, _body()

    def _search(topic: str, *, limit: int, timeout_sec: float):  # noqa: ARG001
        return [{"source": "selftest", "title": "Abelian groups", "year": 1930,
                 "doi": "10.1000/selftest", "abstract": ABSTRACT}]

    work = Path(args.ws)
    st = Store(work)
    st.init()  # 幂等：两个进程都调也不会重置已 init 的工作区
    _wait_for_go(Path(args.barrier), args.n, args.timeout)

    res = run_topic(
        st, topic=args.topic, budget_usd=1.0, out_dir=Path(args.out),
        transport=_transport, spec=ModelSpec(api_key="selftest-key"),
        max_calls=1, search_fn=_search, now=args.now,
    )
    man_path = Path(args.out) / "run-manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
    Path(args.result).write_text(json.dumps({
        "exit_code": res["exit_code"],
        "reason": res["reason"],
        "calls": res["calls"],
        "spent_usd_this_run": res["spent_usd_this_run"],
        "task_row": man.get("task_row"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

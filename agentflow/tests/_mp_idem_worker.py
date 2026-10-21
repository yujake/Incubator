"""多进程幂等测试的工作进程（刻意不叫 `test_*.py`，不被 pytest 收集）。

## 为什么是独立脚本 + 文件通信，而不是 `multiprocessing`

两条独立的理由，各自都足够：

1. 跨平台：Windows 是 `spawn` 起点，子进程要重新导入模块。pytest 的测试模块
   在子进程里被重新导入会连带碰到 `conftest` 的 `sys.path` 注入与 fixture 发现。
   一个可被 `python <脚本>` 直接执行的顶层脚本没有这个问题。
2. 不走管道：本项目的受限执行环境里，管道是明确的失败面（子进程用管道存输出
   会 EPERM）。结果与"就绪"信号一律走文件 —— 那也是 `Store` 自己一直在用的通道。

## 它同时扮演两个角色（本文件的设计要点）

- 正控：同一个幂等键的 N 个进程，账本必须只有一行。
- 负控（装置自证）：不同的幂等键的 N 个进程必须落 N 行。
  没有这条，一次"因为进程根本没跑起来 / 写入被静默丢弃"而得到的"1 行"，
  会被误读成"幂等生效了"。这正是本项目反复强调的"没有负控的绿灯不是绿灯"。

## 它如何把竞态窗口确定性地放大

`--mode reply` 会在 `modelcost._find_by_marker` 上装一个钩子：当外层查重读到
"没有这笔账"时，让该进程在屏障上等齐所有同伴，再继续往下写。
于是"先读账再写账"之间的窗口从"几微秒、看运气"变成"必现" ——
修复前的代码在 `--mode reply` 下必然写出 N 行，修复后必然只写 1 行。
用同一个装置跑出两种结局，才说明修复真的改变了那个窗口，而不是测试运气变了。
"""

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

from agentflow import modelcost as MC  # noqa: E402
from agentflow.modelgw import ModelReply  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tokenmeter import Charge, TokenMeter  # noqa: E402

#: 固定时间戳：账本行要求 `at` 非空，而测试不许依赖当前时间。
TS = "2026-01-01T00:00:00+00:00"


def _barrier(directory: Path, name: str, n: int, timeout: float) -> None:
    """文件屏障：写自己的票，然后等齐 `n` 张票。

    每个进程每个 `name` 只参与一次，所以票数到达 `n` 就释放。
    超时必须抛而不是静默继续 —— 静默继续会让"没等齐"变成
    "看起来没重复"，那是把装置故障伪装成修复生效。
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


def _reply(tokens_in: int = 1000, tokens_out: int = 500) -> ModelReply:
    return ModelReply(ok=True, text="4", tokens_in=tokens_in, tokens_out=tokens_out,
                      attempts=1, model="deepseek-chat", scope="reason")


def run(args: argparse.Namespace) -> dict:
    store = Store(args.root)
    store.init()  # 幂等：已 init 的工作区不会被重置
    meter = TokenMeter(store)
    barrier_dir = Path(args.barrier_dir)

    # ---- 所有进程先在同一个起点集合，否则"并发"只是"先后"
    _barrier(barrier_dir, "pre", args.n, args.timeout)

    if args.mode == "reply":
        # 把"读账 → 写账"之间的窗口确定性放大（见模块 docstring）。
        real = MC._find_by_marker
        fired = {"done": False}

        def _slow(meter_, key):  # noqa: ANN001, ANN202
            row = real(meter_, key)
            if row is None and not fired["done"]:
                fired["done"] = True
                _barrier(barrier_dir, "postread", args.n, args.timeout)
            return row

        MC._find_by_marker = _slow  # type: ignore[assignment]
        res = MC.charge_reply(
            meter, _reply(), task_id=args.task_id, call_index=args.call_index,
            scope="reason", now=TS,
        )
        return {"pid": os.getpid(), "mode": args.mode, **{k: res[k] for k in
                ("charged", "reason", "usage_id", "usd")}}

    if args.mode == "once":
        # `{pid}` 占位符让"每进程一个不同的键"这条负控成为可能：
        # 它必须落 N 行，用来证明本装置数得出并发写入（见模块 docstring）。
        key = args.idem_key.replace("{pid}", str(os.getpid()))
        res = meter.charge_once(
            Charge(role="modelgw", scope="reason", tokens_in=1000, tokens_out=500,
                   usd=0.0005, task_id=args.task_id, note=args.note),
            idem_key=key, now=TS,
        )
        return {"pid": os.getpid(), "mode": args.mode, "idem_key": key,
                "recorded": res["recorded"], "usage_id": res["usage_id"],
                "duplicate": res["duplicate"]}

    if args.mode == "control":
        # 负控：不同的键必须落不同的行。用一个每次执行都不同的 note。
        res = meter.charge(
            Charge(role="modelgw", scope="reason", tokens_in=1000, tokens_out=500,
                   usd=0.0005, task_id=args.task_id,
                   note=f"control-note;pid={os.getpid()}"),
            now=TS,
        )
        return {"pid": os.getpid(), "mode": args.mode, "recorded": res["recorded"],
                "usage_id": res["usage_id"]}

    raise SystemExit(f"未知 mode：{args.mode!r}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="usage_ledger 多进程幂等测试的工作进程")
    ap.add_argument("--mode", required=True, choices=("reply", "once", "control"))
    ap.add_argument("--root", required=True, help="工作区根（data/ 的父目录）")
    ap.add_argument("--barrier-dir", required=True)
    ap.add_argument("--result", required=True, help="本进程结果的落盘路径")
    ap.add_argument("--n", type=int, required=True, help="参与者总数（屏障用）")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--task-id", default="t-mp")
    ap.add_argument("--call-index", type=int, default=0)
    ap.add_argument("--idem-key", default="")
    ap.add_argument("--note", default="mp")
    args = ap.parse_args(argv)

    payload: dict
    try:
        payload = {"ok": True, **run(args)}
    except BaseException as e:  # noqa: BLE001 —— 异常也要落盘，否则父进程只看得到"没结果"
        payload = {"ok": False, "pid": os.getpid(), "mode": args.mode,
                   "error": f"{type(e).__name__}: {e}"}
    Path(args.result).parent.mkdir(parents=True, exist_ok=True)
    Path(args.result).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""K16 的跨进程读回执工作进程（刻意不叫 `test_*.py`，不被 pytest 收集）。

## 为什么这一条必须是"另一个进程"

AL-06 的缺口是"回执按 `(工作区根, request_id)` 存在进程内字典里"：同一个解释器里
怎么写都读得到，于是"进程内够用"这句话在那条判据下永远成立。要证明回执真的落盘，
就得让写它的那个进程退出，由另一个进程去读 —— 与 `tests/_vreview_mp_worker.py`
同一口径（结果走文件，不走管道）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import identity as IDENT  # noqa: E402
from agentflow import litstage as L  # noqa: E402
from agentflow.store import Store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="K16 回执的跨进程判据工作进程")
    ap.add_argument("--root", required=True)
    ap.add_argument("--request-id", required=True)
    ap.add_argument("--instance", default="")
    ap.add_argument("--result", required=True)
    args = ap.parse_args(argv)
    payload: dict
    try:
        IDENT.set_current_instance(args.instance)
        st = Store(Path(args.root))
        got = L.readback_receipt(st, args.request_id)
        payload = {"ok": True, "found": bool(got),
                   "instance": str((got or {}).get("instance") or ""),
                   "slots": list((got or {}).get("slots") or []),
                   "at": str((got or {}).get("at") or "")}
    except BaseException as e:  # noqa: BLE001 —— 异常也要落盘，否则父进程只看得到"没结果"
        payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    Path(args.result).parent.mkdir(parents=True, exist_ok=True)
    Path(args.result).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

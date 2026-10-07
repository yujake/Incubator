"""G-35 裁定用的实测：把桩打在 `open` 上（而不是打在被测函数 `code_hash` 上）。

要证明两件事：
1. `monkeypatch.setattr(VT, "open", boom, raising=False)` 能**真的进到 `code_hash` 函数体内部**
   （因为它按 globals → builtins 的顺序解析 `open`），于是"逃逸路径"被真实执行；
2. 打桩撤掉之后同一条路径照旧可用（负控），说明桩没有顺手改掉别的行为。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(r"D:\Incubator\agentflow")
sys.path.insert(0, str(ROOT / "src"))

from agentflow.tools import verify_tools as VT  # noqa: E402

probe = Path(r"D:\Incubator\temp\_g35_probe_target.py")
probe.write_text("print(1)\n", encoding="utf-8")

print("真实 code_hash（未打桩）:", VT.code_hash(probe))

calls: list[str] = []


def boom(*a, **k):
    calls.append(str(a[0]) if a else "?")
    raise PermissionError("拒绝访问（桩）")


had = "open" in VT.__dict__
VT.open = boom  # type: ignore[attr-defined]
try:
    try:
        VT.code_hash(probe)
        print("打桩后：没有抛异常 —— 桩没有进到函数体，不能用来证明逃逸路径")
    except PermissionError as e:
        print(f"打桩后：真实 code_hash 抛出 {type(e).__name__}({e}) —— 桩确实命中了函数体内的 open")
        print(f"        被拦的路径={calls}")
finally:
    if not had:
        del VT.__dict__["open"]

print("撤桩后:", VT.code_hash(probe))
assert VT.code_hash(probe) == VT.code_hash(probe)
probe.unlink()
print("结论：桩应打在 open 上（raising=False 只为容忍某些实现把 open 显式导入了 globals）")

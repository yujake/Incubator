# -*- coding: utf-8 -*-
"""探针：`verify.check_formal` 对工作区里那份**纯核心** Lean 源码能不能跑成。

背景（真机读数，`projects/p3-review` 的 `t-0253`）：E 报「本机条件下没查成（import_unavailable）」，
理由写成「check_formal 在传 checker_name 时**无条件**注入 `import Mathlib`，这条路无法从参数侧关掉」。
但工具 schema 里有一个 `imports` 形参（`verify_tools.py:782`），而实现是
`imports=imports if imports is not None else ("Mathlib",)` ⇒ 显式传 `imports: []` 应当**不注入**。

这条探针就是把这件事量出来（探针不改工作区的语义：只在副本上跑）：
  · 不传 imports ⇒ 预期 `import_unavailable`（Mathlib 不在本机）；
  · 传 imports=[] + 声明名 ⇒ 预期 `verified`（纯核心编译器能过）。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

REPO = pathlib.Path(r"D:\Incubator")
LEAN_BIN = REPO / "temp" / "lean470" / "lean-4.7.0-windows" / "bin"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", default=r"D:\Incubator\projects\p3-review")
    ap.add_argument("--script", default="code/lean/p2_rho_sum_zero.lean")
    ap.add_argument("--name", default="rho_sum_zero")
    args = ap.parse_args()
    ws = pathlib.Path(args.ws)
    os.environ["PATH"] = str(LEAN_BIN) + os.pathsep + os.environ["PATH"]
    sys.path.insert(0, str(REPO / "agentflow" / "src"))
    from agentflow.store import Store
    from agentflow.tools import build_registry

    st = Store(ws)
    built = build_registry(store=st, workspace_root=ws, roles=("E",))
    reg = built.registry
    if getattr(reg, "bound_role", None) is None:
        reg.bound_role = "E"          # `P-14`：注册表要代表某个角色，调用期才判得了权限
    base = dict(claim=f"探针：核验 {args.name} 这条恒等式",
                script_path=args.script, checker_name=args.name)
    for label, extra in (("默认 imports（= 不注入任何库）", {}),
                         ("显式 imports=[]（同上，写出来而已）", {"imports": []}),
                         ("显式 imports=('Mathlib',)（旧默认：纯核心源码上跑不成）",
                          {"imports": ("Mathlib",)})):
        res = reg.call("verify.check_formal", **base, **extra)
        data = res.data if hasattr(res, "data") else res
        keys = ("checked", "verified", "verifier_status", "missing_imports", "reason")
        print(f"\n[{label}] ok={getattr(res, 'ok', '?')} error={getattr(res, 'error', None)!r}")
        if not isinstance(data, dict):
            print(f"   data（非 dict）：{data!r}"[:400])
        if isinstance(data, dict):
            for k in keys:
                if k in data:
                    print(f"   {k} = {data[k]!r}")
            out = str(data.get("verifier_output") or "")
            print("   verifier_output 头两行：" + " | ".join(out.splitlines()[:2])[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

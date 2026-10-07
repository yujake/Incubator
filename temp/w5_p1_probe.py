"""W5：P1 `verify.check_formal` 的三条负控 + 一条真实正控（真跑本机 Lean 4.7.0）。

用工具层的注册表调用（与调用方走同一条路），不直接调函数。
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(r"D:\Incubator\agentflow\src").resolve()))

LEAN_BIN = pathlib.Path(r"D:\Incubator\temp\lean470\lean-4.7.0-windows\bin")
os.environ["PATH"] = str(LEAN_BIN) + os.pathsep + os.environ["PATH"]

from agentflow import store as ST  # noqa: E402
from agentflow.tools import verify_tools as VT  # noqa: E402
from agentflow.tools.base import ToolRegistry  # noqa: E402

NO_MATHLIB: list[str] = []  # 本机无 Mathlib ⇒ 带任何 import 都会 compile_error

root = pathlib.Path(tempfile.mkdtemp(prefix="w5_p1_"))
st = ST.Store(root)
st.init()
reg = ToolRegistry(name="w5")
VT.register(reg, store=st, root=root)

GOOD = "theorem one_plus_one : 1 + 1 = 2 := rfl\n"
SORRY = "theorem one_plus_one : 1 + 1 = 2 := by sorry\n"
OTHER = "theorem two_plus_two : 2 + 2 = 4 := rfl\n"


def show(label: str, res) -> dict:
    d = res.data or {}
    print(f"--- {label}")
    print(f"    ok={res.ok} kind={res.meta.get('kind')!r} error={(res.error or '')[:110]!r}")
    print(f"    checked={d.get('checked')!r} verified={d.get('verified')!r} "
          f"reason={d.get('reason')!r}")
    print(f"    detail={str(d.get('detail'))[:190]!r}")
    print(f"    verifier_output={str(d.get('verifier_output'))[:150]!r}")
    print(f"    meta: status={res.meta.get('status')!r} ran={res.meta.get('ran')!r} "
          f"axioms={res.meta.get('axioms')!r} sorry_count={res.meta.get('sorry_count')!r} "
          f"evidence_kind={res.meta.get('evidence_kind')!r}")
    return d


print("=" * 72)
print("[0] 真实后端探测（PATH 已加入 " + str(LEAN_BIN) + "）")
det = VT.detect_verifier()
print(f"    checked={det['checked']} available_names={det['available_names']}")
print(f"    version={[x.get('version') for x in det['available']]}")

print()
print("[负控 ①] 源码含 sorry ⇒ 绝不能是 proof 成功")
d1 = show("source 含 sorry", reg.call(
    "verify.check_formal", claim="1+1=2", source=SORRY, name="one_plus_one",
    imports=NO_MATHLIB))
assert d1["verified"] is not True, "含 sorry 不许判通过"
assert d1["reason"] == "uses_sorry", d1["reason"]
print("    >>> 断言通过：verified 不是 True，reason=uses_sorry")

print()
print("[负控 ②] 环境无检查器 ⇒ checked=False 且理由明确（不是'通过'）")
_orig = VT.detect_verifier
VT.detect_verifier = lambda: {"checked": True, "available": [], "available_names": [],
                              "reason": "（注入：本环境没有 Lean/Coq/Isabelle）",
                              "probe_errors": []}
d2 = show("无后端", reg.call("verify.check_formal", claim="1+1=2", source=GOOD,
                              name="one_plus_one", imports=NO_MATHLIB))
VT.detect_verifier = _orig
assert d2["checked"] is False and d2["verified"] is None and d2["reason"] == "no_backend"
print("    >>> 断言通过：checked=False / verified=None / reason=no_backend")

print()
print("[负控 ③] 源码里没有那个声明 ⇒ 不得判成功")
d3 = show("声明名对不上", reg.call(
    "verify.check_formal", claim="1+1=2", source=OTHER, name="one_plus_one",
    imports=NO_MATHLIB))
assert d3["verified"] is not True
assert d3["reason"] == "decl_mismatch", d3["reason"]
print("    >>> 断言通过：verified 不是 True，reason=decl_mismatch")

print()
print("[正控] 本机真实 Lean 4.7.0 真跑一次最小证明（无 Mathlib 的命题）")
d4 = show("真实正控", reg.call("verify.check_formal", claim="1+1=2", source=GOOD,
                                name="one_plus_one", imports=NO_MATHLIB,
                                timeout_sec=120))
assert d4["verified"] is True and d4["reason"] == "verified", (d4["reason"], d4["detail"])
print("    >>> 断言通过：verified=True / reason=verified（唯一给 proof 级证据的状态）")

print()
print("[附加] 真实后端 + 声称的声明名不存在 ⇒ 也必须红（退出码 0 不许放过）")
d5 = show("真后端 + 名字对不上", reg.call("verify.check_formal", claim="x", source=GOOD,
                                          name="no_such_decl", imports=NO_MATHLIB,
                                          timeout_sec=120))
assert d5["verified"] is not True
print("    >>> 断言通过：退出码 0 但声明没被检查到 ⇒ 不判通过")
print("=" * 72)
print("ALL P1 ASSERTIONS PASSED")
print(json.dumps({"neg1": d1["reason"], "neg2": d2["reason"], "neg3": d3["reason"],
                  "pos": d4["reason"], "extra": d5["reason"]}, ensure_ascii=False))

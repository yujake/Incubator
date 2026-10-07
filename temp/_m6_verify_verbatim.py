# -*- coding: utf-8 -*-
"""M6 的一次性等价证明：拆出来的每个动作方法，**源码非空行**与拆分前逐字相同。

做法：从 `git show <ref>:agentflow/src/agentflow/agent_c.py` 取拆分前的文件，
用 AST 找出每个动作方法的行区间；再在新包里取同一个方法（`inspect.getsource`）逐行比对。
相对 import 的层级由拆分器加深了一层（`. → ..`），比对时把它归一化掉（**只**归一化这一点，
其余任何差异都算不同）。

读数（脚本自己打印）：每个动作的"行数 / 是否逐字相同 / 差异行数"。
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(r"D:\Incubator")
PROJ = ROOT / "agentflow"
REL = os.environ.get("M6_FILE", "agentflow/src/agentflow/agent_c.py")
IMPORT_RE = re.compile(r"^(\s*)from (\.+)(.*)$")


def normalize(line: str) -> str:
    """把相对 import 的层级归一化（拆包时 `.` 变 `..`，这不是语义改动）。"""
    m = IMPORT_RE.match(line)
    return f"{m.group(1)}from .{m.group(3)}" if m else line


def main() -> int:
    sys.path.insert(0, str(PROJ / "src"))
    ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    before = subprocess.run(["git", "show", f"{ref}:{REL}"], cwd=ROOT,
                            capture_output=True).stdout.decode("utf-8")
    tree = ast.parse(before)
    lines = before.splitlines()
    cls_name = os.environ.get("M6_CLS", "AgentC")
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
    module = importlib.import_module(os.environ.get("M6_MOD", "agentflow.agent_c"))
    spec = module.SPEC
    actions = [a.handler_name for a in spec.actions]

    print(f"参照版：{ref}:{REL}（{len(lines)} 行）；动作 {len(actions)} 个")
    bad = 0
    for action in actions:
        node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == action)
        starts = [node.lineno, *[d.lineno for d in node.decorator_list]]
        old = [ln.strip() for ln in lines[min(starts) - 1:node.end_lineno] if ln.strip()]
        new = [ln.strip() for ln in inspect.getsource(getattr(getattr(module, cls_name), action)).splitlines()
               if ln.strip()]
        old_n = [normalize(ln) for ln in old]
        new_n = [normalize(ln) for ln in new]
        same = old_n == new_n
        if not same:
            bad += 1
            diff = [f"{i}: 旧 {a!r} / 新 {b!r}" for i, (a, b) in enumerate(zip(old_n, new_n))
                    if a != b][:3]
            print(f"  [不一致] {action}：旧 {len(old_n)} 行 / 新 {len(new_n)} 行；{diff}")
        else:
            where = getattr(getattr(module, cls_name), action).__module__
            print(f"  [逐字相同] {action:22s} {len(old_n):4d} 行  现在住在 {where}")
    print(f"\n合计：{len(actions) - bad}/{len(actions)} 个动作逐字搬移")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

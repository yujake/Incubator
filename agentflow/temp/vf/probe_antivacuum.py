# -*- coding: utf-8 -*-
"""VF 路反真空探针：分别把三处修复「改回旧形态」，量判据会不会红。

三种旧形态：
- `key`    ：幂等键命名空间改回 `task:<号>`；
- `vseam`  ：不登记 `role_seam("V")`（工具路径回到 env 现造第二条缝）；
- `sid`    ：秘书装配不读 ambient sid（回到 `sid=None`）；
- `all`    ：三者一起（= 改前的产品形态，用来复现 6 笔吞账 + 7 条缺省会话）。

用法（在 `agentflow/` 下）::

    $env:PYTHONPATH='src;tests'; python -B temp/vf/probe_antivacuum.py [key|vseam|sid|all|none]
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
PROJ = HERE.parents[1]
sys.path.insert(0, str(PROJ / "src"))
sys.path.insert(0, str(PROJ / "tests"))

import pytest  # noqa: E402

from test_rehearsal_cli_proof_main_chain import (  # noqa: E402
    _ledger_identity, _run, _session_split,
)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "none"
    from agentflow import llmseam as LS
    import agentflow.secretary as SEC

    mp = pytest.MonkeyPatch()
    if mode in ("key", "all"):
        mp.setattr(LS, "_idem_namespace",
                   lambda **kw: f"task:{kw.get('task_id') or ''}")
    if mode in ("vseam", "all"):
        real = LS.set_role_seam

        def _skip_v(role, llm):
            real(str(role), None if str(role) == "V" else llm)

        mp.setattr(LS, "set_role_seam", _skip_v)
    if mode in ("sid", "all"):
        mp.setattr(SEC, "_ambient_session_sid", lambda: None)
    try:
        got = _run(pathlib.Path(tempfile.mkdtemp(prefix="vf-anti-")), mp, lean="0")
    finally:
        mp.undo()
    reading = _ledger_identity(got["ws"], got["store"])
    split = _session_split(got["ws"])
    out = {
        "mode": mode,
        "calls": reading["calls"],
        "rows": reading["rows"],
        "duplicates": [(c["role"], c["session"]) for c in reading["duplicates"]],
        "elsewhere": [(c["session"], c["role"], c["task_id"])
                      for c in split["elsewhere"]],
        "settle_rows": len([r for r in got["store"].rows("usage_ledger")]) - reading["rows"],
    }
    (HERE / f"antivacuum-{mode}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8", newline="")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

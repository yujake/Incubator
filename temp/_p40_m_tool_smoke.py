"""§40 的活体读数：M 的 16 件工具**每件至少真调一次**（找的是同类潜伏 bug）。

为什么值得单独跑：§37 那个 `NameError` 之所以活到真机才现形，是因为
"没人测的分支就是没测的分支" —— 既有用例只走了每个工具的一条快乐路径。
这个探针换一个问法：**这个工具调起来会不会抛异常/崩**（不是问结果对不对）。
三态纪律照旧：样例缺了某个必填参数就记 `unknown`（没查成），不记 `pass`。

跑法（在 `agentflow/` 下）：
    $env:PYTHONPATH='src'; python -B ..\\temp\\_p40_m_tool_smoke.py
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1] / "agentflow"
sys.path.insert(0, str(REPO / "src"))

from agentflow import store as S  # noqa: E402
from agentflow.tools import ROLES, build_registry  # noqa: E402

#: 参数名 → 样例值（按上面打印出来的 schema 逐个对过）。缺样例的必填参数记 unknown。
SAMPLES: dict[str, object] = {
    "target_role": "G", "action": "revise", "params": {"doc_id": "main"},
    "targets": [{"target_role": "G", "action": "revise", "params": {"doc_id": "main"},
                 "instance": "i1"}],
    "role_name": "G", "path": "out/paper/main.tex", "content": "smoke", "pattern": "smoke",
}
#: 逐工具覆盖：`fs.write` 要与 `fs.read`/`fs.stat` 用不同的路径（否则只会命中"已存在"那条分支）。
OVERRIDES: dict[str, dict[str, object]] = {
    "fs.write": {"path": "out/review/REPORT.md", "content": "smoke\n"},
}


def main() -> int:
    bad: list[str] = []
    unknown: list[str] = []
    with tempfile.TemporaryDirectory(prefix="p40_smoke_") as td:
        root = Path(td)
        (root / "data").mkdir()
        (root / "out" / "paper").mkdir(parents=True)
        (root / "out" / "paper" / "main.tex").write_text("% smoke\n", encoding="utf-8")
        st = S.Store(root)
        st.init()
        reg = build_registry(store=st, workspace_root=root, roles=tuple(ROLES)).registry
        # `conductor.ensure_project` 的 `projects_dir` 缺省指向**默认 projects 目录**
        # （`agentflow.projects.projects_dir(None)`）而不是当前工作区 —— 2026-10-02 实测：
        # 不带这一行时，这个探针在真盘的 `D:\Incubator\projects\` 下建了 project12/project13
        # 两个空项目（§41.3 记了这次污染与清理）。所以这里必须把它指到临时目录里。
        overrides = dict(OVERRIDES)
        overrides["conductor.ensure_project"] = {"projects_dir": str(root / "_probe_projects")}

        for spec in sorted(reg.for_role("M"), key=lambda s: s.name):
            # `spec.params` 是 JSON Schema 子集：本工具层只用到 type/required/properties/enum/items
            required = list((spec.params or {}).get("required") or [])
            missing = [k for k in required if k not in SAMPLES]
            if missing:
                unknown.append(f"{spec.name}（没有样例的必填参数：{missing}）")
                print(f"  unknown  {spec.name:24s} 必填参数没有样例：{missing}")
                continue
            kwargs = {**{k: SAMPLES[k] for k in required}, **overrides.get(spec.name, {})}
            try:
                res = reg.call(spec.name, role="M", **kwargs)
                state = "ok" if res.ok else "fail"
                print(f"  {state:8s} {spec.name:24s} kind={res.meta.get('kind')!r} "
                      f"err={str(res.error)[:60]!r}")
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{spec.name}: {type(exc).__name__}: {exc}")
                print(f"  崩溃!    {spec.name:24s} {type(exc).__name__}: {exc}")
                traceback.print_exc()
    print()
    print(f"崩溃（抛异常）：{len(bad)} 件 {bad}")
    print(f"没查成（缺样例）：{len(unknown)} 件 {unknown}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

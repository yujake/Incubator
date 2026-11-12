# -*- coding: utf-8 -*-
"""两份冻结快照的逐格 diff（只读；重冻之前必须逐格看过的那份机器读数）。

`AGENTS.md` 把这两份快照列入禁改区，理由是：随手重冻，"声明与行为没变"就失去了唯一的
可比对象，而 `diff` 是"这一改到底动了哪一格"的唯一机器读数，必须由人逐格看过。判据面
（`tests/test_agent_surface_snapshot.py` / `tests/test_tool_surface_snapshot.py`）只回答
"快照与现况一致吗"，答不了"这一格从什么变成了什么" —— 这个脚本就是那一格。

它刻意不住进 `tests/`：它不是判据（没有"通过/失败"可言，人是来读 diff 的），写成用例
只会让一批"永远绿、没人读"的断言混进判据面。

三态退出码：0 = 逐格相同（重冻无事可做）；1 = 有差异（打印逐格 diff，这就是人要看的东西）；
2 = 没查成（快照读不到 / 被测模块 import 不了 / 现况算不出来）。`2` 绝不是 `0`。

已知盲区：只覆盖 `tests/golden/` 四份中的两份（agent 面 / tool 面）。`run_topic_snapshot.json`
与 `verify_all_snapshot.json` 的现况要跑一次真实工作区，代价与落盘面不同，不在本脚本里。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src"
TESTS = REPO / "tests"


def _load_snapshot_module(name: str):
    """按文件名 import `tests/` 下的快照模块（`tests` 不是包，不能普通 import）。

    两条路径在最前面插一次、之后一直留着：被测的 `_snapshot()` 是惰性 import
    （`from agentflow import capabilities as C` 写在函数体里），取完模块就把路径撤掉
    会让它在下一次调用时抛 `ModuleNotFoundError`。本进程只读、只跑一次，留着没有副作用。
    """
    for extra in (str(TESTS), str(SRC)):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    return __import__(name)


def _diff_agent() -> list[str]:
    """agent 面的逐格 diff（角色 -> 变了的字段名）。"""
    mod = _load_snapshot_module("test_agent_surface_snapshot")
    with tempfile.TemporaryDirectory(prefix="golden-agent-") as td:
        live = mod._snapshot(pathlib.Path(td))
    golden = json.loads(mod.GOLDEN.read_text(encoding="utf-8"))
    out: list[str] = ["== agent_surface =="]
    out.append(f"role_count={live['role_count']} "
               f"actions={sum(len(v['actions']) for v in live['roles'].values())} "
               f"tools_total={sum(len(v['tools']) for v in live['roles'].values())}")
    for role in sorted(set(golden["roles"]) | set(live["roles"])):
        got = golden["roles"].get(role, {})
        now = live["roles"].get(role, {})
        fields = [f for f in sorted(set(got) | set(now)) if got.get(f) != now.get(f)]
        if fields:
            out.append(f"  {role}: {fields}")
        if not now.get("tools"):
            out.append(f"  {role}: 一个工具都没有")
        missing = [a for a, sig in (now.get("handler_signatures") or {}).items()
                   if sig == "（类上没有这个方法）"]
        if missing:
            out.append(f"  {role}: 动作缺实现 {missing}")
    for key in ("role_count", "schema_roles", "tool_roles", "read_only_roles",
                "non_summonable", "wiring_status", "role_registry"):
        if golden.get(key) != live.get(key):
            out.append(f"  top[{key}] changed")
    return out


def _diff_tool() -> list[str]:
    """tool 面的逐格 diff（声明 / 签名 / 角色面）。"""
    mod = _load_snapshot_module("test_tool_surface_snapshot")
    with tempfile.TemporaryDirectory(prefix="golden-tools-") as td:
        live = mod._snapshot(pathlib.Path(td))
    golden = json.loads(mod.GOLDEN.read_text(encoding="utf-8"))
    out: list[str] = ["== tool_surface =="]
    out.append(f"summary.count={live['summary'].get('count')} "
               f"(golden {golden['summary'].get('count')})")
    if live["summary"] != golden["summary"]:
        keys = [k for k in sorted(set(live["summary"]) | set(golden["summary"]))
                if live["summary"].get(k) != golden["summary"].get(k)]
        out.append(f"  summary changed: {keys}")
    for key in ("roles", "roles_with_m", "readonly_write_leaks", "cli"):
        if live[key] != golden.get(key):
            out.append(f"  [{key}] changed")
    changed_decls = [n for n in sorted(set(golden["declarations"]) | set(live["declarations"]))
                     if golden["declarations"].get(n) != live["declarations"].get(n)]
    changed_sigs = [n for n in sorted(set(golden["signatures"]) | set(live["signatures"]))
                    if golden["signatures"].get(n) != live["signatures"].get(n)]
    out.append(f"  declarations changed: {changed_decls}")
    out.append(f"  signatures changed: {changed_sigs}")
    for role in ("A", "B", "C", "D", "E", "F", "G", "H", "V", "L", "M"):
        if not live["roles"].get(role):
            out.append(f"  {role}: 工具面为空")
    return out


def _changed(lines: list[str]) -> bool:
    """除了表头与那几行纯读数，正文里还有没有"变了"的行。"""
    for line in lines:
        if line.startswith("==") or line.startswith("summary.") or line.startswith("role_count="):
            continue
        if line.startswith("  declarations changed: []") or \
                line.startswith("  signatures changed: []"):
            continue
        if line.startswith("  "):
            return True
    return False


def main() -> int:
    try:
        agent = _diff_agent()
        tool = _diff_tool()
    except Exception as exc:                                     # noqa: BLE001 - 三态：没查成
        print(f"没查成：算不出逐格 diff（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 2
    for block in (agent, tool):
        print("\n".join(block))
    return 1 if (_changed(agent) or _changed(tool)) else 0


if __name__ == "__main__":
    sys.exit(main())

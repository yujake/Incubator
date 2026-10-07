"""手工迁移那 5 类"没有同一行原文"的旧坐标（拆包后它们换了形状，机械匹配不到）。

逐条给出**为什么这么映射**（依据 = 旧行原文 + 新文件里的对应物）：

| 旧坐标 | 旧行原文（`65746a5:webui.py`） | 新坐标 | 依据 |
|---|---|---|---|
| `webui.py:322` | `if kind == "agent_run_start":` | `webui/state.py:286` | `_scan` 里判 run 起点的那个分支（逐字同文） |
| `webui.py:974` | `def _answer_action(...)` | `webui/writes.py:90` | 回答提交那一支搬进 `writes.py` 的 `answer()`（形状从"返回 3 元组的动作函数"变成"写面函数"） |
| `webui.py:1144` | `if path == "/api/state":` | `webui/routes.py:97` | if 链换成路由表：那一行现在是 `("GET", "/api/state", "handle_state")` |
| `webui.py:1148` | `if path.startswith("/run/"):` | `webui/routes.py:95` | 同上：`("GET", "/run/{sid}", "handle_run")` |
| `webui.py:1167` | `if path != "/answer":` | `webui/server.py:341` | `handle_answer` 的入口（POST 那一支的实现） |

映射不是猜的：上表每一行都能用
`git show <base>:agentflow/src/agentflow/webui.py | Select-Object -Index <N-1>`
与 `Select-String -Path agentflow/src/agentflow/webui/*.py -Pattern <新行原文>` 复核。
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(r"D:\Incubator")
MAP = {
    "webui.py:322": "webui/state.py:286",
    "webui.py:974": "webui/writes.py:90",
    "webui.py:1144": "webui/routes.py:97",
    "webui.py:1148": "webui/routes.py:95",
    "webui.py:1167": "webui/server.py:341",
}
DRAFTS = sorted((REPO / "draft").glob("7*.md"))


def main() -> int:
    write = "--write" in sys.argv
    total = 0
    for doc in DRAFTS:
        text = doc.read_text(encoding="utf-8")
        new = text
        hits: list[str] = []
        for old, fresh in MAP.items():
            if old not in new:
                continue
            hits.append(f"{old} -> {fresh}（{new.count(old)} 处）")
            new = new.replace(old, fresh)
        if new != text:
            print(f"{doc.name}:")
            for row in hits:
                print("  " + row)
            total += len(hits)
            if write:
                doc.write_text(new, encoding="utf-8", newline="")
    print(f"\n涉及 {total} 类替换" + ("" if write else "（dry-run；加 --write 落盘）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

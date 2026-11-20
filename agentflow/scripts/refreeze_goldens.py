# -*- coding: utf-8 -*-
"""按现值重冻 `tests/golden/` 的两份「面」快照（agent 面 / tool 面），或只报差异。

## 为什么这份重冻逻辑要进 `scripts/`

`AGENTS.md` 把这两份快照列进禁改区：随手重冻，「声明与行为没变」就失去了唯一可比对象。
所以「重冻」这件事本身必须是一条可复跑、可审的命令，而不是某趟真机里的一段临时脚本。
（原稿：`temp/_p240_refreeze_goldens.py`，2026-11-20 提升。）

## 口径：先 `import conftest`，再借判据自己的 `_snapshot` 与写盘格式

为什么不能直接跑 `python -B tests/test_*_surface_snapshot.py --write`：那两条命令
要求 `agentflow` 在 `sys.path` 上，且不经过 `tests/conftest.py`（设置文件 / 机器事实
不被钉住）⇒ 写出来的基线可能不是判据那一套口径认的那一份。这里先 import conftest
（它把 `src/` 注入 `sys.path`、把设置文件钉到不存在的路径、清掉本机事实类环境变量），
再复用两个判据文件自己的 `_snapshot` 与写盘格式
（`ensure_ascii=False, indent=1, sort_keys=True` + 末尾换行、LF）。

## 用法（在 `agentflow/` 下）

    python scripts/refreeze_goldens.py            # 只报：0=两份都与现值一致 / 1=有差异 / 2=没查成
    python scripts/refreeze_goldens.py --write    # 真的重冻（禁改区动作：写完仍要人逐格看过）

缺省只报不写：重冻是禁改区动作，不该被一次「顺手跑一下」触发。
"""
from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(TESTS))


def _modules():
    """导入两个判据文件（先 conftest：环境钉在它里面）。"""
    import conftest  # noqa: F401  —— 设置文件 / 机器事实 / Lean 档都钉在这里

    return (importlib.import_module("test_agent_surface_snapshot"),
            importlib.import_module("test_tool_surface_snapshot"))


def _snapshot_now(mod) -> dict:
    """按判据自己的口径现算一份快照（在临时目录里装配，不碰仓库）。"""
    with tempfile.TemporaryDirectory(prefix="refreeze-golden-") as td:
        return mod._snapshot(pathlib.Path(td))


def _same(a: dict, b: dict) -> bool:
    return json.dumps(a, ensure_ascii=False, sort_keys=True) == \
        json.dumps(b, ensure_ascii=False, sort_keys=True)


def _write(mod, snap: dict) -> None:
    mod.GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    mod.GOLDEN.write_text(
        json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="重冻 tests/golden 的两份面快照（缺省只报差异，--write 才落盘）")
    ap.add_argument("--write", action="store_true",
                    help="把两份快照写成现值（禁改区动作：写完仍要人逐格看过 diff）")
    args = ap.parse_args(argv)

    try:
        agent_mod, tool_mod = _modules()
    except Exception as exc:  # noqa: BLE001 - 任何一步失败都是"没查成"
        print(f"[unknown] 判据文件导入不了：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    failed = False
    for label, mod in (("agent_surface_snapshot.json", agent_mod),
                       ("tool_surface_snapshot.json", tool_mod)):
        try:
            now = _snapshot_now(mod)
            old = json.loads(mod.GOLDEN.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[unknown] {label} 算不出/读不到：{type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 2
        same = _same(now, old)
        print(f"  [{'same' if same else 'DIFF'}] {label}")
        if same:
            continue
        failed = True
        if args.write:
            _write(mod, now)
            print(f"        已重冻 → {mod.GOLDEN}")
        else:
            print("        （只报；要落盘加 --write —— 这是禁改区动作，先逐格看过 diff）")
    if failed and not args.write:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

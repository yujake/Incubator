# -*- coding: utf-8 -*-
"""`json.dumps` 必须带 `default=`（真机崩溃族的一次性收口）。

## 现场（2026-10-17，T1/T4/T5 三趟并发）

三趟各撞到 1–2 次同一个崩溃：

```
TypeError: Object of type TopicalityReport is not JSON serializable
```

它此前分三处修过（`store` / `secretary.append_jsonl` / `canonical_json_text`），但只要
还有一处漏网，同一类崩溃就会在别的路径上再来一次 —— 于是改成"全仓一次扫干净"：
`src/agentflow/**` 里每一处 `json.dumps(...)` 都带 `default=str`。

为什么这样安全：对纯 JSON 数据，`default=str` 不改变任何字节（输出与原来逐字相同）
⇒ 历史哈希、快照、回执都不受影响；对含非 JSON 值的载荷，此前根本 dump 不出来，
所以没有"既有字节"会被改掉。

本判据用 AST（不看正则、不看注释）扫运行路径，扫到一处就红。
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "src" / "agentflow"


def _is_json_dumps(node: ast.Call) -> bool:
    fn = node.func
    if isinstance(fn, ast.Attribute) and fn.attr == "dumps":
        base = fn.value
        return (isinstance(base, ast.Name) and base.id == "json") or \
            (isinstance(base, ast.Attribute) and base.attr == "json")
    return False


def test_every_json_dumps_has_a_default() -> None:
    """正控：全仓每一处 `json.dumps(...)` 都带 `default=`（缺一处就红）。"""
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:          # 语法坏的文件由 compileall 负责抓，这里跳过
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_json_dumps(node):
                if not any(k.arg == "default" for k in node.keywords):
                    offenders.append(f"{path.relative_to(ROOT.parent.parent)}:{node.lineno}")
    assert offenders == [], (
        "这些 `json.dumps(...)` 没有 `default=` ⇒ 载荷里一旦有非 JSON 值就抛 "
        "`TypeError`（真机 T1/T4/T5 的崩溃族）：" + ", ".join(offenders))

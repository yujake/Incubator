"""JSONL 文件的读法 —— 唯一实现（`draft/36` 的 T-6）。

## 为什么单列一个模块

`draft/36` 的体检说"同一件事两处实现"有 7 组。逐对查证之后（`draft/28` §211 有逐对读数），
其中 6 组要么是假重复（名字相同、对象不同：`ledger_path` 服务的是两份不同的台账、
`render_markdown` 一个是产物台账一个是稿件渲染），要么早就合并过（`evidence.parse_claims`
与 `doc_tools.citation_ref_parts` 都是写明了理由的纯转发）。真正还剩的只有一组：

```text
artifacts.read_ledger(root)     ← 一个工作区的产物台账 ARTIFACTS.jsonl
signatures.read_ledger(path)    ← 稿件签名台账 DOC-SIGNATURES.jsonl
sessions.read_session(root, sid) ← 一段会话记录 <sid>.jsonl
```

三份完整的实现，逐字同形（连"坏行逐条报出、不静默跳过"的注释都一样），
唯一差别是 `signatures` 那句措辞写成"不是 JSON 对象"、另两处写"不是对象"。

## 为什么值得合并（不是"为了整齐"）

它们是同一类磁盘格式的读法：坏行的定义、空行的处理、"读不出来"与"没有这一行"的
三态区分、"合法 JSON 但不是对象"这一档，都是同一条判据。三份实现意味着：
改一处（比如将来要支持 BOM 或 CRLF）另两处不会跟着变，而漂移的表现是
"同一份坏文件，`verify` 说它坏、`session show` 说它好"——没有任何东西会报错。

## 为什么不是塞进 `textutil`

`textutil` 的职责是"文本规范化 / 相似度 / slug / 页码解析"（它自己的 docstring），
往里面塞"文件怎么读"会让它的边界变模糊。一个 20 行的模块只做一件事，
比在别处加一节更难被误读。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["read_jsonl"]


def read_jsonl(path: str | Path) -> tuple[list[dict], list[str]]:
    """读一个 JSONL 文件；返回 `(记录, 坏行说明)`。

    三态纪律在这四行里：

    - 文件不存在 ⇒ `([], [])` —— 那是合法初态（还没写过），不是问题；
    - 空行 ⇒ 跳过（不算记录、也不算问题）；
    - 某行不是合法 JSON ⇒ 记一条带行号的问题，不静默跳过；
    - 某行是合法 JSON 但不是对象（例如 `[1, 2, 3]`）⇒ 同样记一条问题。

    为什么后两档要分开报：读者拿到的坏行说明要能回答"是文件坏了，还是有人往里写了
    非对象的行"—— 折成一句"有坏行"就没法查了（`tests/test_sessions.py` 里那条
    "合法 JSON 但不是对象"的负控就是钉这一档的）。
    """
    p = Path(path)
    if not p.is_file():
        return [], []
    records: list[dict] = []
    problems: list[str] = []
    for i, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            obj: Any = json.loads(raw)
        except ValueError as e:
            problems.append(f"第 {i} 行读不出来（{type(e).__name__}: {e}）")
            continue
        if not isinstance(obj, dict):
            problems.append(f"第 {i} 行不是对象")
            continue
        records.append(obj)
    return records, problems

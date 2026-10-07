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

## 四态（R4 组 6②：把"文件在不在"与"读的时候炸了"从"没有记录"里分出来）

`read_jsonl` 只给 `(记录, 坏行说明)` 两样东西，于是下面两件事无处可报：

- 文件不存在与文件在但一条记录也没有，返回值逐字相同（都是 `([], [])`）；
- 读取本身失败（无效 UTF-8、权限、把目录当文件读）在改前要么崩在调用方、要么
  被 `is_file()` 挡掉当成"不存在" —— 读者拿不到"是没写过，还是读不出来"。

所以本模块另出一个 `read_jsonl_state`：行内容的口径一个字不改（坏行怎么算、
空行怎么跳过、返回什么记录），只在旁边多报一个 `state`。`read_jsonl` 变成它的薄包装，
签名与"文件不存在 ⇒ `([], [])`"这条既有契约都保持原样。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["READ_STATES", "read_jsonl", "read_jsonl_state"]

#: `read_jsonl_state` 的四个取值。三态纪律在这里是"四态"：`absent` 与 `empty` 是两种
#: 不同的"没有记录"（一个是还没写过、一个是写了但没内容），`unreadable` 是"没查成"。
READ_STATES = ("absent", "empty", "ok", "unreadable")


def read_jsonl_state(path: str | Path) -> tuple[list[dict], list[str], str]:
    """读一个 JSONL 文件；返回 `(记录, 坏行说明, 四态之一)`。

    两条轴是正交的，别把它们折在一起看：

    - `state` 说的是"这一格查到什么程度"：
      - `absent` —— 路径不存在（合法初态：还没写过）；
      - `empty` —— 文件在、但一条记录也没读出来（空行不算记录）；
      - `ok` —— 读到了至少一条记录；
      - `unreadable` —— 没查成：读取本身失败（`OSError` 一族，或不是 UTF-8）。
        这一档不是"没有记录"，两者的区别正是本函数存在的理由。
    - `problems` 说的是"坏在哪几行"：某行不是合法 JSON、或合法 JSON 但不是对象
      （例如 `[1, 2, 3]`），逐条带行号报出，不静默跳过。

    所以"文件里全是坏行"的形状是 `([], [第 1 行…], "empty")` —— 状态说"没读出记录"、
    说明说"为什么"。折成一句"有坏行"就没法查了（`tests/test_sessions.py` 里那条
    "合法 JSON 但不是对象"的负控就是钉这一档的）。
    """
    p = Path(path)
    if not p.exists():
        return [], [], "absent"
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        # 把"读取失败"落成一档可读的状态，而不是让异常冒到调用方：
        # 调用方拿到的仍是二元组（`read_jsonl`），但这里能说清"是读不出来"。
        return [], [f"读不出来（{type(e).__name__}: {e}）"], "unreadable"
    records: list[dict] = []
    problems: list[str] = []
    for i, raw in enumerate(text.splitlines(), 1):
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
    return records, problems, ("ok" if records else "empty")


def read_jsonl(path: str | Path) -> tuple[list[dict], list[str]]:
    """读一个 JSONL 文件；返回 `(记录, 坏行说明)`。

    这是 :func:`read_jsonl_state` 的薄包装，签名与行内容口径都不变：

    - 文件不存在 ⇒ `([], [])` —— 那是合法初态（还没写过），不是问题；
    - 空行 ⇒ 跳过（不算记录、也不算问题）；
    - 某行不是合法 JSON ⇒ 记一条带行号的问题，不静默跳过；
    - 某行是合法 JSON 但不是对象（例如 `[1, 2, 3]`）⇒ 同样记一条问题。

    与改前唯一的两处差别，都在"读取本身失败"这一档上，而且都是"把说不出口的
    变成说得出口的"：

    - 改前：密码错的编码/坏字节 ⇒ `read_text` 抛 `UnicodeDecodeError` 崩在调用方；
      现在 ⇒ 返回 `([], [读不出来（…）])`。
    - 改前：路径是个目录 ⇒ `is_file()` 为假 ⇒ 静默当成"不存在"（`([], [])`）；
      现在 ⇒ 同样返回一条 `读不出来（…）`。

    记录与坏行说明的产生方式一个字没动；要区分这四档请直接用
    :func:`read_jsonl_state`。
    """
    records, problems, _state = read_jsonl_state(path)
    return records, problems

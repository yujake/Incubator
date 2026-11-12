"""JSONL 文件的读法 —— 唯一实现。

## 为什么只有一个实现

产物台账 `ARTIFACTS.jsonl`、稿件签名台账 `DOC-SIGNATURES.jsonl`、会话记录
`<sid>.jsonl` 读的是同一类磁盘格式：坏行的定义、空行的处理、"读不出来"与"没有
这一行"的三态区分、"合法 JSON 但不是对象"这一档，都是同一条判据。各写一份意味着
改一处（比如将来要支持 BOM 或 CRLF）另几处不会跟着变，而漂移的表现是"同一份坏
文件，`verify` 说它坏、`session show` 说它好"—— 没有任何东西会报错。

## 为什么不是塞进 `textutil`

`textutil` 的职责是"文本规范化 / 相似度 / slug / 页码解析"（它自己的 docstring），
往里面塞"文件怎么读"会让它的边界变模糊。

## 四态（把"文件在不在"与"读的时候炸了"从"没有记录"里分出来）

`read_jsonl` 只给 `(记录, 坏行说明)` 两样东西，于是下面两件事无处可报：

- 文件不存在与文件在但一条记录也没有，返回值逐字相同（都是 `([], [])`）；
- 读取本身失败（无效 UTF-8、权限、把目录当文件读）要么崩在调用方、要么被
  `is_file()` 挡掉当成"不存在" —— 读者拿不到"是没写过，还是读不出来"。

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
    loads = json.loads
    for i, raw in enumerate(text.splitlines(), 1):
        # 空行判据与 `not raw.strip()` 等价（`str.strip()` 缺省剥的正是
        # `str.isspace()` 为真的字符），但不为每一行造一份剥好的副本：
        # 非法 JSON 行也要走到 `loads`，那儿本来就不怕首尾空白。
        if not raw or raw.isspace():
            continue
        try:
            obj: Any = loads(raw)
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

    读取本身失败的那一档同样折成一条问题，而不是让异常冒到调用方：

    - 坏字节 / 非 UTF-8 ⇒ 返回 `([], [读不出来（…）])`；
    - 路径是个目录 ⇒ 同样返回一条 `读不出来（…）`，不静默当成"不存在"。

    要区分这四档请直接用 :func:`read_jsonl_state`。
    """
    records, problems, _state = read_jsonl_state(path)
    return records, problems

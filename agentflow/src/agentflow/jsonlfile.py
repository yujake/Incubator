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

__all__ = ["read_jsonl", "read_jsonl_state"]

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
      （例如 `[1, 2, 3]`），带行号报出，不静默跳过。单行逐字报；连续同因的一整段
      折成一条「第 A–B 行（N 行；首条：…）」（口径见 :func:`_line_problems`）——
      "坏行是一整段"与"坏行有几条"是两件事，折的是后者。
    - 行界只有 `\\n`：`str.splitlines()` 会把 U+0085 等 Unicode 行界也切掉
      （真机 lp-ball-10 的 8 条合法行被切成 90 段，见下面循环上方的注释）。

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
    bad: list[tuple[int, str, str]] = []
    loads = json.loads
    # ---- 行界只有 `\n`（R10FIX-D1） -------------------------------------------
    #
    # 这里曾经是 `text.splitlines()`。`str.splitlines()` 按 Unicode 行界切：
    # `\x0b \x0c \x1c \x1d \x1e \x85 \u2028 \u2029` 全算，而 JSONL 的行界只有 `\n`。
    # 真机 lp-ball-10（2026-11-19）的会话第 522/554/556/568/570/608/610/614 行带着
    # 文献抽取文本里的 82 个 U+0085（NEL）⇒ 8 条合法 JSON 行被切成 90 段，
    # `read_session` 只读出 3659/3667 条、报 84 条坏行；收工那三格
    # （`roster_registration` / `summon_consumption` / `verdict_escalation`）因此
    # `checked=false`，M 的信箱每一步都把同一批坏行重报一遍（4589 条 note）。
    # 判据 `tests/test_jsonl_line_boundary_is_newline_only.py`。
    for i, raw in enumerate(text.split("\n"), 1):
        # 空行判据与 `not raw.strip()` 等价（`str.strip()` 缺省剥的正是
        # `str.isspace()` 为真的字符），但不为每一行造一份剥好的副本：
        # 非法 JSON 行也要走到 `loads`，那儿本来就不怕首尾空白。
        if not raw or raw.isspace():
            continue
        try:
            obj: Any = loads(raw)
        except ValueError as e:
            bad.append((i, "读不出来", f"{type(e).__name__}: {e}"))
            continue
        if not isinstance(obj, dict):
            bad.append((i, "不是对象", ""))
            continue
        records.append(obj)
    return records, _line_problems(bad), ("ok" if records else "empty")


def _line_problems(bad: list[tuple[int, str, str]]) -> list[str]:
    """坏行说明：单行逐字沿用老格式，连续同因的那一截折成「行号范围 + 行数」。

    为什么要折（R10FIX-D1 的第二半）：一行坏掉会连带把后面几行切成碎片，一份 84 条
    坏行的文件逐行报出 84 句，每一句都进 M 的 `run.notes` —— 真机那趟同一批 84 个
    行号被重报了 55 次（4589 条）。折成一段一句之后，"读不出来的是一整段"这件事
    仍然可读（首尾行号 + 行数 + 首条原因），而条数不再随文件大小膨胀。

    口径：

    - 单行 ⇒ 与改前逐字相同（`第 N 行读不出来（Type: msg）` / `第 N 行不是对象`）——
      既有判据与调用方都按这个字面读；
    - 连续（行号相邻）且同一类（都是"读不出来"或都是"不是对象"）⇒ 一条
      `第 A–B 行…（N 行；首条：…）`；不同类不合并（否则"不是对象"这个读数会被
      吞进 JSON 语法错误里）。
    """
    out: list[str] = []
    run: list[tuple[int, str, str]] = []

    def _flush() -> None:
        if not run:
            return
        first = run[0]
        last = run[-1]
        if len(run) == 1:
            if first[1] == "不是对象":
                out.append(f"第 {first[0]} 行不是对象")
            else:
                out.append(f"第 {first[0]} 行读不出来（{first[2]}）")
        elif first[1] == "不是对象":
            out.append(f"第 {first[0]}–{last[0]} 行不是对象（{len(run)} 行）")
        else:
            out.append(f"第 {first[0]}–{last[0]} 行读不出来（{len(run)} 行；"
                       f"首条：{first[2]}）")
        run.clear()

    for item in bad:
        if run and not (item[0] == run[-1][0] + 1 and item[1] == run[-1][1]):
            _flush()
        run.append(item)
    _flush()
    return out


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

# -*- coding: utf-8 -*-
"""五处登记的「账骨架」：把判据算出来的差渲染成可以直接粘贴的整行 / 整段。

## 这一层是什么（`docs/DEVELOPMENT-SPEC.md` 第 17.1 节的检测面）

这条红以前是「读报错 → 翻表 → 手抄」：判据只报「差在哪」，人还得自己照着表的
格式把那一行抄出来，而抄错时没有任何东西会红。本模块把「差」直接渲染成目标
文件里的那一行（缩进、引号、逗号、markdown 竖线都照抄），人只剩「复核 + 补一句
理由」。第 17.1 节把这件事叫「红必须带着账骨架来」。

## 三条纪律

1. 纯函数：输入是差集 / 编辑清单，输出是字符串。不读盘、不写盘、不改基线
   （第 17.3 / 17.4 节：自动写盘等于把被判者升成判据；自动重冻等于让「改参数名 /
   删返回键」从一条红变成一次静默放行）。
2. 格式贴着目标文件的真实字节 —— 「能粘贴」是这一层唯一的价值，差一个字符
   它就只是又一段要人翻译的散文。
3. 理由一律留占位：第 17.2 节那三问只有人能答，机器只负责把格子排好。

## 落点与格式出处

每处都先读了它自己的判据与目标文件的字节，再照着写：

* 顶层模块注册表：`tests/test_release_all.py` 的 `_AGENTFLOW_TOP_LEVEL_MODULES`
  是 `dict[str, str]`，条目形如 `"store.py": "一行理由",`（缩进 4）；
* 拒绝码表：`tests/test_refusals.py` 的 `_FAILURES_NOT_REFUSALS` 是
  `dict[tuple[str, str], str]`，条目形如 `("agent_d/poll.py", ""): "一行理由",`
  （缩进 4），处数表 `_REPEAT_COUNTS` 形如 `("x.py", ""): 3,`；
* `returns` 基线：`tests/fixtures/tool_declaration_baseline.json` 是两空格缩进的
  JSON，`contract_amendments` 数组元素缩进 4、键缩进 6，末尾元素带逗号；
* 文档索引：`docs/INDEX.md` 入册行是 `| [名字](名字) | 一行说明 |`，第 6 节
  不入册行是 `| 名字 | 为什么不入册 |`；
* 读图：`docs/READING-MAP.md` 开头那一句是三格读数（文件数 / 总行数 / 超过 800 行
  的文件数）加 `agent_loop.py` 行数，粗体星号也照抄。
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

#: 顶层模块登记那一条理由的占位。机器不替人写「为什么必须是顶层」。
TOP_LEVEL_REASON_PLACEHOLDER = "一句话：它是什么、为什么必须是顶层模块"
#: 拒绝码表那一条理由的占位。
REFUSAL_REASON_PLACEHOLDER = "一句话：为什么这是「执行了、没成功」而不是一次拒绝"
#: `contract_amendments` 那一条理由的占位。
AMENDMENT_REASON_PLACEHOLDER = "一句话：这次契约演进为什么合法（重冻仍单独一次、逐格 diff）"
#: 文档索引「入册」那一格的占位。
DOC_REGISTERED_PLACEHOLDER = "一句话：它是什么、算哪一档（当前规格 / 历史证据）"
#: 文档索引「不入册」那一格的占位。
DOC_UNREGISTERED_PLACEHOLDER = "一句话：为什么不入册（草稿 / 一次性复算输出 / 临时纸）"


# ---------------------------------------------------------------- 一、顶层模块注册表


def top_level_module_line(name: str) -> str:
    """`_AGENTFLOW_TOP_LEVEL_MODULES` 的一整个条目行（可粘贴，缩进 4）。"""
    return f'    "{name}": "{TOP_LEVEL_REASON_PLACEHOLDER}",'


def top_level_missing_line(name: str) -> str:
    """登记了、盘上却没有的模块：该删的是它那一行（给成注释，避免误粘贴）。"""
    return f'    # 删掉这一行（盘上已经没有这个模块）："{name}"'


def top_level_modules_message(problems: Sequence[str], on_disk: Sequence[str],
                              registered: Mapping[str, str]) -> str:
    """顶层模块集合与登记表不一致时的失败信息（含可粘贴的整行）。"""
    extra = [name for name in on_disk if name not in registered]
    missing = [name for name in registered if name not in set(on_disk)]
    lines = ["盘上顶层模块集合与 `_AGENTFLOW_TOP_LEVEL_MODULES` 不一致："]
    lines.extend(f"  - {one}" for one in problems)
    lines.append("")
    lines.append("可粘贴的账骨架（复核后把占位那句话换成真的理由；判据不替你写，也不写盘）：")
    lines.extend(top_level_module_line(name) for name in extra)
    lines.extend(top_level_missing_line(name) for name in missing)
    return "\n".join(lines)


# ---------------------------------------------------------------- 二、拒绝码表


def refusal_line(rel: str, kind: str) -> str:
    """`_FAILURES_NOT_REFUSALS` 的一整个条目行（可粘贴，缩进 4）。"""
    return f'    ("{rel}", "{kind}"): "{REFUSAL_REASON_PLACEHOLDER}",'


def refusal_repeat_line(rel: str, kind: str, count: int) -> str:
    """`_REPEAT_COUNTS` 的一整个条目行（同一 `(文件, kind)` 出现多处时用）。"""
    return f'    ("{rel}", "{kind}"): {count},'


def refusal_missing_message(missing: Mapping[tuple[str, str], int]) -> str:
    """有手写失败站点没登记时的失败信息（含 `(文件, kind)` 与可粘贴的元组行）。"""
    lines = [
        "这些手写的 ok=False 没有登记，也没有走 `agentflow.refusals.refuse`："
        f"{sorted(missing)} ⇒ 它们的拒绝会再次被台账记成 ok",
        "",
        "可粘贴的账骨架（补进 `_FAILURES_NOT_REFUSALS`；理由留了占位）：",
    ]
    for rel, kind in sorted(missing):
        count = missing[(rel, kind)]
        lines.append(f"# 站点：({rel}, {kind!r})，盘上 {count} 处")
        lines.append(refusal_line(rel, kind))
        if count > 1:
            lines.append(f"# 这一档盘上有 {count} 处，处数表再补一行：")
            lines.append(refusal_repeat_line(rel, kind, count))
    return "\n".join(lines)


def refusal_stale_message(stale: Mapping[tuple[str, str], int]) -> str:
    """登记表里有条目已经扫不到时的失败信息（给的是「删哪一行」）。"""
    lines = [
        f"登记表里这些条目已经扫不到了（豁免腐烂，请删）：{sorted(stale)}",
        "",
        "可粘贴的账骨架（删掉对应的行；处数表里同名的也一起删）：",
    ]
    for rel, kind in sorted(stale):
        lines.append(f'    # 删掉这一行：("{rel}", "{kind}")')
        count = stale[(rel, kind)]
        if count > 1:
            lines.append(f'    # 删掉处数登记：("{rel}", "{kind}"): {count},')
    return "\n".join(lines)


# ---------------------------------------------------------------- 三、returns 基线


def contract_amendment_object(tool: str, key: str, edits: Sequence[dict],
                              *, date: str) -> str:
    """一个 `contract_amendments` 数组元素（缩进 4 + 末尾逗号，与基线字节同形）。"""
    payload = {
        "tools": [tool],
        "key": key,
        "reason": AMENDMENT_REASON_PLACEHOLDER,
        "date": date,
        "edits": list(edits),
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return "\n".join("    " + line for line in body.splitlines()) + ","


def contract_amendments_block(entries: Sequence[Mapping[str, object]],
                              *, date: str) -> str:
    """整份可粘贴的 JSON 片段（每个受影响工具一条 amendment，围在 json 代码块里）。"""
    chunks = [contract_amendment_object(str(one["tool"]), str(one["key"]),
                                        list(one["edits"]), date=date)  # type: ignore[arg-type]
              for one in entries]
    return "```json\n" + "\n".join(chunks) + "\n```"


def contract_amendments_message(diffs: Sequence[str],
                                entries: Sequence[Mapping[str, object]],
                                *, date: str) -> str:
    """声明契约有未被记账的差异时的失败信息（含 `value_edits()` 现算的整份片段）。"""
    head = ("工具的声明契约被改动了 —— 这一批只许改 summary；合法的演进要在基线 "
            "`contract_amendments` 里留一条带 reason 的逐项编辑清单：\n  "
            + "\n  ".join(diffs))
    if not entries:
        return head
    tail = ["", "可粘贴的账骨架（插进基线 `contract_amendments` 数组；"
                "`reason` 是占位，重冻仍是单独一次、人逐格看过）：",
            contract_amendments_block(entries, date=date)]
    rest = len(diffs) - len(entries)
    if rest > 0:
        tail.extend(["",
                     f"另有 {rest} 条差异不是「某一格的值变了」（新增 / 删除工具）："
                     "它们不能靠 edits 放行，必须在基线的 `declarations` 里登记。"])
    return "\n".join([head, *tail])


# ---------------------------------------------------------------- 四、文档索引


def docs_index_registered_row(name: str) -> str:
    """`docs/INDEX.md` 入册行（`§1`–`§3` 任一处都认，这里是 §2 的形态）。"""
    return f"| [`{name}`]({name}) | {DOC_REGISTERED_PLACEHOLDER} |"


def docs_index_unregistered_row(name: str) -> str:
    """`docs/INDEX.md` 第 6 节「不入册」行。"""
    return f"| `{name}` | {DOC_UNREGISTERED_PLACEHOLDER} |"


def docs_index_message(names: Sequence[str]) -> str:
    """有文档既没入册、也没进第 6 节时的失败信息（两种落位各给一行）。"""
    ordered = sorted(names)
    head = "；".join(f"{name} 既不在 docs/INDEX.md 里，也没登记进 §6「不入册」"
                    for name in ordered)
    lines = [head, "",
             "两种落位各给一行（二选一；把占位那句话换成真的判断）："]
    for name in ordered:
        lines.extend(["", f"# {name} 落位 A：入册（§1–§3 任一处）",
                      docs_index_registered_row(name),
                      f"# {name} 落位 B：不入册（§6，显式登记 + 理由）",
                      docs_index_unregistered_row(name)])
    return "\n".join(lines)


# ---------------------------------------------------------------- 五、读图


def reading_map_headline(files: int, total: int, big: int, loop_lines: int) -> str:
    """`docs/READING-MAP.md` 开头那一句（三格读数 + `agent_loop.py` 行数，整句可粘贴）。"""
    return (f"> **{files} 个 `.py`、{total:,} 行**，**{big} 个文件超过 800 行**"
            f"（**全仓最大的是 `agent_loop.py`，{loop_lines:,} 行**")


def reading_map_big_table_rows(rows: Sequence[tuple[str, int]]) -> str:
    """读图第 3 节那张大文件表的行（行数是现算值，后两格留占位）。"""
    return "\n".join(f"| `{name}` | {lines} | <边界> | <为什么这么大> |"
                     for name, lines in rows)


def reading_map_counts_message(problems: Sequence[str], files: int, total: int,
                               big: int, loop_lines: int) -> str:
    """开头三格过期时的失败信息（含整句可粘贴的原文）。"""
    return ("`docs/READING-MAP.md` 开头那三格过期了（口径见该文档 `:10` 的复跑命令）：\n  - "
            + "\n  - ".join(problems)
            + "\n\n可粘贴的账骨架（整句替换回去）：\n"
            + reading_map_headline(files, total, big, loop_lines))


def reading_map_largest_message(got: int, files: int, total: int, big: int,
                                loop_lines: int) -> str:
    """`agent_loop.py` 行数过期时的失败信息（含整句可粘贴的原文）。"""
    return (f"`agent_loop.py` 的行数：文档 {got:,} vs 现算 {loop_lines:,}\n\n"
            "可粘贴的账骨架（整句替换回去，三格读数一并核）：\n"
            + reading_map_headline(files, total, big, loop_lines))


def reading_map_rows_message(stale: Sequence[str],
                             rows: Sequence[tuple[str, int]]) -> str:
    """读图第 3 节行数过期时的失败信息（含可粘贴的表行）。"""
    return ("读图 §3 的行数过期了（改数字，别改判据）：" + "；".join(stale)
            + "\n\n可粘贴的账骨架（把现算值换进那一行；后两格照原文补）：\n"
            + reading_map_big_table_rows(rows))

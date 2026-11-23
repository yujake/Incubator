# -*- coding: utf-8 -*-
"""工具面的三段（能力 / 场景 / 案例）—— 「唯一一处渲染口径」。

业主 2026-11-22 指令（逐字）：「角色不需要知道工具的具体实现，只需要知道工具能干什么
以及怎么用工具，具体实现的描述仅可保留在代码注释」。落到工具面上就是三段：

    ① 能力（`summary`）   这个工具做什么、产出什么、边界在哪；
    ② 场景（`scenario`）  什么时候该用它（而不是别的哪一件）；
    ③ 案例（`example` + `example_code`） 一条真实调用 + 它会回什么。

三段「都不许」出现实现细节：内部模块名 / 私有函数名 / 算法名 / 内部存储布局
（哪张表、哪个中间文件、"它其实调了 X"）。那些只留在 handler 的代码注释里。

## 为什么单列一个模块，而不是住在 `tools/base.py`

三处读者分属三层：`tools/base.py`（声明与装配）、`agent_prompts.tools_lines`（提示词）、
`llmseam.build_tool_face`（function-calling 的 description）。前者的包 `__init__`
装的是全部工具模块，谁 import 它都会把整棵工具树拖进来 —— 提示词那一层因此不能
直接 import 它。这个模块只依赖标准库，三层都能安全 import，于是「同一份渲染」
才真的是同一份（两处各拼一套 = 模型读到的两句话迟早分家，而只有一处有判据看着）。

## 字数口径

字符数，去掉首尾空白算（含标点）。`example_code` 的代码块「不计入」、且逐字不许压缩
（改一个键名，模型抄下去就是一次 `unknown_param`）：

    ① < 100 · ② < 50 · ③ < 100（含返回描述，不含代码）

压缩批次的 `cohort ≤ 0.75` 只量 ①（`summary`）—— 那条判据的口径一个字没动。
"""
from __future__ import annotations

from typing import Any

#: 三段各自的上限（字符数）。改这里等于改格式本身 —— 判据与提示词都读它。
FACE_SUMMARY_MAX = 100
FACE_SCENARIO_MAX = 50
FACE_EXAMPLE_MAX = 100

#: 三段的固定标签（解析面与断言面共用这一份）。第一段（能力）在渲染时「不带标签」：
#: 它是行首那一句，前面已经有「- 工具名：」，再加「能力：」是重复；也正因为这一点，
#: "只填了能力、还没填场景与例"的迁移期渲染与今天「逐字节相同」（提示词摘要不漂）。
FACE_LABELS: tuple[tuple[str, str], ...] = (
    ("summary", "能力"),
    ("scenario", "场景"),
    ("example", "例"),
    ("example_code", "代码"),
)

#: 段与段之间的分隔符：提示词那一侧与 function-calling 那一侧必须是同一串字节。
FACE_SEP = "；"

#: 段文本「自带的标签」：`example` 若以「例：」/「例如：」/「示例：」开头，渲染时先剥掉。
#:
#: 为什么要有这一张表（2026-11-22 片7 实测）：三段格式迁移时，各片是照着同一份模板抄的，
#: 其中几片（`fs.*` / `verify.*` / `attack.*` / `formal.*`，实测 26 件）把「例：」也抄进了
#: `example` 文本；`face_text` 渲染时又加一次标签 ⇒ 模型面上出现「例：例：…」。
#: 修法是两处一起：源头那 26 件的前缀清掉（本批），同时这里做防御性剥离 ——
#: 以后新增一件若又把标签写进文本，模型面上也不会出现两个「例：」。
FACE_OWN_PREFIXES: dict[str, tuple[str, ...]] = {
    "场景": ("场景：", "场景:"),
    "例": ("例：", "例:", "例如：", "例如:", "示例：", "示例:", "举例：", "举例:"),
    "代码": ("代码：", "代码:"),
}


def strip_face_label(label: str, text: str) -> str:
    """剥掉段文本自带的那个标签（只删前缀字符，正文一个字不动）。

    反复剥到不再变：源头上真出现「例：例：x」时，一次剥离只会剩一个 —— 渲染面仍会看见
    两个标签。既然这里的语义是「这一段只有一个标签」，那就剥干净（每轮都变短，必然停机）。
    """
    prefixes = FACE_OWN_PREFIXES.get(label, (f"{label}：", f"{label}:"))
    out = str(text or "").lstrip()
    while True:
        for prefix in prefixes:
            if out.startswith(prefix):
                out = out[len(prefix):].lstrip()
                break
        else:
            return out


def face_units(text: str) -> int:
    """字数口径：去掉首尾空白后的字符数（含标点；不计代码块 —— 调用方不传它）。"""
    return len(str(text or "").strip())


def face_segments(spec: Any) -> list[tuple[str, str, int]]:
    """这件工具「有内容的那几段」：`[(键, 标签, 字数)]`；空段不渲染。"""
    out: list[tuple[str, str, int]] = []
    for key, label in FACE_LABELS:
        text = str(getattr(spec, key, "") or "").strip()
        if text:
            out.append((key, label, face_units(text)))
    return out


def face_text(spec: Any) -> str:
    """三段 → 一段模型可读的文本。

    `agent_prompts.tools_lines`、`llmseam.build_tool_face` 的 description、
    `ToolRegistry.text_catalog` 三处都调它。

    第一段（能力）裸写，其余段带标签（`场景：` / `例：` / `代码：`）：
    行首已经有「- 工具名：」，再写「能力：」既是重复，也会让"只填了能力"的迁移期
    渲染无谓地漂掉整张提示词（那一漂没有任何语义变化，却要重冻十一格摘要）。

    段文本「自带的同名标签」在这里剥掉（:func:`strip_face_label`）：标签只由本函数加，
    文本里那一份是重复的 —— 剥在唯一这一处，比在 126 件 `example=` 上各改一遍更靠得住
    （新加的工具也自动受它保护）。
    """
    out: list[str] = []
    for index, (key, label) in enumerate(FACE_LABELS):
        text = str(getattr(spec, key, "") or "").strip()
        if not text:
            continue
        out.append(text if index == 0 else f"{label}：{strip_face_label(label, text)}")
    if not out:
        return str(getattr(spec, "summary", "") or "")
    return FACE_SEP.join(out)


def face_budget_problems(spec: Any) -> list[str]:
    """三段是否齐、是否超字数：返回逐条描述（空列表 = 合格）。

    这是「判据」用的函数，不是装配期的门 —— 格式迁移期不可能 126 件同时齐，
    而装配期一炸整张注册表都装不起来（那会把「还没写完」变成「产品坏了」）。
    """
    problems: list[str] = []
    limits = {"summary": FACE_SUMMARY_MAX, "scenario": FACE_SCENARIO_MAX,
              "example": FACE_EXAMPLE_MAX}
    labels = dict(FACE_LABELS)
    name = str(getattr(spec, "name", "?"))
    for key, limit in limits.items():
        text = str(getattr(spec, key, "") or "").strip()
        if not text:
            problems.append(f"{name}：缺「{labels[key]}」这一段（{key}）")
            continue
        if face_units(text) > limit:
            problems.append(f"{name}：「{labels[key]}」{face_units(text)} 字 > 上限 {limit}")
    if not str(getattr(spec, "example_code", "") or "").strip():
        problems.append(f"{name}：缺「代码」这一格（example_code）")
    return problems

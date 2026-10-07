#!/usr/bin/env python
"""受控词表普查（`G-26` 第一步）：一个取值被定义了、却没有任何地方产出它。

## 这一版只做一半，而且把另一半写出来

本工具只查"死取值"：词表里登记了、而 `src/` 里找不到产出点的取值。
另一个方向 "漏词表"（代码产出了不在任何词表里的字面量）没有实现 ——
它逐字写在输出的"已知缺口"一节里，不靠读者猜。为什么先做这一半：

- "死取值"是可判定的：值在不在文本里出现，是个能机械化的事实；
- "漏词表"需要一个"哪些字面量算产出"的口径，而那个口径正是 `P-22`/`P-23`
  要人裁决的东西（补产出 / 删词表 / 登记为预留）。替人定口径再把它包成红灯，
  等于用门逼出一个未经裁决的改法。

## 为什么有下限断言（反真空，`P16`）

若扫描器读不到词表、或读不到任何产出点，它会把一切都报成"没有死取值" ——
那是假绿。所以这里对"扫到几个词表""扫到几个产出点"各设下限，不满足就报
`unknown`(2)：没查成不是没问题。

## `P-23` 点名但普查看不见的四条（前三条进登记表，会打印在"栏一附"）

`P-23` 的清单里有几条结构上落不进 `dead` 这一栏。它们的登记照样打印
（输出里的"栏一附：已登记为预留、但今天普查看不见它是死取值"），
而不是被悄悄吞掉 —— 登记表里有一条而输出里查无此条，比不登记更糟：

- `DOC_KINDS:survey` —— `survey` 这个字面量在 `providers.py` 里是主题类别
  （provider 返回的 type 描述词那一列），不是文档种类：同形不同义。
- `DEP_KINDS:lemma` —— 普查报它"有产出"，而那个产出是 `formalgw._DECL_KEYWORDS` 里的
  Lean 关键字 `"lemma"`：同名词、不同义。普查用正则找"带引号的字面量"，
  它分辨不了"这个词出现了"与"这个取值被产出了"。
- `DEP_KINDS:dataset` —— 同理：命中的是 `providers.py` 的文献类型码 `"dataset": "Z"`
  与 `agent_g.py` 测试夹具里的一个 kind，都不是 `DEP_KINDS` 的生产点。
- `capabilities:UNKNOWN_SIDE_EFFECT` —— 它不是任何词表里的取值，而是
  `capabilities.py` 里的一个模块级常量（`UNKNOWN_SIDE_EFFECT = "unknown"`）。
  本工具的判据是"以 `VOCAB_SUFFIXES` 结尾的字符串元组"，单个常量不在扫描范围内，
  所以它连"同形不同义"都算不上。它的语义（三态纪律的"未知"档、且被 `_WRITE_LIKE`
  当写者处理）不是词表遗漏，是刻意设计。见 `capabilities.py:70-76`。
  这一条只在本节写明，不进登记表（登记一个不存在于任何词表里的键没有意义）。

⇒ 前三条是已知漏检的一种形态（"字面量出现了，但不是那个意思"），
与 `R010` 的 `ocr.backends` 那条同族。它们在这里逐条写明，不靠读者猜。

## 退出码

`0` = 查过了、没有死取值；`1` = 查过了、有死取值；`2` = 没查成（读不到源码树 / 词表数或产出点数低于下限）。
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import time
from pathlib import Path

#: 词表命名的判据：模块里以这些后缀结尾、且值是"字符串元组"的常量。
#: 刻意不写死"有哪几个词表"（那样新增词表会静默落在普查之外，而数字照样好看）：
#: 取到几个就报几个，并把名单打进输出（`G-32`：数字要能追溯到对象）。
#:
#: `_FORMS` 是 `R-30` 补上的（`draft/28` §136.6）：`CONJECTURE_FORMS` 此前整个落在
#: 普查之外，"猜想的形状"这一轴的死取值没有任何判据管它。补它之前先量过一次：
#: 全仓以 `_FORMS` 结尾的常量**只有它一个**（`schema.py:437`）⇒ 不会顺手牵出别的语义面。
VOCAB_SUFFIXES: tuple[str, ...] = ("_KINDS", "_STATUSES", "_OUTCOMES", "_SCOPES", "_FORMS")

#: 词表**定义点**所在的文件（相对 `<root>/src`）。`R-37` 把它从"只有 `schema.py`"
#: 扩成"判据层的这几个"：
#:
#: 为什么此前只有 `schema.py`：它的值域（表结构、字段词表）确实都在那里。
#: 为什么不够：判据层自己也会定义受控词表 —— `claimanatomy.py` 有 5 张
#: （`CLAIM_KINDS` / `CLAIM_STATUSES` / `ALLOWED_USE_KINDS` / `CLAIM_SOURCE_KINDS` /
#: `CLAIM_CHECK_KINDS`），它们此前**完全不在 R011 的判据面内**（实测 2026-09-29：普查报
#: "词表 21 个"而名单里没有这 5 张）。
#:
#: 一处**已知余量**（如实登记，不假装扫全了）：`src/` 里仍有 15 个受控词表常量落在这份
#: 名单之外（例如 `fetch.ERROR_KINDS`、`evidence.ACQUIRE_STATUSES`、`verify.CITATION_KINDS`）。
#: 它们是"还没被纳入的判据面"，不是"没问题" —— 名单是显式的，扩它要单独一次口径变更
#: （每纳入一张表都可能带出新的死取值 ⇒ 会改 lint 读数）。观测命令与当次读数见
#: `draft/28` §168。
VOCAB_DEFINITION_FILES: tuple[str, ...] = ("agentflow/schema.py", "agentflow/claimanatomy.py")

#: 反真空下限：这两个数字不是判据，只是"扫描器确实读到东西了"的最低证据；低于它一律判没查成。
#: 真实仓库的当次规模不写死（`G-32`）：由 `python tools/vocab_census.py` 的汇总行当次读
#: —— 观测 2026-09-27 14:56:51 ⇒ 词表 20 个（产出点五万行量级，同一条汇总行当次给）。
MIN_VOCABS = 3
MIN_PRODUCER_LINES = 50

#: 已登记为"预留"的取值：`{(词表名, 取值): 理由}`。
#:
#: ## 为什么这张表存在
#:
#: `P-23` 要求审计输出分两栏（"已登记为预留" / "无人认领"）并且不许合并 ——
#: 合并等于静默豁免：一个"没人认领的死取值"与一个"写明为什么留着"的取值会被读成同一件事。
#:
#: 往这张表里加一条是人的动作：它的语义是"我知道这个取值现在没有产出点，我决定留着，
#: 理由是这个"。所以本工具只提供位置（登记表 + 两栏输出），不替谁填 ——
#: 与"只出 info 不做成红灯"是同一条纪律：不替人做口径裁定。
#:
#: ## `P-22` / `P-23` 的裁定（选项 c：登记为预留）
#:
#: 登记表只能有一处，就是这里。 不许在 `schema.py` 里另写一份"预留"标记：
#: 同一件事两个落点必然漂移，而漂移的表现是"审计说预留、schema 说没有"（FC-03）。
#:
#: 为什么选 c 而不是另外两条路（原裁定理由照抄，`P-23` 自己推荐 c）：
#:
#: - 最便宜且不撒谎。删词表值（选项 b）要动 `schema.py` 且带"追溯性"争议；
#:   补产出（选项 a）对 `quote_mismatch` 不是接线而是新能力 ——
#:   实测：`quoteverify.check_quote` 的 `reason` 取值只有 `no_text_layer` / `empty_quote` /
#:   `substring_match` / `substring_match_outside_declared_range` / `substring_match_fulltext` /
#:   `not_found` / `not_found_page_unknown` / `empty_page_range`（末一档是 `R-08` = B1 候选 C
#:   加的：声明的窗口是空的 ⇒ 判"没法判"，不许折成 `not_found`）—— 根本没有
#:   "找到了但不一样"这一档。
#:   所以 (a) 会正好撞上 `P-22` 自己的负控（"只写了名字、没有 code 能算出它 ⇒
#:   审计必须仍然报死取值"）。
#:
#: ## 登记：`closing` 验收读数的**行级码**（`draft/52` CC-02 裁定 (a)）
#:
#: 它们不是词表常量，而是 `closing._check_acceptance` 里 `Finding("acceptance", <code>, …)`
#: 的取值 —— 列在这里，是因为 CC-02 把"一行读不懂"从"整表 unknown"改成**行级**记账，
#: 新增了两个码（旧的那些一个字没改，历史读数照旧能对）：
#:
#: - `acceptance_row_unreadable` —— 这一行形状/字段类型读不懂（非对象 / `na` 非布尔 /
#:   `min`·`max` 非整数 / `id` 缺失或重复）；
#: - `acceptance_rows_unreadable` —— 汇总读数（有几行读不懂 ⇒ 整格 `unknown`）。
#:
#: 与它们同族的旧码（**未改**）：`acceptance_unreadable`（结构级：顶层不是 JSON/数组）、
#: `acceptance_leg_unreadable`（台账读不到）、`acceptance_unknown_kind`、
#: `acceptance_na_without_reason`、`acceptance_chain_unreadable`、`acceptance_all_na`。
#: 这些码共用一个纪律：**`unknown` 不许读成 `pass`**（见 `closing.acceptance_row_state`）。
#:
#: ## 一处推翻：`FINDING_KINDS.quote_mismatch` 改走 (b)（`E-10` 裁定，2026-09-27）
#:
#: 上面那条"最便宜且不撒谎"的取舍对其余取值仍然成立，但
#: `FINDING_KINDS.quote_mismatch` 这一条被单独重裁为 (b) 删词表值：
#: 它描述的是一个做不到的承诺（词表说会报"引文不符"，实现只给 `not_found`），
#: 而"登记为预留"对一条假承诺不是最便宜的处置 —— 假承诺留在词表里，
#: 读者照样会以为系统会报"引文不符"。所以那个取值已从
#: `schema.FINDING_KINDS` 删除，本登记表里的那一条同时删除
#: （登记一个不存在的取值就是"登记已过期"，会被 `R011` 打进栏一附）。
#: 想恢复这个能力，请作为新条目提出（附阈值标定方案）—— 不许把值加回来。
#:
#: `reserved` 不是"通过"。它必须照样打印（含理由），因为它回答的是
#: "这个取值为什么还留着" —— 静默豁免是本项目最忌的形态（`G-13`/`N-5` 同族）。
#:
#: 本表的键不要求出现在 `dead` 里 —— 有些被点名的取值"同形不同义"，
#: 普查看得见字面量却看不见那是死取值。这类条目会打印在栏一附里，
#: 于是它们既不会静默消失，也不会伪装成"已确认无产出"。
#: `UNKNOWN_SIDE_EFFECT` 是唯一不进本表的被点名项：它不是任何词表里的取值，
#: 而是 `capabilities.py` 的一个模块级常量（见模块 docstring 那一节）。
RESERVED_VALUES: dict[tuple[str, str], str] = {
    # 这里曾经有一条 `("FINDING_KINDS", "quote_mismatch")` 的登记。
    # `E-10` 裁定 (b)（2026-09-27）把那个取值从 `schema.FINDING_KINDS` 删掉了
    # （理由见上面"一处推翻"那一节：它对一条做不到的承诺做预留），
    # 于是这条登记同时消失 —— 登记一个不存在的取值就是"登记已过期"。
    ("DOC_KINDS", "reproduction_report"): (
        "死取值。agent_g 只写 note/paper 一类的稿件，没有任何地方建 kind="
        "'reproduction_report' 的文档行。留着的理由：它对应 E→G 的『独立复现报告』这条交付物，"
        "是设计里明确存在、只是尚未接线的一类产物；删掉它会让『复现报告』在词表里无处安放。"
    ),
    # `FINAL-R7-08` 更正：这里原本还有一份 `("DOC_KINDS", "survey")`，与下面那条同名重复，
    # 字典字面量里后一条静默覆盖前一条 —— 于是这 7 行是死文本，而读登记表的人会以为
    # survey 有两条独立理由。重复的那一份已删，留下的是下面那条（它多写了一句
    # "普查看不见它是死取值"）。
    ("DEP_KINDS", "proposition"): (
        "死取值。agent_g.register_dependency 的 kind 取值里没有 proposition。留着的理由："
        "数学文献里『命题』是与 theorem/lemma 并列的标准依赖种类，删掉会让一条依赖无法如实登记。"
    ),
    ("DEP_KINDS", "prior_art"): (
        "死取值。留着的理由：FC-23 的『先行工作』是必须能与 theorem/experiment 分开的一类依赖 ——"
        "『我引了一篇同类工作』与『我用了一条定理』的证据力完全不同，合并会让依赖计数虚高。"
    ),
    # ---- 下面三条是"同形不同义"：普查看不见它们是死取值，所以它们会打印在栏一附里。
    # 之所以仍然登记（而不是只写在 docstring 里）：登记表是机器可读的那一份，
    # 写在这里才会被打印出来、才会在"这条其实已经接线了"时被人看见。
    ("DOC_KINDS", "survey"): (
        "普查看不见它是死取值：`survey` 这个字面量在 `providers.py` 里是主题类别"
        "（provider 返回的 type 描述词那一列：'survey'/'review'/'introduction'/'textbook'/"
        "'overview'），不是文档种类。同形不同义 ⇒ 正则命中它、而 `DOC_KINDS` 却拿不到产出。"
        "留着的理由：综述是 G 的一类正式交付物，将来 agent_g 会写它；删掉它等于说"
        "『本框架不产出综述』—— 那不是我们的事实。"
    ),
    ("DEP_KINDS", "lemma"): (
        "普查看不见它是死取值：它报的『有产出』来自 `formalgw._DECL_KEYWORDS` 里的 "
        "Lean 关键字 `\"lemma\"`。同名词、不同义 —— 那是『源码里能声明 lemma』，"
        "不是『有一条 kind='lemma' 的依赖被登记』。留着的理由：lemma 是与 theorem 并列的"
        "标准依赖种类，删掉会让一条引理级的依赖无处安放。"
    ),
    ("DEP_KINDS", "dataset"): (
        "普查看不见它是死取值：命中的是 `providers.py` 的文献类型码 `\"dataset\": \"Z\"` "
        "与 `agent_g.py` 里一个测试夹具的 kind。两者都不是 `DEP_KINDS` 的生产点。"
        "留着的理由：引用了外部数据集是一条真实且必须能与 theorem 分开的依赖"
        "（`external_unavailable` 那一档就是为它这类准备的）。"
    ),
    # ---- `T1`（2026-09-29，依据 `draft/30` §T1）加 `conjectures` 表时新声明的状态机：
    # `CONJECTURE_STATUSES` 的 9 个取值里有 5 个今天在 `src/` 里没有产出点。
    # 它们**不是**遗忘，是那份条目逐字写着的"不做"：T1 只加**数据面**（表 / 词表 /
    # 跨对象不变量），提出、检验、否证、升格这些**语义动作**在 T3 的条目里才接线；
    # 于是今天这 5 个值只能由 `table.*` 直接写入，没有任何 agent 代码写它们。
    # 处置按本表 doctrine 的选项 (c) 登记为预留：删值要动 `schema.py` 且会让
    # `draft/29` §7.5 的状态机残缺；补产出属于 T3 的条目，不属于 T1。
    # ⚠️ **这 5 条是 AI 代写的登记**（窗口见 `docs/NOAI-SUSPENSION-2026-09-28.md`）。
    # 本表 docstring 写明"往这张表里加一条是人的动作"，而"留还是删"正是口径裁定 ⇒
    # 这条注记必须留着，供 2 名 reviewer 走查时推翻。
    ("CONJECTURE_STATUSES", "proposed"): (
        "死取值。留着的理由：它是 `Conjecture.status` 的**默认值**（每一行猜想生下来就是它），"
        "但普查不把『dataclass 默认值』算作产出点 ⇒ 这一条同时是普查的已知缺口"
        "（见 `draft/28` §136 的 R-30）。写它的语义动作（D 提出猜想）在 T3 接线。"
        "**`draft/28` §168 起**：普查已把类体默认值算作产出点（R-31 的修法）⇒ 本条从"
        "『死取值』挪进栏一附（登记了、而普查不见其为死取值），理由的前半句"
        "（『不把默认值算产出点』）已过期，留着是为了不改写历史登记。"
    ),
    ("CONJECTURE_STATUSES", "testing"): (
        "死取值。留着的理由：`draft/29` §7.5 状态机里『正在检验』这一档；"
        "写入它的动作（把猜想挂到实验上）属于 T3。删掉它会让『检验中』无处安放。"
    ),
    ("CONJECTURE_STATUSES", "refuted"): (
        "死取值。留着的理由：『被反例否证』是猜想闭环的终点之一，"
        "`Conjecture.validate` 已经强制它必须带 `counterexample_experiment_id`"
        "（『检验过没有结论』不得转成『被否证』）；写入它的动作在 T3。"
    ),
    ("CONJECTURE_STATUSES", "known_in_literature"): (
        "死取值。留着的理由：『别人已经证过』与『我们证过』是两件事（同本表 `DOC_KINDS` 一族"
        "的取舍），它要求非空 `known_lit_id`；写入它的动作在 T3。"
    ),
    ("CONJECTURE_STATUSES", "withdrawn"): (
        "死取值。留着的理由：『撤下必须写理由、不许静默消失』是 `Conjecture.validate` 的硬条件，"
        "而『撤下』这个动作在 T3 才接线。"
    ),
    # ---- `draft/28` §168（`R-30` + `R-37` 的取词表面拓宽）新看见的 17 条里，
    # **由数据产出**的那 7 条。它们不是"没有产出点"，而是"产出点不在代码里"：
    # 普查的判据是"这个字面量在 `src/` 里出现过吗"，而这几张词表的值是由**文档/数据**
    # 写进去的（谁写见每条的理由）。⇒ 判据对它们不适用，登记在这里（栏一），
    # 附上 2026-09-29 在 `projects/p2-review` 实测到的行数当证据。
    #
    # ⚠️ **这 7 条是 AI 代写的登记**（窗口见 `docs/NOAI-SUSPENSION-2026-09-28.md`；
    # 本表 docstring 写明"往这张表里加一条是人的动作"）⇒ 留还是删由 2 名 reviewer 走查裁定。
    # 另外 10 条**故意没有登记**（它们是"代码与数据都不产出"的真缺口，三条出路
    # ——接线/登记为预留/删值——都是口径裁定，AI 不替人做）⇒ 它们留在栏二，
    # 于是 `R011` 以 error 报出来，逐条见 `draft/28` §168 的 R-64。
    ("CLAIM_KINDS", "定理"): (
        "由数据产出（不是代码字面量）：`documents.claims[].kind`，"
        "`projects/p2-review` 实测 7 行（2026-09-29）。普查的字面量判据看不见它。"
    ),
    ("CLAIM_KINDS", "命题"): (
        "由数据产出：`documents.claims[].kind`，实测 8 行（2026-09-29）。"
    ),
    ("CLAIM_KINDS", "引理"): (
        "由数据产出：`documents.claims[].kind`，实测 9 行（2026-09-29）。"
    ),
    ("CLAIM_SOURCE_KINDS", "文献"): (
        "由数据产出：`documents.claims[].source_kind`，实测 16 行（2026-09-29）。"
        "『这条断言是从文献里读来的』只能由写稿件的一方给出，代码侧没有产出点。"
    ),
    ("CLAIM_SOURCE_KINDS", "自证"): (
        "由数据产出：`documents.claims[].source_kind`，实测 8 行（2026-09-29）。同 `文献`。"
    ),
    ("CLAIM_CHECK_KINDS", "只读了陈述"): (
        "由数据产出：`documents.claims[].our_check`，实测 4 行（2026-09-29）。"
        "它是 P3 台账里那三条 `lem:*` 的 `our_check` 取值（`draft/28` 的 R-40 说的就是这一档）。"
    ),
    ("CONJECTURE_FORMS", "identity"): (
        "由数据产出：`conjectures.form`，实测 8 行（2026-09-29）。"
        "`form` 由提出猜想的一方写（D/人），代码里只有 `universal` 出现过字面量。"
    ),
    # ---- 下面 10 条是 `R-64`（`draft/28` §168 咬出、§173 处置）：
    # 拓宽取词表面之后**第一次看得见**、且"代码与数据都不产出"的取值。
    # 三条出路里选的是**登记为预留**（`P-23` 的选项 c）：它们是各自分类法里的合法成员，
    # 只是本工作区（`projects/p2-review`）没用到；删值会让"这一类断言/形状"无处安放。
    # ⚠️ **这 10 条同样是 AI 代写的登记**（窗口见 `docs/NOAI-SUSPENSION-2026-09-28.md`）⇒
    # 逐条走查时请判"留还是删"；若判"删"，要动的是 `schema.py`/`claimanatomy.py` 的词表值。
    ("CLAIM_KINDS", "定义"): (
        "死取值（无产出且无人认领 ⇒ 本批登记为预留）。它是数学稿件里与定理/引理并列的标准断言种类；"
        "本包实测 `documents.claims[].kind` 只出现 命题/引理/定理 ⇒ 这一档没有被用到。"
        "写它的是**写这类断言的稿件**（G 或人），不是代码字面量。"
    ),
    ("CLAIM_KINDS", "推论"): (
        "死取值 ⇒ 预留。同 `CLAIM_KINDS.定义`：分类法成员，本包未用到。"
    ),
    ("CLAIM_KINDS", "例"): (
        "死取值 ⇒ 预留。同 `CLAIM_KINDS.定义`：分类法成员，本包未用到。"
    ),
    ("CLAIM_KINDS", "注"): (
        "死取值 ⇒ 预留。同 `CLAIM_KINDS.定义`：分类法成员，本包未用到。"
    ),
    ("CLAIM_STATUSES", "待精化"): (
        "死取值 ⇒ 预留：`claimanatomy` 的降级规则里有『还没写清』这一档，"
        "而 `documents.claims[].status` 在本包 24 行里一次都没出现过。"
    ),
    ("ALLOWED_USE_KINDS", "Remark only"): (
        "死取值 ⇒ 预留：降级档之一（把一条断言降到'只作备注'）；"
        "本包的 `claims[].allowed_use` 没有行用过它。"
        "⚠️ 顺带记一条：这张词表里三条取值**语言不统一**（`主结果` / `Remark only` / `移入 open`）——"
        "统一命名是一次独立的清理，不在本批。"
    ),
    ("CLAIM_SOURCE_KINDS", "未决"): (
        "死取值 ⇒ 预留：来源未定档；本包 24 行的 `source_kind` 只出现 文献/自证。"
    ),
    ("CONJECTURE_FORMS", "existential"): (
        "死取值 ⇒ 预留：猜想形状轴上的三档之一（T1 声明的那张词表）；"
        "数据里只出现 `universal`/`identity`（`conjectures.form`，实测 24 行）。"
        "**若要收窄词表**（只留实际用过的两档），那是另一次 `schema.py` 变更 ⇒ 需人裁，"
        "本批不替人做这个减法。"
    ),
    ("CONJECTURE_FORMS", "bound"): (
        "死取值 ⇒ 预留：同 `CONJECTURE_FORMS.existential`。"
    ),
    ("CONJECTURE_FORMS", "structural"): (
        "死取值 ⇒ 预留：同 `CONJECTURE_FORMS.existential`。"
    ),
    # ---- `draft/37` §16 P1（2026-10-02）加 `statements` 表时新声明的两套词表。
    #
    # ⚠️ **这两条是 AI 代写的登记**（窗口见 `docs/NOAI-SUSPENSION-2026-09-28.md`；
    # 本表 docstring 写明"往这张表里加一条是人的动作"）⇒ 留还是删由 2 名 reviewer 走查裁定。
    #
    # 为什么只有 `superseded` 需要登记（而 `active`/`disputed`/`refuted`/
    # `external_lit`/`own_result` 不需要）：普查的判据是"这个字面量在 `src/` 里
    # （除定义文件外）出现过吗"，而 `verify.py` 的新不变量里写着
    # `s.get("status") == "active"` / `== "external_lit"` 这样的**比较**字面量
    # ⇒ 它们被判成"有产出"。这是本规则判据的一个已知弱点，比"同形不同义"更宽：
    # **一次比较也被算作一次产出**。`superseded` 之所以暴露出来，只是因为
    # 今天没有任何一处写它的字面量（连比较都没有）—— 它是最诚实的那一条。
    # 这三档（`active`/`disputed`/`refuted`）真正的产出点在 `draft/37` §16 P2 的
    # 提示词（B 消化入库、D 审阅改状态），届时它们会由**数据**产生。
    ("STATEMENT_STATUSES", "superseded"): (
        "死取值 ⇒ 预留。`draft/37` §16 P1 声明的四档状态之一（被后来的一条取代）。"
        "留着的理由：『我们把它重写成了更强的形式』是命题台账必须能表达的一件事；"
        "删掉它，一条被取代的命题就只能留在 `active` 里继续被引用 —— 那正是"
        "`STATEMENT_UNUSABLE_STATUSES` 要防的形态。写它的动作在 P2/P3（D 审阅 + 收工）。"
    ),
    ("STATEMENT_UNUSABLE_STATUSES", "superseded"): (
        "死取值 ⇒ 预留。它是 `STATEMENT_STATUSES` 里『不许再当依据用』的那三档之一"
        "（`verify` 的 `proof_stmt_on_unusable_stmt` 读的就是这张表）。"
        "之所以另立一张小词表而不是在 `verify` 里内联一个元组：那张表是**策略**"
        "（哪些状态会撤销一条命题的依据力），与状态机本身是两个轴；"
        "内联会让『同一判据两个落位』（`ATTACK_TERMINAL_STATUSES` 是同族的先例）。"
    ),
    # ---- `draft/37` §16 P2（2026-10-02）加 `literature.matched` 时新声明的词表。
    #
    # ⚠️ **这一条也是 AI 代写的登记** ⇒ 留还是删由 2 名 reviewer 走查裁定。
    #
    # 它为什么是"死取值"、以及另外两个取值为什么不是（这条正好把本规则判据的弱点
    # 展示得最清楚）：
    #   · `mismatch` / `partial` 在 `verify.py` 里有它们的**比较**字面量
    #     （`== "mismatch"` / `== "partial"`）⇒ 普查判为"有产出"；
    #   · `exact` 在任何非定义文件里**一次都没出现过** ⇒ 报死取值。
    #   三者的**真实**产出点其实是同一个：模型按提示词（`ROLE_BRIEFS["A"]`）往
    #   文献行里写。也就是说"比较字面量算不算产出"这条判据在这里给出了三个不一致的结论
    #   —— 登记它是为了不让"exact 没人写"这件事静默消失。
    ("LIT_MATCH_STATUSES", "exact"): (
        "死取值 ⇒ 预留。`draft/37` §2 R1b 的命中校验第一态（检索回来的就是派活点名的那一篇）。"
        "留着的理由：它是这一栏**最常见**的取值（核过、对得上），删掉它等于让"
        "『我核过了、是对的』无处安放 —— 而『没核』（空串）与『核过、对』必须是两个状态"
        "（三态纪律：没查不许折成查过了没问题）。写它的动作在 P2 的提示词里"
        "（A 登记文献行时写 `matched`），代码侧没有字面量产出点。"
    ),
    #
    # ---- 顺带记一条**本规则覆盖面的已知缺口**（不是本次改动引入的，是这次才被撞见）：
    #
    # `VOCAB_SUFFIXES` 只认 `_KINDS / _STATUSES / _OUTCOMES / _SCOPES / _FORMS` 五个后缀
    # ⇒ 名字不以它们结尾的词表**整个不进扫描面**，于是它的取值是死是活**没有任何读数**。
    # 本仓今天就至少还有这些在扫描面之外（`grep '^[A-Z_]\+ = (' src/agentflow/schema.py` 对照）：
    #   `SEARCH_MODES` · `PRIORITIES` · `LIT_TYPES` · `RELATION_STATUS` ·
    #   `EXPERIMENT_RESULTS` · `STATEMENT_ORIGINS`。
    # 本次撞见它是因为那张词表的名字本来以 STATES 结尾（不在五个后缀里）
    # ⇒ 普查对它一声不响（栏二 0），改名成 `LIT_MATCH_STATUSES` 之后 `exact` 立刻现形。
    # **修法有两条**（都要动本文件或 `schema.py` 的常量名 ⇒ 属口径裁定，留给人）：
    # ① 把 STATES / TYPES / MODES / RESULTS / ORIGINS 这几个后缀补进 `VOCAB_SUFFIXES`；
    # ② 或者把那些常量改名成已认的后缀。在两者之间选一个是人的动作，本批只登记现象。
}


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码（GBK 下打印中文/符号会抛 UnicodeEncodeError）。

    内联的理由与其它门脚本同：门必须在本包 import 不了时也能跑。规范实现见
    `src/agentflow/console.py::pin_utf8`。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 可以忽略：被重定向或被替换过的流可能没有 reconfigure，不该让门崩掉。
            pass


def _vocab_constants(schema_py: Path) -> dict[str, list[str]]:
    """从**一个**文件的 AST 里取词表：`名字以 VOCAB_SUFFIXES 结尾` 且值是字符串序列。

    保留这个单文件形态：`tests/test_vocab_census.py` 直接调它去核某一个文件的词表
    （`E-10` 裁定 (b) 那一条），而且"一个文件里有哪些词表"本身是有用的读数。
    多文件版本是 :func:`_vocab_constants_in`（`R-37`）。
    """
    out, err = _vocab_constants_in([schema_py])
    if err:
        raise ValueError(err)
    return out


def _vocab_constants_in(paths: list[Path]) -> tuple[dict[str, list[str]], str]:
    """从若干个定义文件里取全部词表；返回 `(词表字典, 问题)`。

    同名常量在两个文件里都定义 ⇒ 记进 `问题`（两份定义点就是两份"唯一真源"，
    谁读谁错；报出来而不是后者覆盖前者）。
    """
    out: dict[str, list[str]] = {}
    where: dict[str, str] = {}
    for p in paths:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            return {}, f"{p} 读不了或解析失败：{type(exc).__name__}: {exc}"
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None:
                continue
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if not names or not any(n.endswith(VOCAB_SUFFIXES) for n in names):
                continue
            if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
                continue
            items = [e.value for e in value.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if not items:
                continue
            if names[0] in out and where[names[0]] != str(p):
                return {}, (f"词表 {names[0]} 在两个定义文件里都有："
                            f"{where[names[0]]} 与 {p} —— 两份定义点必须合成一份")
            out[names[0]] = items
            where[names[0]] = str(p)
    return out, ""


def _class_default_literals(paths: list[Path]) -> list[str]:
    """`R-31`：定义文件里**类体属性默认值**的字符串字面量（例如 `status: str = "proposed"`）。

    为什么需要它：`Conjecture.status` 的默认值就是 `"proposed"` —— **每一行猜想生下来
    就是它**，那是货真价实的产出点，而定义点整份被排除之后普查看不见。

    为什么**不**把定义文件整份算进产出正文（本条的第一次实现，已否决）：`schema.py`
    的其余部分有大量注释与报错文案；整份算进去之后，真正死掉的取值会因为
    "在注释里被提到过"而变成"有产出" —— 实测 `dead_total` 从 6 变成 **0**
    （见 `draft/28` §168 的对照读数）。只取类体默认值：那是**代码真的会写进数据**的
    字面量，判据精确，且不动其余口径。
    """
    out: list[str] = []
    for p in paths:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for stmt in cls.body:
                value: ast.expr | None = None
                if isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                    value = stmt.value
                elif isinstance(stmt, ast.Assign):
                    value = stmt.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    out.append(value.value)
    return out


def _producer_text(src_dir: Path, exclude: set[Path]) -> tuple[str, int]:
    """把 `src/**/*.py`（排除词表定义点所在的那几个文件）读成一大段文本。

    为什么要排除定义点：不排除的话每个取值都会"命中它自己的定义"，于是永远报不出死取值 ——
    那是这条普查最典型的假绿形态（实测：把定义文件整份算进产出正文时 `dead_total` 从 6 变 0）。
    排除的是**定义文件整份**；定义文件里有真实产出面的那部分（类体默认值）由
    :func:`_class_default_literals` 精确补回来（`R-31`）。
    """
    parts: list[str] = []
    lines = 0
    for p in sorted(src_dir.rglob("*.py")):
        if p in exclude:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        parts.append(text)
        lines += text.count("\n") + 1
    return "\n".join(parts), lines


def census(root: Path) -> dict:
    """跑一次普查，返回结果字典（`checked` 为假表示没查成）。"""
    src = root / "src"
    definition_paths = [src / rel for rel in VOCAB_DEFINITION_FILES]
    missing = [str(p) for p in definition_paths if not p.is_file()]
    if missing:
        # 少一个定义文件 ⇒ **没查成**（那几张词表会静默落在判据面之外，而读数照样好看）
        return {"checked": False, "reason": f"读不到定义文件：{missing}"}
    try:
        vocabs, dup_problem = _vocab_constants_in(definition_paths)
    except ValueError as exc:
        return {"checked": False, "reason": str(exc)}
    if dup_problem:
        return {"checked": False, "reason": dup_problem}
    blob, producer_lines = _producer_text(src, set(definition_paths))
    defaults = _class_default_literals(definition_paths)
    if defaults:
        # 把类体默认值当成一段"合成产出正文"接在后面（`R-31`）：它们是代码真的会写进
        # 数据的字面量，而不是"在注释里出现过"。这一段的字节不进 `producer_lines`
        # （那是"扫过多少行源码"的读数，不该被合成文本灌水）。
        blob = blob + "\n" + "\n".join(f'DEFAULT = "{d}"' for d in defaults)
    if len(vocabs) < MIN_VOCABS:
        return {"checked": False, "reason": f"只扫到 {len(vocabs)} 个词表（下限 {MIN_VOCABS}）"}
    if producer_lines < MIN_PRODUCER_LINES:
        return {"checked": False, "reason": f"产出点只有 {producer_lines} 行（下限 {MIN_PRODUCER_LINES}）"}

    dead: dict[str, list[str]] = {}
    for name, values in sorted(vocabs.items()):
        missing = [v for v in values if not re.search(rf"['\"]{re.escape(v)}['\"]", blob)]
        if missing:
            dead[name] = missing

    # 两栏分开算、分开给（`P-23`：不许合并 —— 合并等于静默豁免）。
    #
    # 栏一取的是"登记表"而不是"死取值 ∩ 登记表" —— 这个区别是刻意的：
    # 有些被点名的取值机械普查看不见它是死的（`survey` 在 `providers.py` 里是
    # 主题类别 ⇒ 正则命中它；见模块 docstring 的那一节）。若栏一只取交集，
    # 那一条登记就会一个字都不打印 —— 那是比"静默豁免"更糟的形态：
    # 登记表看上去处理了它，而输出里查无此条。
    # 所以栏一按登记表原样打印，并单独标出哪几条今天普查看不见，
    # 让"同形不同义"与"其实已经接线了"这两种情况都必须被人看见。
    reserved: dict[str, list[str]] = {}
    unclaimed: dict[str, list[str]] = {}
    registered_not_dead: dict[str, list[str]] = {}
    dead_pairs = {(name, v) for name, values in dead.items() for v in values}
    for (name, v) in sorted(RESERVED_VALUES):
        bucket = reserved if (name, v) in dead_pairs else registered_not_dead
        bucket.setdefault(name, []).append(v)
    for name, values in dead.items():
        for v in values:
            if (name, v) not in RESERVED_VALUES:
                unclaimed.setdefault(name, []).append(v)
    return {
        "checked": True,
        "vocabs": {k: len(v) for k, v in sorted(vocabs.items())},
        "producer_lines": producer_lines,
        "dead": dead,
        "reserved": reserved,
        "unclaimed": unclaimed,
        #: 已登记为预留、但今天普查不认为它是死取值的那些。两种成因都要人看一眼：
        #: ① 同形不同义（普查看见了字面量，但那是另一个命名空间里的词）；
        #: ② 它其实已经接线了 ⇒ 登记表这一条过期了，应当撤掉。
        "registered_not_dead": registered_not_dead,
        # 这几个数字是分开的，刻意不提供"死取值合计"那一个合并数字当门面 ——
        # 但保留它作诊断（`dead_total`），输出时两栏并列打印。
        "dead_total": sum(len(v) for v in dead.values()),
        "reserved_total": sum(len(v) for v in reserved.values()),
        "unclaimed_total": sum(len(v) for v in unclaimed.values()),
        "registered_not_dead_total": sum(len(v) for v in registered_not_dead.values()),
        "reserved_reasons": {f"{k[0]}.{k[1]}": why for k, why in sorted(RESERVED_VALUES.items())},
        # 没实现的那一半必须出现在输出里（"没查成"与"查过没问题"要能分开）。
        "known_gap": "反向（漏词表：代码产出了不在词表里的字面量）本版未实现 —— 它的口径是 P-22/P-23 的人类裁决项",
    }


def main(argv: list[str] | None = None) -> int:
    _pin_utf8()
    ap = argparse.ArgumentParser(
        prog="vocab_census",
        description=(
            "受控词表普查：找出登记了却没有产出点的取值（死取值）。"
            "退出码 0=没有 / 1=有 / 2=没查成。"
        ),
    )
    ap.add_argument("--root", default=None, help="仓库根（默认本文件的上两级）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args(list(argv) if argv is not None else None)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    t0 = time.monotonic()
    result = census(root)
    secs = time.monotonic() - t0

    if args.json:
        print(json.dumps({**result, "root": str(root), "seconds": round(secs, 2)}, ensure_ascii=False, indent=2))
    elif not result["checked"]:
        print(f"[vocab-census] unknown(2)：没查成 —— {result['reason']}")
    else:
        print(f"[vocab-census] 词表 {len(result['vocabs'])} 个 / 产出点 {result['producer_lines']} 行（{secs:.1f}s）")
        # 两栏必须分开打印、且两栏都打（`P-23`）：合并等于静默豁免。
        # 即使某一栏为空也要打出来 —— "这一栏是空的"本身是信息。
        print(
            f"[vocab-census] 栏一：已登记为预留 {result['reserved_total'] + result['registered_not_dead_total']} 个"
            f"（其中 {result['registered_not_dead_total']} 个今天普查看不见它是死取值 —— 见栏一附）"
        )
        for name, values in sorted(result["reserved"].items()):
            for v in values:
                why = result["reserved_reasons"].get(f"{name}.{v}", "（未写理由：登记表要求写）")
                print(f"  {name}.{v}：预留 —— {why}")
        # 栏一附：登记了、但普查不认为它是死的。必须打印 ——
        # 否则那几条登记在输出里查无此条，等于登记表自己骗自己。
        if result["registered_not_dead_total"]:
            print(
                f"[vocab-census] 栏一附：已登记为预留、但今天普查看不见它是死取值 "
                f"{result['registered_not_dead_total']} 个 ⇒ 需人确认是『同形不同义』还是『登记已过期』"
            )
            for name, values in sorted(result["registered_not_dead"].items()):
                for v in values:
                    why = result["reserved_reasons"].get(f"{name}.{v}", "（未写理由：登记表要求写）")
                    print(f"  {name}.{v}：预留（普查未见其为死取值）—— {why}")
        print(f"[vocab-census] 栏二：无人认领 {result['unclaimed_total']} 个")
        for name, values in sorted(result["unclaimed"].items()):
            print(f"  {name}：{len(values)} 个取值在 src/ 里找不到产出点 —— {values}")
        print(
            f"[vocab-census] 死取值合计 {result['dead_total']} 个"
            "（这一行只是诊断；判定请分别看两栏，不许用合计代替分栏）"
        )
        print(f"[vocab-census] 已知缺口：{result['known_gap']}")

    if not result["checked"]:
        return 2
    return 1 if result["dead_total"] else 0


if __name__ == "__main__":  # pragma: no cover - 由 tests 直接调 main()
    raise SystemExit(main())

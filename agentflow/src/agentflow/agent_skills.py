# -*- coding: utf-8 -*-
"""各智能体的 **skills**（业主 2026-10-14：「把面对不同类型任务应唤起的协作方式写成各智能体的
skills，以防止前置大量提示词，现做现读」）。

## 为什么要"现做现读"而不是"前置全塞"

前置提示词是**每一次模型调用**都要付的代价（真机读数里一个角色的系统提示词两万多字），
而"这一趟到底会遇到哪一类活"要到跑起来才知道。所以这里只把**一张极短的索引**
（slug + 一句话 + 什么时候读它 + 盘上路径）放进前置提示词，正文按需用 `fs.read` 现读。

## 三条硬约束（改这一份的人先读）

1. **不照搬市面原文**：来源（`temp/deepmath/moonshine/assets/skills/builtin` 那 38 个）
   只抽**工作逻辑**，改写成"哪一步由哪个角色做、用我们哪一个真实动作/工具"。
2. **不虚构动作**：每一条 skill 的 `actions` / `tools` 都必须在
   `capabilities`（60 动作 / 32 边）与工具注册表里**真实存在**，
   且从"拥有这条 skill 的角色"出发**够得到**（自己的动作，或它出边上的角色能做）。
   `validate()` 逐条查这件事，判据见 `tests/test_agent_skills.py`。
3. **描述无歧义**：每条 skill 必须写清"什么时候读它"（`when`）——没有这一格，
   索引就变成又一份没人读的长文档。

## 落点

- 目录/正文/索引**只有这一处定义**（本模块的 `CATALOG`）；
- `materialize(root)` 把目录里的每条 skill 写成 `<工作区>/skills/<角色>/<slug>.md`
  （`AGENT-PROFILES.md` 同一条做法：框架在开跑时把可读材料落到工作区里），
  于是角色能用自己的 `fs.read` 现读；
- 前置提示词里只出现 `index_block(role)` 那一段。
"""

from __future__ import annotations

import dataclasses
import pathlib

__all__ = ["SKILLS_DIR", "SURVEY", "Skill", "CATALOG", "skills_for", "index_block",
           "materialize", "validate", "builtin_sources"]

#: 工作区里那一层目录名（相对工作区根）。
SKILLS_DIR = "skills"

#: `shared` 这个槽里的 skill 给**每个角色**（协作链层面的、与某一岗无关的那些）。
SHARED = "shared"


@dataclasses.dataclass(frozen=True)
class Skill:
    """一条 skill：索引要的三格（slug / 一句话 / 何时读）+ 正文 + 它用到的真东西。"""

    slug: str
    title: str
    #: 索引里那一句话（≤60 字；索引是**给模型扫的**，不是给人读的长文）。
    summary: str
    #: 什么时候读它（索引里第二格；这一格缺了，索引就成了摆设）。
    when: str
    #: 正文（markdown，可以长 —— 它按需读，不占前置）。
    body: str
    #: 这条 skill 会派出去的动作（`角色.动作`），逐条由 `validate()` 核可达性。
    actions: tuple[str, ...] = ()
    #: 这条 skill 会自己直接调的工具（`组.名`），逐条由 `validate()` 核存在性。
    tools: tuple[str, ...] = ()


def _m_skills() -> tuple[Skill, ...]:
    """M（军师）那一族 —— 业主点名「特别要给 M 多找素材（毕竟它是军师）」。

    来源（38 个 builtin 里挑出来综合的，逐条写在 §SURVEY）：`math-research-loop` /
    `propose-subgoal-decomposition` / `propose-research-plan-*` / `identify-key-failures` /
    `research-consolidation` / `literature-survey` / `record-novelty` / `quality-assessor` /
    `memory-trigger-evaluator`。M 自己没有动作（它是主控），所以它的 skill 全部落在
    "派给谁、按什么顺序、卡了怎么办"上，用到的是 `summon` 形状与 `conductor.*` 工具。
    """
    return (
        Skill(
            slug="立项-从一句话到可派的三件",
            title="把用户的一句话拆成三件可派的活",
            summary="一句话任务 → 先落一条命题 + 一份检索 + 一次复现，而不是先写计划书",
            when="开跑第一步；或用户给的目标还是一句自然语言、没人知道该动谁的时候",
            actions=("A.search_literature", "D.propose_question", "E.run_experiment"),
            tools=("conductor.status_report", "conductor.closing"),
            body="""# 把用户的一句话拆成三件可派的活

## 判据（什么时候算拆好了）

三件活各自满足：**有一个明确的收件角色**、**它做完会落一行台账**、**你能拿那一行做下一步**。
三件里缺任何一件，说明这一件还只是"要研究 X"这种空话。

## 步骤

1. **先定口径**：这句话里哪些是用户定的取舍（目标、范围、要不要形式化、花多少）？
   只有用户能定的，用 `ask_user` 当面问（主控特权，见循环协议第 6 条）；别自己替他定。
2. **三件活**（缺哪件补哪件，不是每趟都要三件）：
   - **要外部事实** ⇒ 派 `A.search_literature`（它落 `search_requests` → 回文献行）；
   - **要内部结论** ⇒ 派 `D.propose_question` / `D.research`（它落 `research_questions` /
     `conjectures`），D 会自己往下派 E/F；
   - **要可复现的数** ⇒ 派 `E.run_experiment`（它落 `experiments`，证明/数值都在那一张表）。
3. **每件活都写 `notify`**（`summary` + `body`）：这是交接留痕，也是被派人拿到的全部背景。
   没写 = 这一趟没有手稿，接手的人只能去翻会话记录。
4. **收工前看两处**：`conductor.status_report` 的读数（谁在飞、谁交了差）、
   以及**你这一趟列的任务列表**（每一项 `done` / `not_done` / `cannot` 照实写）。

## 反面形态（真机里出现过）

- 把"研究 X"原样派给 D 就算完事 —— D 拿到一句没有口径的话，只能自己猜一个方向；
- 先写一份很长的计划书再派活 —— 计划书不进台账，下一趟没人读得到它；
- 一次性派十条给同一个角色 —— 并发上限与写集分波会让它们排成串行，白等。
""",
        ),
        Skill(
            slug="派活-按写集分波而不是按心情",
            title="一批活怎么派：按写集分波、按角色分实例",
            summary="同一张表的活串行、不同表的活并发；同角色多实例用 instance 标签",
            when="一次要派两件以上、或两件活会写同一张表的时候",
            actions=("A.search_literature", "B.run_once", "E.run_experiment", "G.build_document"),
            tools=("conductor.status_report",),
            body="""# 一批活怎么派

## 一条判据

**同波并发的前提是"写集不相交"**（`policy.estimate_write_conflict`）。所以：

- 两件活都写 `statements` ⇒ 放**不同波**（`summon_many` 会自己按写集分波，别指望它并发）；
- 一件写 `literature`、一件写 `experiments` ⇒ 可以同波；
- 同一角色要同时干几件 ⇒ 用 `summon_many` 并给每一项不同的 `instance` 标签
  （`summon` 那一形状里没有 `instance`，写了会被丢掉）。

## 步骤

1. 先看这一批**各自会写哪张表**（`conductor.role_spec` 能读到一个角色的写集）；
2. 按上一条分波；一浪里别塞超过在飞上限（超了会被 `fanout_exceeded` 拒，或者等到超时）；
3. 派完**立刻看读数**：返回里的 `waves` / `concurrent_peak` 是"到底并发了没有"的证据 ——
   一次一个地派会把本该并行的活排成串行，而账面上看不出来；
4. 每一件都带 `notify`（这一批算一次派活，写一行手稿）。

## 什么时候**不要**并发

- 后一件活要用前一件的产出（例如 G 要等 B 登记完命题才写正文）；
- 两件活会争同一份**唯一**资源（例如都去跑同一个 Lean 目标）；
- 你还不清楚这一批该不该做 —— 先派一件探路，看清了再批量。
""",
        ),
        Skill(
            slug="卡点-先定位再改派",
            title="卡住了先定位：是能力面、职责面，还是口径没定",
            summary="被拒一次要读理由码再决定改派/切面/上报，别换名字重试同一次越权",
            when="有子代理被拒、超预算、反复 no_change，或你觉得这件事好像没人能做的时候",
            actions=("A.run_once", "C.neighbors", "D.propose_question"),
            tools=("conductor.status_report", "conductor.board"),
            body="""# 卡住了先定位

## 三档，处置完全不同

1. **能力面不够**（子代理自己不会、它出边上的伙伴也不会）：
   读秘书给的 `reach_fit` 读数 —— `unreachable` 说明**它那一支里没有任何人会**。
   处置：改派给有它的那一支，或者把"要谁做"写给直接父（代唤申请），
   或者如实记成「职责之外」。
2. **职责面不够**（这件活本来就不该由它做）：
   读到 `forbidden_edge` 就是这个意思 —— 它**不是**故障，是"这条边不存在"。
   处置：看拒绝理由里点名的**能替你派的角色**，改派；别换个名字重试同一次越权。
3. **口径没定**（该不该做、按什么标准算、取舍怎么定）：
   这是**只有用户能定**的那一档 ⇒ `ask_user`（主控）或写进 final 交回召唤者。

## 一条纪律

`unknown` **不是**"做得到"：名字拼错、角色名认不出，都是"判不了"。
先把名字写对再看结论 —— 把"没查成"读成"没问题"是本项目最贵的一种错。

## 上报怎么写（被派的活干不着时）

- **职责之外** ⇒ 把能力内的做完 + 一条 message 上报，然后正常收工（不写 `blocked`）；
- **需要请示实施细则** ⇒ 才 `blocked`：`{"blocked": {"what": …, "why": …, "needs": …}}`
  三格都要有（说不出被什么卡住就落不到盘上；说不出要请示什么，那多半是职责之外）；
- 两条路的共同要求：**上报要落盘**（手稿 / 板项 / 问题），口头说过了不算。
""",
        ),
        Skill(
            slug="收工-门是读数不是判决",
            title="收工前：门、任务列表、结论三样对齐",
            summary="机器报的格是读数；不认它就写明理由，不许盖掉当没看见",
            when="准备收工、或收工门报红/报 unknown 的时候",
            actions=("G.build_document", "H.review"),
            tools=("conductor.closing", "conductor.acceptance"),
            body="""# 收工前

## 三样东西必须对齐

1. **任务列表**（你自己列的）：每一项 `what` + `state ∈ done/not_done/cannot`；
   `cannot` 的每一项都要有 `why`（说不出为什么，等于没查）。
2. **结论**（`goal_met`）：被派的活做完了没有 —— 判据是**活**，不是"步数用尽"、
   也不是"机器说没事"。步数从来不是收工理由。
3. **收工门**（`conductor.closing` 的读数）：它是**读数**，不是判决。
   门报 `unknown`（没查成）与报 `pass`（查过了没问题）是两件事，
   读到 `unknown` 不许写成"应该没事"，也不许直接盖掉 —— 写明"这一格没查成 + 为什么"。

## 卡在哪一档

- 缺**证据** ⇒ 派能出证据的角色（数值 `E.run_experiment`、形式化 `E.check_formal`、
  逐条走查 `B → V`、稿件级审校 `H.review`）；别把"缺证据"写成"结论成立"。
- 缺**稿件** ⇒ `G.build_document`（正文与引用一起落，引用要能查到那一行）。
- 缺**用户口径** ⇒ `ask_user`（问出去就停在原地等，见协议第 6 条）。

## 一条最容易犯的错

把"没查到 / 没接线 / 被拒绝"写成"没有问题"或"不存在"。三态纪律对主控同样成立：
你的结论是要被人拿去决策的，哪一种"没查成"都要说出口。
""",
        ),
        Skill(
            slug="指派-按任务类型选收件人",
            title="按任务类型选收件人（含两条只能间接走的链）",
            summary="这类活收件人是 X；要 F 走 D→F，要 V 走 F→V —— M 到 F/V 没有直接边",
            when="拿到一件活、要决定「这该派给谁」的时候（尤其是想派 F 或 V 的时候）",
            actions=("A.search_literature", "B.run_once", "C.neighbors", "D.propose_question",
                     "E.run_experiment", "G.build_document", "H.review"),
            tools=("conductor.role_spec", "conductor.summon_many"),
            body="""# 按任务类型选收件人

## 决策表（左列是活，右列是收件人与它的第一个动作）

| 这件活是 | 派给谁 | 起手动作 |
|---|---|---|
| 要**外部事实**（有没有人做过、要一份文献） | A | `A.search_literature` |
| 要**消化一手材料**成台账（抽取/重抽取） | B | `B.run_once` |
| 要**盘上/结构读数**（哪里薄、谁挨着谁） | C | `C.neighbors` |
| 要**把一件模糊的事立成研究问题** | D | `D.propose_question` |
| 要**一条硬的数**或形式化裁决 | E | `E.run_experiment` |
| 要**一份稿件/论文** | G | `G.build_document` |
| 要**稿件级审校** | H | `H.review` |

上表每一行都是**直接边**（`M → {A,B,C,D,E,G,H}`）。两个角色**不在**你的直接出边里：

- **F（攻坚）**：走 `M → D → F` —— 把"要证哪一条、卡在哪一步"写进**给 D 的派活**；
- **V（逐行走查）**：V 只由 **F** 派（`F → V`），所以走 `M → D → F → V` ——
  同样写进给 D 的派活，别自己去派 F 或 V：直接派会得到 `forbidden_edge`（受控拒绝）。

## 被拒之后的处置（别换名字重试）

`forbidden_edge` 是"这条边不存在"，不是故障：换一条链。三条替代链是
**M→B**（直接）、**M→D→F**、**M→D→F→V**。

## 一次派几件

一件活一个收件人；要一批并发就用 `conductor.summon_many` 并让它**按写集分波**
（同角色多实例给不同 `instance` 标签）。派之前用 `conductor.role_spec`
读一眼收件人的**写集**——那才是"能不能同时做"的判据，不是你的心情。
""",
        ),
    )


def _b_skills() -> tuple[Skill, ...]:
    """B（消化与登记）。

    来源：`extract-project-claims`（把正文里的断言抽成结构化行）、
    `extract-conclusion-memory` / `conclusion-manage`（结论按类型管起来）、
    `extract-reference-memory`（出处与引文）、`memory-hygiene`（留痕卫生）。
    """
    return (
        Skill(
            slug="登记-三件式与证据三态",
            title="登记一条命题：三件式 + 证据三态",
            summary="定理内容 / 证明过程 / 出处三件齐；quote_verified 是三态，不许自报",
            when="第一次把一条命题写进 statements，或补一条缺出处的旧行时",
            actions=("B.register_statement", "V.verify_proof"),
            tools=("table.get", "table.schema"),
            body="""# 登记一条命题

## 三件式（缺哪件都不算登记完）

1. **定理内容**：含**完整假设**的正文（`statement_full`）—— 省掉假设的命题会被下游
   当成无条件成立，这一条是本表最硬的门；
2. **证明过程**（`proof_text`）：外部文献来的就是原文那一段逐字摘录；
   自产命题（`origin="own_result"`）才是"我们自己的证明"；
3. **出处**：`external_lit` 要 `source_lit_id` + `page_range`；`own_result` 要
   `doc_id` 或 `line_range`。**出处不在库整笔不写**。

## 证据三态（这一格最容易被自报）

`quote_verified` 只有三种值，写之前先问自己是哪一种：

- `True` —— 引文回验过了（**逐字命中**或**语义相同**，两档都要说清是哪一档）；
- `False` —— 对不上（写 `quote_reason` 说清怎么对不上）；
- `None` —— **还没查**（`quote_reason` 写"为什么还没查"）。
  `None` 不是"没问题"，别把它写成 `True`。

引文语义那一档（业主 2026-10-14 口径）必须留证据：来源里那一段逐字正文 +
那一次判定的调用记录 —— 说不出对着哪一段、哪一次判的，就不算通过。

## 等级不许自报

`conjecture` / `pre_theorem` / `theorem` 是从**五元位现算**的，盘上那一格只是缓存。
写了更漂亮的等级，判据照样按现算读 —— 白写。
""",
        ),
        Skill(
            slug="消化-先在正文里定位再登记",
            title="消化一篇文献：先在正文里定位，再落行",
            summary="拿到「请登记这几条」，先逐条在原文里找到它，再登记（含行号/页码）",
            when="被派去消化一份 PDF/手稿、或有人让你「把这几条登记进去」的时候",
            actions=("B.register_statement", "C.neighbors"),
            tools=("manuscripts.read", "fs.search", "table.list"),
            body="""# 消化一篇文献

## 顺序不能反（R14 的教训）

**先在正文里定位那一条，再登记它**。反过来的形态是"照着手稿里的一句转述登记"，
而转述与原文常常不是一回事（真机里出现过"手稿说 7 条定理，正文里只有 6 条"）。

1. 用 `fs.search` 在正文里找**环境**（`\\begin{theorem}` 这类）或标签（`thm:`），
   拿到真实行号；
2. 逐条读**它那一段**（`fs.read` 带 `start_line` / `max_lines`），把
   `statement_full` 抄全、`proof_text` 抄那一段证明；
3. 页码：PDF 有文本层就填真实页码；只有 `.tex` 时把行号写进 `label`，
   **不要编一个页码**（编出来的页码会被审稿判据拿去核，然后对不上）；
4. 再调 `register_statement`。登记完**回读一行**（`table.get`）确认落盘的形状。

## 与图那一侧对一下

登记完用 `C.neighbors` / `C.structural_duplicates` 看结构读数：
同一条命题被登记两次、或一条关系两边指向同一个概念 —— 这两样是查重判据
真正会抓的形态，早看早改。
""",
        ),
        Skill(
            slug="重抽取-什么时候提、怎么给依据",
            title="重抽取（reprocess）：什么时候该提，依据怎么写",
            summary="引文对不上、或一条关系该换一种读法时才提；请求要带 relation_ids 与为什么",
            when="发现已有的抽取结果对不上原文、或一条关系的表述需要换一种读法时",
            actions=("B.reprocess_once", "B.run_reprocess", "H.judge_quote_semantics"),
            tools=("table.search", "table.list"),
            body="""# 重抽取

## 什么时候提

- **引文对不上原文**（逐字与语义两档都不成立）；
- **一条关系的表述该换一种读法**（例如把"交换性可放宽到有限环"读成"只在有限环成立"）；
- **同一个概念被抽成了两条**（结构重复那一档）。

反过来说：**只是"我想再读一遍"不该提** —— 那会白烧一轮抽取。

## 怎么给依据（少一条都不算可受理）

请求落 `reprocess_requests`：`relation_ids`（要点名，不是"那几条"）+
`reason` ∈ 受控词表 + `note` 写清"哪里对不上、正确读法是什么"。
B 的 `run_reprocess` 会领走它 —— **只在报告里写"这个关系该重抽"等于没提**。

## 拿不准就先判语义

"逐字不一样"不等于"意思不一样"：先用 `H.judge_quote_semantics` 判一次语义
（它会留下 verdict + 那一次判定的调用记录）。判出来"语义相同"就不必重抽。
""",
        ),
    )


def _h_skills() -> tuple[Skill, ...]:
    """H（稿件级审校）。

    来源：`verify-overall`（整体核验）、`verify-correctness-logic`（逻辑轴）、
    `pessimistic-verifier`（默认怀疑）、`quality-assessor`（质量分档）。
    """
    return (
        Skill(
            slug="审校-每条发现都要能复核",
            title="审校：每条发现都要指到那一行、并给出最小修法",
            summary="发现必须带轴/严重度/行号/逐字引文/最小修法 —— 光说「有问题」不算",
            when="做 review / review_report，或收到「这几处改了吗」的复核请求时",
            actions=("H.review", "H.verify_fixes", "A.run_once"),
            tools=("manuscripts.read", "table.list"),
            body="""# 审校

## 一条发现的最小形态

**轴**（体例 / 数学 / 引用 / 结构）· **严重度**（error / warning / info）·
**行号** · **逐字引文**（≤20 词，从正文里抄，不是转述）· **最小修法**。
五格缺一，这条发现就是"审校者的印象"，而不是可复核的读数 ——
真机里出现过"评审方提的 medium 泄漏是错的，实现方拿证据顶回来"这种事，
所以发现本身也要能被顶。

## 两档别混

- `H.review`：**审稿** —— 出 findings（落 `review_findings`）；
- `H.review_report`：**审报告** —— 判一份报告站不站得住（体例与承重）。
一次只做一件；两件放一起会让"这是稿子的问题还是报告的问题"读不出来。

## 引文那一档

拿不准逐字对不上算不算错，用 `H.judge_quote_semantics` 判**语义**（四档结论：
`same_meaning` / `different` / `stronger_than_source` / `unjudgeable`）。
"比原文更强"（`stronger_than_source`）是数学写作里最常见的隐性缺陷：
原文有条件、正文里没了 —— 这一档必须指出来。

## 复核修法

别人说"改了"，用 `H.verify_fixes` 逐条核**改没改对**，而不是重头再审一遍。
""",
        ),
        Skill(
            slug="悲观核验-先找边界与反例",
            title="悲观审校：先找边界情形与反例，再读论证",
            summary="默认「这条结论有问题」：先试小情形、退化情形与极端参数",
            when="一条结论「看起来对」、或作者自己很有信心的时候（那时最容易漏）",
            actions=("H.review", "E.run_experiment"),
            tools=("table.search", "fs.read"),
            body="""# 悲观审校

## 顺序反过来

通常的读法是"跟着论证走，找漏洞"。悲观那一档先做三件事：

1. **最小情形**：参数取最小（n=1、图是单点、群是平凡群）它还对吗？
2. **退化情形**：假设里的条件取等号/取边界（紧性刚好用到、电导下界刚好取到）呢？
3. **极端参数**：条件全都放宽一点，结论先坏在哪一步？

三步里任一步给出反例 ⇒ 这条结论的问题**已经定位到那一步**，
比"论证读了三遍没看出毛病"有用得多（读不出毛病与没有毛病是两件事）。

## 找到反例怎么办

- 反例要**落盘**：派 `E.run_experiment`（它落 `experiments` 行，带可复跑的
  `code_path` / `code_hash` / `exit_code`）—— 只在报告里写"我试了一个反例"不算；
- 然后如实写"结论在 XX 条件下不成立"，**不要**把反例改小成"表述不严谨"。

## 一条纪律

`看不出来` 是合法的三态之一，但它必须**说清卡在哪**（哪一步、缺什么读数）。
把它写成 `成立` 是本项目最贵的一种错。
""",
        ),
    )


def _v_skills() -> tuple[Skill, ...]:
    """V（证明级复核）。

    来源：`pessimistic-verifier` / `verify-correctness-logic` /
    `verify-correctness-assumption` / `lemma-prover`（逐引理读）。
    """
    return (
        Skill(
            slug="复核-三态并指到那一步",
            title="复核一份证明：三态结论 + 指到那一步",
            summary="成立 / 有毛病 / 看不出来；退回必须说清哪一步、缺什么依据",
            when="F 把写成的证明交来复核时（每次都是冷启动：只看证明本身）",
            actions=("V.verify_proof", "F.step"),
            tools=("fs.read", "table.get"),
            body="""# 复核一份证明

## 三态（只有三个，没有第四个）

- **成立**：每一步的依据都能在证明里或册子上找到；
- **有毛病**：指出**哪一步**（步号）+ 缺什么依据 + 补上之后能不能过；
- **看不出来**：写清卡在哪一步、缺什么读数才能判。

"我没看出毛病"**不是**"成立" —— 这一条是这个岗位单独被登记过的那类错
（漏检与通过在台账上只差一个字）。

## 退回的语气是给下一个人的

"有毛病"本身不构成可操作的信息。退回时必须给：**哪一步**、**缺什么**、
（能给的）**最小补法** —— F 按那一条补，而不是重写整篇。

## 顺手核对两件事

1. **假设轴**：证明里用到的前提，正文那条命题真的写了吗？（用了没写的条件
   ⇒ 这不是证明，是另一条命题）；
2. **引文轴**：引用外部结论的那几步，引文是否真的在原文里（逐字或语义那一档）。
""",
        ),
        Skill(
            slug="假设轴-前提是否真被满足",
            title="假设轴：结论用的条件，原文真的给了吗",
            summary="逐条核「这一步凭什么成立」：条件、量词、退化情形三样",
            when="复核一条「看起来很强」的结论，或原文的假设写得含糊时",
            actions=("V.verify_proof", "F.status"),
            tools=("fs.read",),
            body="""# 假设轴

## 三条最常出问题的地方

1. **条件被偷偷加强**：原文里"有限生成"在论证里变成了"有限"；
2. **量词顺序**：`∀ε ∃δ` 与 `∃δ ∀ε` 是两条命题（换序之后常常变成假的）；
3. **退化/边界情形**：空集、单点、零测、n=1 这些"显然"的地方往往是缺口。

## 怎么做

- 每一步问一句"**这一步凭什么**"：依据在证明里（前一步）还是在册子上（一条已登记的
  命题 / 实验）？两处都找不到 ⇒ 那一步没有依据；
- 找到一条被引用的册子行，就去看它**自己的假设**有没有被满足
  （`table.get` 读那一行的 `statement_full`）—— 引用链上第一处不满足就是毛病所在；
- 读不到证明全文时如实回 `reason`，不要凭题目猜内容。

## 与形式化那一档的关系

能机器核的（`E.check_formal` 过的那几条）不是免除这一档：形式化证的可能是
**被加强过的假设**，而那正是这一轴要抓的。
""",
        ),
    )


def _e_skills() -> tuple[Skill, ...]:
    """E（实验与形式化）。

    来源：`construct-counterexamples`（造反例）、`construct-toy-examples`（玩具例）、
    `verify-correctness-computation`（算得对不对）、
    `examination-of-special-cases-*`（特例审查）。
    """
    return (
        Skill(
            slug="反例优先",
            title="先试能不能造出反例，再动手证",
            summary="动手证明之前先花一步找反例；反例要落 experiments 行，不许只在报告里说",
            when="拿到一条「应该对」的命题、或准备开始一轮攻坚之前",
            actions=("E.run_experiment", "B.register_statement"),
            tools=("table.schema", "fs.write"),
            body="""# 反例优先

## 为什么先做这一件

证一条假命题可以烧掉一整轮预算（真机里有过：三轮攻坚之后发现前提被写强了）。
而"找一个反例"通常只要一步：写十几行脚本、在最小参数上跑一遍。

## 步骤

1. **把命题写成可判定的形式**：哪些是变量、量词怎么排、边界在哪里；
2. **从最小情形往外试**：参数取最小 → 逐步放大 → 随机试几组；
3. **落盘**：`E.run_experiment`（数值实验）或 `E.run_script_experiment`（脚本），
   带 `code_path` / `code_hash` / `exit_code` 与那句可复跑的命令 ——
   **只在报告里写"我试了一个反例"不算**；
4. **结论二选一**：找到反例 ⇒ 让 `B.register_statement` 把"这一条不成立（反例：exp:…）"
   如实登记；没找到 ⇒ 把"试了哪几组参数、都没坏"写进依据 —— 它是"没找到"，
   **不是**"成立"。

## 一条纪律

数值"看起来对"不是证明：收敛慢、浮点误差、参数太特殊都会骗人。
它只能当**证据的一档**（`numeric`），等级由五元位现算。
""",
        ),
        Skill(
            slug="小例先行-先算最小情形",
            title="小例先行：最小情形先跑通，再谈一般性",
            summary="从 n=1 / 单点 / 低维开始，把「为什么」先看清再写一般结论",
            when="面对一条一般性结论、或要判断「这个方向对不对」的时候",
            actions=("E.run_experiment",),
            tools=("fs.write", "fs.read"),
            body="""# 小例先行

## 小例的三个用处（都不是"举例说明"）

1. **发现问题**：一般情形里的隐含条件，往往在小例上直接暴露（某个和是 0、某个域不非空）；
2. **给量级**：常数大概多大、增长多快 —— 后面写"显然有界"时心里有数；
3. **当回归**：小例算出来的数就是后面代码的测试用例（改一次跑一次）。

## 怎么做

- 写一个**最小脚本**（不用框架、不用库的那一种），把算式原样敲进去；
- **打印中间量**，不只打印结论（"结论对"可能来自两处错误互相抵消）；
- 把脚本与它的输出一起留在工作区（`fs.write`），并在实验行里写 `code_path`；
- 小例与一般情形的差：小例通常**退化了**（量词变成有限个），
  所以在结论里写清"这一档验到哪一步"。

## 反面形态

用一个大而全的脚本一次算完：出错时你不知道是哪一步，
而"跑通了"也不说明任何一步是对的。
""",
        ),
        Skill(
            slug="形式化-能机器核的才算数",
            title="形式化：能机器核的才签 formal，且要写清核的是什么",
            summary="check_formal 过的那几条才算 formal 位；假设被加强过的不算",
            when="一条结论要用形式化背书（proof/formal 位），或有人问「这个 Lean 文件算不算数」时",
            actions=("E.check_formal", "E.evidence_for"),
            tools=("fs.write", "fs.list"),
            body="""# 形式化

## 只有"检查器原话"才算数

- 形式化那一档要留下**检查器的原话**（`verifier_output`），
  而不是"我写完了、编译过了"；
- 假设被**加强**过的定理：机器核过也不等于原文那条成立 ——
  这一类要如实写成 `stronger_than_source` 那一档的缺陷，别拿它当原文的背书；
- 检查器没装 / 开关关着 ⇒ 如实回 `lean_disabled` / `not_wired`，
  这条路的替代是 V 的自然语言逐行走查（三态结论），**不是**"证明通过了"。

## 写 Lean 代码的落点

- 文件落到工作区 `code/lean/`（`fs.write`），实验行里写 `code_path` + `code_hash`；
- 每次跑完记 `exit_code` 与那句可复跑的命令 —— 别人要能一键重跑；
- 一条定理一个文件比一个大文件好：**哪一条没过**要一眼看得出来。

## 一条纪律

形式化不是"更严格所以更可信"的自动挡：它核的是**你写下的那条**。
写窄了（少一个假设）、写偏了（换了定义），机器都会高高兴兴地报通过。
""",
        ),
    )


def _f_skills() -> tuple[Skill, ...]:
    """F（证明攻坚）。

    来源：`lemma-prover` / `proof-constructor` / `direct-proving` / `proof-corrector` /
    `propose-subgoal-decomposition`。
    """
    return (
        Skill(
            slug="攻坚-一次一步并留中间态",
            title="攻坚：一次一步，每一步留得下中间态",
            summary="先立项（预算不完整即拒）；step 是唯一会改计划的方法；一轮一步",
            when="被派一条要证的命题，或一条计划要往前推一轮的时候",
            actions=("F.create_plan", "F.step", "F.status"),
            tools=("attack.create_plan", "attack.pick_next_subgoal", "attack.check_budget"),
            body="""# 攻坚：一次一步

## 立项（`F.create_plan`）

**预算不完整即拒绝，且不写库** —— 被拒是受控的：补齐预算（步数/时间/目标）
再立一次，别把"没立成"当成"不需要立"。

## 推进（`F.step`）

`F.step` 是**唯一会改计划的方法**（`list_plans` / `status` 只读）。
一轮一步：一轮里塞三件事，出错时你不知道是哪一步坏的。

## 中间态必须留得下（这一条最容易被省）

每一步的产出要能**被别人复核**：把一个中间结论写成命题（交 **B** 登记，
`F → B` 是直接边）或写成盘上的文件（`fs.write`），而不是只在话里说"我证到了这一步"。
理由：复核的人（**V**）是**冷启动**的 —— 它只看证明本身，不看你的心路。

## 卡住时

先 `F.status` / `F.list_plans` 读当前状态，再说卡在哪一步、缺什么。
"看不出来"是合法的三态之一，但它必须指到那一步。
""",
        ),
        Skill(
            slug="交付-证明要能被别人复核",
            title="交付一份证明：可复核、可退回、可逐条改",
            summary="proof 由 V 签才算数；自报 proof 会被降级；要复核就派 V（F 才有到 V 的边）",
            when="一份证明写完了要交出去，或被 V 退回来要改的时候",
            actions=("F.step", "V.verify_proof", "B.register_statement"),
            tools=("table.get", "verify.check_formal", "fs.write"),
            body="""# 交付一份证明

## 谁签那个字

- **证明文本**落 `statements.proof_text`（由 B 登记）；
- **"审过"由 V 签**（`verifications`）：`F → V` 是直接边 —— **V 只能由 F 派**
  （主控 M 都没有到 V 的边）。所以"要人逐行走查"这件事，落法就是**你派 V**。
- **自报的 `proof` 一律降级成 `cross_check`**（结构强制）：别指望"我说我证了"能算数。

## 三态退回来的活怎么接

V 的结论只有三个：**成立 / 有毛病（指到那一步）/ 看不出来**。

- **有毛病** ⇒ 它给了那一步 ⇒ 只改那一步，别重写整份证明
  （`proof-corrector` 的工作逻辑：**定点修**，改动面越大越难复核）；
- **看不出来** ⇒ 缺的是依据或那一步没写清 ⇒ 补齐**那一处**再交回去，
  别把"看不出来"读成"通过了"；
- 改完**再派一次 V**：复核结论是**逐次**的读数，上一轮签过的字不覆盖这一轮的新文本。

## 形式化那一档

要用机器核（`verify.check_formal`）就**把源码也落进工作区**
（`code/lean/<名字>.lean`，`fs.write`）：裁决与落库之间差的就是这一份可复跑的文件。
检查器没装 / 开关关着 ⇒ 如实回 `lean_disabled` / `not_wired`，替代路是 V 的逐行走查，
**不是**"证明通过了"。
""",
        ),
    )


def _a_skills() -> tuple[Skill, ...]:
    """A（检索与登记）。

    来源：`literature-survey` / `query-memory` / `extract-reference-memory` /
    `memory-hygiene` / `problem-refiner`。
    """
    return (
        Skill(
            slug="检索-先本地再联网",
            title="先问盘上有没有，再决定要不要出网",
            summary="本地书架能答的别出网；出网那一次要过准入闸门并按主题交回来源",
            when="要外部事实、要一份文献清单、或有人问「这个方向有没有人做过」时",
            actions=("A.shelf_search", "A.search_literature", "A.ingest_local"),
            tools=("search.shelf", "search.local", "search.providers"),
            body="""# 先本地再联网

## 顺序（省的是出网那一次，也是可复现那一次）

1. **本地书架**：`A.shelf_search`（`search.shelf`）列出全文已经在盘上的；
   给了 query 还能按主题取最相关的一页与逐字摘录 —— 摘录是**逐字**的，可以直接进 `quote`。
2. **本地词面**：`search.local` 在已入库的文献里找（不联网）。
3. **联网**：`A.search_literature` —— 它入队（过 I7 准入闸门）→ 领跑 → 把候选与来源交回召唤方。
   闸门会拒（配额/重复），**被拒不是失败**：如实说明"这一条没出网，因为 X"。
4. **盘上已有的文件**：`A.ingest_local` 按内容 sha256 幂等登记，不联网。

## 交回什么（判据）

一条候选至少要能指到：**来源标识**（DOI/arXiv id/URL）、**拿到的原文在哪**（盘上路径）、
**它凭什么是相关的**（命中在哪一句）。三格缺一，那一条就只是"我搜到过"。
""",
        ),
        Skill(
            slug="登记-一篇文献只留一个键",
            title="去重：同一篇文献只能有一个键",
            summary="先归一化再判重；重复候选要留读数，不许静默合并也不许两条并存",
            when="登记一条新文献、或发现同一个 DOI 出现了两行的时候",
            actions=("A.run_once", "A.ingest_local"),
            tools=("search.dedup_check", "search.register", "table.schema"),
            body="""# 一篇文献只留一个键

## 次序

1. **归一化**：DOI 小写去前缀、arXiv id 去版本号 —— 归一化规则是**盘上那一份**
   （`dedup.py` 的 `normalize_doi` / `literature_keys`），不是你自己临时想的写法。
2. **查重**：`search.dedup_check` 给读数，别凭标题眼熟就下结论。
   三态：`duplicate`（同一条）· `new`（确实没有）· `unknown`（判不了 ⇒ 说清为什么）。
3. **登记**：`search.register` 落 `literature` 行。

## 两条不许

- **不许静默合并**：两条像但不等（预印本 vs 正式版、会议 vs 期刊）⇒ 如实登记两条并写清关系，
  合并是判断，判断要留痕；
- **不许"先并了再说"**：判重错则概念图静默地少一条或多一条边，没有任何地方会报错 ——
  这正是本仓把 `dedup.py` 划进禁改区的那条理由。
""",
        ),
    )


def _c_skills() -> tuple[Skill, ...]:
    """C（结构与图分析）—— 只读角色。

    来源：`query-memory` / `research-consolidation` / `pessimistic-verifier` /
    `math-research-loop` / `quality-assessor`。
    """
    return (
        Skill(
            slug="结构-先定位再下钻",
            title="结构读数：先定位，再下钻到那一段",
            summary="别一上来读全文；先问图，拿到编号再逐条读原文那一段",
            when="要回答「这堆材料里有什么/哪一块最薄/还缺什么」这一类结构性问题时",
            actions=("C.neighbors", "C.gaps", "C.handle"),
            tools=("graph.neighbors", "graph.stats", "table.get"),
            body="""# 先定位再下钻

## 三层，按代价从小到大

1. **图这一层**（便宜）：`C.neighbors` / `C.hottest` / `C.paths` / `C.proof_chain` ——
   回答"谁挨着谁、哪条链最短、哪个概念最热"；
2. **缺口这一层**：`C.gaps`（结构缺口候选，可显式选择是否提交检索请求）/
   `C.structural_duplicates`（I5 的输入）—— 回答"哪里还薄"；
3. **原文这一层**（贵）：真要看正文，抓**那一段**而不是全文（`fs.read` 带
   `start_line` / `max_lines`；`manuscripts.read` 同理）。

## 产出怎么落

C 的**产出登记口只有 `C.handle` 一处**（报告 ok 时由它收口落 `analysis_reports`）。
所以：先跑分析器，再由 `handle` 收口 —— 只在对话里报一堆读数、没有落 `analysis_reports` 行，
这一趟等于没有产出。

## 一条纪律

结构读数**不是**数学结论：度数高不等于重要，路径短不等于那条证明对。
把"图上看起来是核心"说成"这一条成立"是最常见的越界。
""",
        ),
        Skill(
            slug="矛盾-三态并指到那一对",
            title="报矛盾：指到是哪两行，判不了也要说",
            summary="每条矛盾/重复都要给出两行编号与判据；unknown 不等于没有问题",
            when="要判「这两条说法冲突吗」「这算不算重复」或有人拿两条结论来问的时候",
            actions=("C.contradictions", "C.relations_between", "C.structural_duplicates"),
            tools=("graph.relations_between", "table.search", "trace.relation"),
            body="""# 报矛盾

## 一条矛盾的最小形态

**两行编号**（`rel:` / `stmt:`）+ **冲突在哪**（哪一对取值不能同时为真）+
**判据**（是定义冲突、是范围冲突，还是引用同一来源读出了两种意思）+ **建议处置**。
四格缺一，那就是"C 好像觉得有问题"。

## 三态

- 真冲突 ⇒ 报，并写明**哪一对**；
- 不冲突 ⇒ 也要写清"我按哪条判据核的"（否则下一个人还得重跑一遍）；
- 判不了 (unknown) ⇒ 说清缺什么（缺原文那一段？缺定义？缺来源？）。
  `unknown` **不是**"没问题" —— 把它写成"没有发现矛盾"是本项目最贵的一种错。

## 谁去收口

C 只判、不改：矛盾问题的闭环由 D 的 `D.adjudicate` 收口（I2），
登记与命题归 B。你给出的是**读数与依据**，处置决定不在你手上。
""",
        ),
    )


def _d_skills() -> tuple[Skill, ...]:
    """D（总研究调度）。

    来源：`problem-generator` / `problem-refiner` / `propose-subgoal-decomposition` /
    `cross-domain-explore` / `identify-key-failures`。
    """
    return (
        Skill(
            slug="起手-先立问题再谈别的",
            title="从零起手：先立一行问题，再谈别的",
            summary="D 的其余动作都要求 qid 已存在 ⇒ 第一步永远是 propose_question",
            when="被派来研究一件事，而 research_questions 里还没有这一行的时候",
            actions=("D.propose_question", "D.assess", "D.submit_gaps"),
            tools=("table.get", "table.schema"),
            body="""# 先立问题

## 硬次序（不是建议）

`D.propose_question` 之外的每一个 D 动作都要求 **qid 已经存在** ⇒
从零起手第一步只能是它。问题要写成一条**能判真假**的问句
（"X 在条件 Y 下成立吗" 是问题；"研究一下 X" 不是）。

## 第二步是判证据，不是直接研究

`D.assess` 判**证据够不够**：

- 够 ⇒ 往下走 `D.research`；
- 不够 ⇒ `D.submit_gaps` 把缺口提交成检索请求（**受配额与已提交集约束**，
  被拒是受控拒绝：说清"这一格已经提交过"或"配额满了"，别反复试）。

## 从缺口出网的门

D 自己不检索：`submit_gaps` 之后由 **A** 领跑（A 过 I7 准入闸门）。
所以"缺文献"的处置是**提交缺口**，而不是自己编一条来源。
""",
        ),
        Skill(
            slug="一轮-有界地串起消化到研究",
            title="一轮怎么跑：有界地串，卡在哪一步说哪一步",
            summary="run_round 有界；攻坚经 D→F，复核只能经 F→V，D 没有到 V 的边",
            when="证据已经就绪、要把 ingest → … → research 串起来跑一轮的时候",
            actions=("D.run_round", "D.probe_c", "D.register_conjecture", "F.step"),
            tools=("attack.pick_next_subgoal", "attack.status", "table.get"),
            body="""# 一轮怎么跑

## 形状

`D.run_round` 把 **ingest → … → research** 串成一轮，**有界**（`limit`）：
一轮做完要能看到"这一轮消化了几条、研究了几个、还剩几个"，
而不是"跑到没得跑为止"（那一趟没法归因）。

## 攻坚与复核走哪条链（这一格最容易写错）

- **攻坚**：`D.probe_c` 按问题向 C 点菜，`D.register_conjecture` 落猜想，
  计划的推进交 **F**（`F.step` 之类；D → F 是直接边）；
- **复核**：逐行走查是 **V** 的活，而 **D 没有到 V 的边** ——
  V 只能由 **F** 派（`F → V`）。所以"要 V 核一遍"这句话的落法是
  **把这件事写进给 F 的派活**，不是自己去派 V（派了会被 `forbidden_edge` 拒）。

## 有界与归因

- 每一轮的产出要落台账（`research_questions` / `conjectures` / `experiments`）；
- 一轮里被**跳过**的条目要留原因（`D.ingest_detailed` 会给逐条明细）——
  "没做"与"做了没成"是两件事，报告里必须长得不一样。
""",
        ),
    )


def _g_skills() -> tuple[Skill, ...]:
    """G（成稿）。

    来源：`research-consolidation` / `quality-assessor` / `conclusion-manage` /
    `literature-survey` / `extract-user-memory`。
    """
    return (
        Skill(
            slug="成稿-正文自己写而不是脚本生成",
            title="成稿：正文由你写，编译只负责编",
            summary="散文体正文 fs.write 到 out/paper/main.tex，再 paper_compile；没有渲染脚本这回事",
            when="任务说「整理成论文 / 交付论文 / 稿件」，或要一份可编译的正文时",
            actions=("G.build_document", "G.register_dependency", "G.compose_claim"),
            tools=("fs.write", "doc.paper_compile", "doc.scan_claim"),
            body="""# 成稿

## 业主 2026-10-13 裁定（逐条落地）

- **正文是你写的，不是脚本生成的**：`fs.write` 写到 `out/paper/main.tex`，
  散文体、章节自己排，`\\cite` / 定理环境随你；落笔前后用 `fs.read` 读回来核一遍。
- **没有「渲染脚本」「建论文包」「核锚」这回事**（2026-10-13 退场，见 `draft/117`）。
- **编译**：`doc.paper_compile` 出 `out/paper/main.pdf`。
  本机 MiKTeX 会写完 PDF 却以 `0xC0000409` 退出 ⇒ **产物与退出码分两栏读**，
  别只看退出码判成败。

## 引用与断言

- 每一条断言用 `G.compose_claim` 构造（判据只有一份，在工具层）；
- 外部依赖用 `G.register_dependency` 登记 —— `closed` 时必须核到**已入库**的来源（FC-23）；
- 稿件级审校由 **H** 做（`H.review`），它的判据是"正文与台账逐字一致 + E 的 proof 或 V 的签名"。

## 落点

`documents` 一行 + `out/paper/main.tex` + `out/paper/main.pdf`；
交付说明落在 `out/review/REPORT.md`（那是 M 的活）。
""",
        ),
        Skill(
            slug="修订-按发现逐条改并留痕",
            title="修订：按 H 的发现逐条改，改完留痕",
            summary="revise 逐条对应发现；refresh_markdown 只重画文件、不改数据行",
            when="H 提了发现、或库里数据变了要重画稿件 markdown 的时候",
            actions=("G.revise", "G.refresh_markdown", "G.build_document"),
            tools=("review.list_findings", "doc.compose_claim", "fs.read"),
            body="""# 修订

## 逐条对应（判据）

`review.list_findings` 拿到 H 的每一条发现，`G.revise` 一条一条改：

- **改了** ⇒ 写清改在正文哪一处（行号或逐字引文）；
- **不改** ⇒ 必须写理由（"评审这条是错的"要用证据顶回去，不是沉默）；
- **两条发现互相冲突** ⇒ 指出来，别自己挑一条当没看见另一条。

`revise` 会把 `review_rounds` +1、`status` 置 `revised` —— 轮次是**读数**，不是战绩。

## 别把两件工具用混

- `G.refresh_markdown`：按库里当前数据**重画文件**，**不改数据行**；
- `G.build_document`：写一行 `documents` 并**无条件渲染**。

"重画了一遍"不等于"内容改对了"：改的是正文与台账的一致性，不是文件的时间戳。
""",
        ),
    )


def _shared_skills() -> tuple[Skill, ...]:
    """协作链层面的 skill（每个角色都读得到）。

    来源：38 个 builtin 里"跨角色成立"的那几条 —— `math-research-loop`（迭代闭环）、
    `verify-overall` / `pessimistic-verifier`（默认怀疑）、`research-consolidation`
    （收拢成可交接的一份）、`memory-hygiene`（留痕卫生）。
    """
    return (
        Skill(
            slug="研究闭环-假设尝试核验改进",
            title="数学研究的迭代闭环：假设 → 尝试 → 核验 → 改进",
            summary="把「研究」拆成四步，每一步都要落一行台账；没有台账的那一步等于没发生",
            when="接到一件没有既定解法的研究性任务（不是照着做的活）时",
            actions=("D.propose_question", "E.run_experiment", "F.create_plan", "B.register_statement"),
            tools=("fs.read",),
            body="""# 研究闭环四步

## 四步与它们各自的落点

1. **定假设**：把要证/要试的东西写成一条**可证伪**的命题（不是一句方向）。
   落点：`D.propose_question` → `research_questions`；或 `B.register_statement` → `statements`。
2. **尝试**：一次只推进一步（一个引理、一个反例、一组参数）。
   落点：`F.create_plan` / `F.step`（攻坚计划）或 `E.run_experiment`（数值）。
3. **核验**：用**独立**的一条路验它 —— 数值复用同一份代码、形式化复用同一个假设，
   都不算独立。落点：`E.check_formal` / `V.verify_proof`（`verifications/*.jsonl`）。
4. **改进**：把这一轮学到的东西写成**下一条**要试的东西（不是"再想想"）。
   落点：回到第 1 步，或写进 `handoff`（交接手稿）让下一趟接上。

## 查台账用什么（这一条与角色有关，所以写在这里）

台账落在 `<工作区>/data/<表>.json`（例：`data/statements.json`）。
**两条路读的是同一份**：手上有库表类工具的用 `table.get` / `table.search` / `table.list`；
**主控 M 手上没有**那一组（它的工具面只有 `conductor.*` 与 fs 那几件）⇒ 用 `fs.read`
读那份 JSON，别去找不存在的工具。本文件是**每个角色都读得到**的，所以 `tools` 那一格
只列人人都有的一件（`fs.read`）。

## 两条纪律

- **假设与事实分开记**：`statements` 里的等级是**现算**的（五元位），别自己写一个更漂亮的；
- **没有第二份文本的"自产命题"**：它的 `quote_verified` 是 `None` + `quote_reason` 写明为什么
  —— 不适用不是没做。
""",
        ),
        Skill(
            slug="留痕-证据先行",
            title="证据先行：每一条断言都要能指到一行台账",
            summary="写结论前先问「这一句的证据是哪一行」，指不到就改写成「未核到」",
            when="准备写结论、写报告、或把一条断言交出去之前",
            actions=("B.register_statement", "C.neighbors", "H.review"),
            tools=("fs.read",),
            body="""# 证据先行

## 一条自检

**这一句的证据是哪一行？** 指得到（`stmt:` / `exp:` / `lit:` / `rel:` / 手稿编号）就写上去；
指不到就把这一句改写成"未核到 + 我查了哪几处"。两种写法在报告里必须长得不一样。

查那一行：台账在 `<工作区>/data/<表>.json`。有库表类工具的用 `table.get` / `table.search`；
**主控 M 手上没有**那一组 ⇒ 用 `fs.read` 直接读那份 JSON（两条路读的是同一份）。

## 三层证据（强度不同，别混）

- `numeric`（E 签）/ `formal`（E 签）：可复现的算与机器核验；
- `proof`（F 写、V 核）：证明过程在 `statements.proof_text`，审过由 V 的三态结论签；
- `cross_check` / `heuristic`：交叉比对与经验判断 —— 它们**不是**定理级证据。

自报的 `proof` 一律降级成 `cross_check`（结构强制），所以别指望"我说我证了"能算数。

## 引文那一格

引文回验有两档：**逐字命中**（`verbatim`）与**语义相同**（`semantic`，业主 2026-10-14 口径）。
语义那一档必须留证据（来源里那一段逐字正文 + 那一次判定的调用记录），
说不出对着哪一段、哪一次判的，就不算通过。
""",
        ),
    )


#: 一轮的调研记录（业主：「至少为每种智能体特地去找至少 5 个 skill 来综合考量」）。
#:
#: 键是角色（含 `shared`），值是**真的读过并用上了的**那几条 builtin skill 名
#: （目录名逐字，见 `temp/deepmath/moonshine/assets/skills/builtin`）。
#: 判据 `tests/test_agent_skills.py` 断言每格 ≥5 且名字都在那张清单里 ——
#: 这是"调研过"这件事唯一能被机器核的形态。
SURVEY: dict[str, tuple[str, ...]] = {
    "shared": ("math-research-loop", "verify-overall", "pessimistic-verifier",
               "research-consolidation", "memory-hygiene", "conclusion-manage"),
    "M": ("math-research-loop", "propose-subgoal-decomposition",
          "propose-research-plan-neural-network-functions", "identify-key-failures",
          "literature-survey", "quality-assessor", "record-novelty",
          "memory-trigger-evaluator", "cross-domain-explore"),
    "A": ("literature-survey", "cross-domain-explore", "extract-reference-memory",
          "query-memory", "problem-refiner"),
    "B": ("extract-project-claims", "extract-conclusion-memory", "conclusion-manage",
          "extract-reference-memory", "memory-hygiene"),
    "C": ("query-memory", "extract-conclusion-memory", "research-consolidation",
          "math-research-loop", "quality-assessor"),
    "D": ("problem-generator", "problem-refiner", "propose-subgoal-decomposition",
          "cross-domain-explore", "identify-key-failures"),
    "E": ("construct-counterexamples", "construct-toy-examples",
          "verify-correctness-computation", "examination-of-special-cases-neural-network-functions",
          "verify-correctness-assumption"),
    "F": ("lemma-prover", "proof-constructor", "direct-proving", "proof-corrector",
          "propose-subgoal-decomposition"),
    "G": ("research-consolidation", "literature-survey", "quality-assessor",
          "conclusion-manage", "extract-user-memory"),
    "H": ("verify-overall", "verify-correctness-logic", "pessimistic-verifier",
          "quality-assessor", "memory-hygiene"),
    "V": ("pessimistic-verifier", "verify-correctness-logic", "verify-correctness-assumption",
          "lemma-prover", "verify-overall"),
}

#: 那一份来源目录里全部 38 个 skill 的目录名（判据拿它核对 `SURVEY` 里的名字）。
BUILTIN_SOURCES: tuple[str, ...] = (
    "conclusion-manage", "construct-counterexamples",
    "construct-counterexamples-neural-network-functions", "construct-toy-examples",
    "cross-domain-explore", "direct-proving", "direct-proving-neural-network-functions",
    "examination-of-special-cases-neural-network-functions", "extract-conclusion-memory",
    "extract-project-claims", "extract-project-memory", "extract-reference-memory",
    "extract-user-memory", "identify-key-failures", "lemma-prover", "literature-survey",
    "math-research-loop", "memory-hygiene", "memory-trigger-evaluator",
    "pessimistic-verifier", "problem-generator",
    "problem-generator-neural-network-functions", "problem-refiner", "problem-solver",
    "proof-constructor", "proof-corrector",
    "propose-research-plan-neural-network-functions", "propose-subgoal-decomposition",
    "quality-assessor", "query-memory", "record-novelty", "research-consolidation",
    "strengthening-agent", "understanding-problems-neural-network-functions",
    "verify-correctness-assumption", "verify-correctness-computation",
    "verify-correctness-logic", "verify-overall",
)


def builtin_sources() -> tuple[str, ...]:
    """来源目录里的 38 个 skill 名（唯一一份；`SURVEY` 的判据读它）。"""
    return BUILTIN_SOURCES


#: 目录：角色 → 它的 skills（`shared` 那一槽给所有角色）。
CATALOG: dict[str, tuple[Skill, ...]] = {
    "shared": _shared_skills(),
    "M": _m_skills(),
    "A": _a_skills(),
    "B": _b_skills(),
    "C": _c_skills(),
    "D": _d_skills(),
    "E": _e_skills(),
    "F": _f_skills(),
    "G": _g_skills(),
    "H": _h_skills(),
    "V": _v_skills(),
}


def skills_for(role: str) -> tuple[Skill, ...]:
    """某个角色这一趟读得到的 skills（自己的 + `shared`）。"""
    return tuple(CATALOG.get(SHARED, ())) + tuple(CATALOG.get(str(role), ()))


def skill_path(role: str, slug: str) -> str:
    """`fs.read` 用的相对路径（相对工作区根）。"""
    return f"{SKILLS_DIR}/{role}/{slug}.md"


def index_block(role: str) -> str:
    """前置提示词里那一段（**只放索引**：路径 + 一句话 + 何时读）。

    为什么这一段的形状是"表格 + 一句纪律"：前置提示词每多一行，每一次模型调用都要
    重新付一次；而正文一旦被塞进来，"按需读"就退化成"还是全塞"。
    """
    rows = skills_for(role)
    if not rows:
        return ""
    lines = [
        "**你这一岗的 skills（现做现读）**：下面每一行是一份**盘上**的操作手册 ——",
        f"先看「什么时候读它」，对上了再用 `fs.read` 读 `{SKILLS_DIR}/<角色>/<名字>.md` 的全文。",
        "**不要**把它们当前置知识背下来：这里只给索引，正文按需读。",
        "",
        "| 名字（相对工作区根的路径） | 一句话 | 什么时候读它 |",
        "|---|---|---|",
    ]
    for s in rows:
        owner = SHARED if s in CATALOG.get(SHARED, ()) else str(role)
        lines.append(f"| `{skill_path(owner, s.slug)}` | {s.summary} | {s.when} |")
    lines.append("")
    lines.append("读了之后按它做；做了什么要落台账（**没有台账的那一步等于没发生**）。")
    return "\n".join(lines)


def materialize(root: str | pathlib.Path) -> list[str]:
    """把目录里的每条 skill 写到 `<root>/skills/<角色>/<slug>.md`；返回**新写或改写**的路径。

    幂等：内容与盘上逐字节相同就不写（免得每次开跑都把工作区搅一遍）。
    """
    base = pathlib.Path(root)
    written: list[str] = []
    for owner, rows in CATALOG.items():
        for s in rows:
            path = base / SKILLS_DIR / owner / f"{s.slug}.md"
            text = _render(owner, s)
            try:
                if path.is_file() and path.read_text(encoding="utf-8") == text:
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")
            except OSError:
                continue        # 工作区不可写：不打断这一趟（提示词里那份索引仍然有效）
            written.append(str(path))
    return written


def _render(owner: str, s: Skill) -> str:
    """一条 skill 落盘的正文（头部三行是给人/给机器核对的，正文是操作手册）。"""
    head = [f"# {s.title}", "", f"- 名字：`{s.slug}`", f"- 属于：`{owner}`",
            f"- 什么时候读它：{s.when}", f"- 一句话：{s.summary}"]
    if s.actions:
        head.append(f"- 会用到的动作（角色.动作）：{', '.join(s.actions)}")
    if s.tools:
        head.append(f"- 会用到的工具：{', '.join(s.tools)}")
    return "\n".join(head) + "\n\n" + s.body.strip() + "\n"


def validate() -> list[str]:
    """逐条查"这条 skill 用到的动作/工具真的存在、且从拥有它的角色出发够得到"。

    三态纪律：查不成的（工具注册表读不出来）也要报出来 —— 不许把它读成"没问题"。
    """
    problems: list[str] = []
    try:
        from . import capabilities as C
    except Exception as exc:  # noqa: BLE001
        return [f"读不到 capabilities（这一格没查成，不是没问题）：{type(exc).__name__}: {exc}"]
    surface = _role_tool_surface(problems)
    problems.extend(_slug_problems())
    for owner, rows in CATALOG.items():
        for s in rows:
            if not s.summary.strip() or not s.when.strip() or not s.body.strip():
                problems.append(f"{owner}/{s.slug}：summary / when / body 三格都不许空")
            for item in s.actions:
                role, _, action = item.partition(".")
                if not role or not action:
                    problems.append(f"{owner}/{s.slug}：动作要写成 角色.动作，收到 {item!r}")
                    continue
                spec = C.find_action(role, action)
                if spec is None:
                    problems.append(f"{owner}/{s.slug}：{item} 不是本系统里存在的动作")
                    continue
                if owner == SHARED or role == owner:
                    continue
                if role not in set(C.ALLOWED_EDGES.get(owner, ())):
                    problems.append(
                        f"{owner}/{s.slug}：{item} 这个角色不在 {owner} 的出边里"
                        "（写进去就是一句做不到的指令）")
            for name in s.tools:
                if not surface:
                    continue
                for who in (sorted(surface) if owner == SHARED else [owner]):
                    if name not in surface.get(who, set()):
                        problems.append(f"{owner}/{s.slug}：工具 {name} 不在 {who} 的工具面上")
    return problems


def _slug_problems() -> list[str]:
    """slug 那一格：非空、无空白、能当文件名、全目录唯一。

    ## 为什么值得单独查

    真机里出现过一条 slug 是 `" pessimistic-先找边界与反例"` —— **行首多了一个空格**。
    它不会让任何一格判据变红：`summary` / `when` / `body` 都齐，动作与工具都对，
    正文也确实能落盘。代价在两个看不见的地方：

    1. 盘上会多出一个 `skills/H/ pessimistic-先找边界与反例.md`（名字里有空格的**首字符**），
       而 `index_block` 印出来的路径与它逐字一致 —— 模型照抄那个路径 `fs.read` 是能读到的，
       于是一切"照常工作"，直到有人在别的工具里按名字对不上；
    2. 索引里两条 skill 的空格差异**人眼几乎看不见**，而机器一读就分得开。

    所以这一格必须是机器查的：**"读起来一样"不等于"是同一个名字"**。
    """
    out: list[str] = []
    seen: dict[str, str] = {}
    for owner, rows in CATALOG.items():
        for s in rows:
            slug = s.slug
            if not slug:
                out.append(f"{owner}：有一条 skill 的 slug 是空的")
                continue
            if slug != slug.strip():
                out.append(f"{owner}/{slug!r}：slug 首尾有空白（当文件名会带进去）")
            if any(ch.isspace() for ch in slug):
                out.append(f"{owner}/{slug!r}：slug 里不许有空白")
            if any(ch in slug for ch in '\\/:*?"<>|'):
                out.append(f"{owner}/{slug!r}：slug 里有不能当文件名的字符")
            if slug in seen:
                out.append(f"{owner}/{slug!r}：slug 与 {seen[slug]} 重了（索引里两条分不开）")
            else:
                seen[slug] = owner
    return out


def _role_tool_surface(problems: list[str]) -> dict[str, set[str]]:
    """每个角色**自己那一份**工具面（`角色 → 真名集合`）。

    ## 为什么不查"全注册表里有没有这个名字"

    第一版就是那样写的，而它当场把自己写坏的那四个工具名放过去了 ——
    错在两个地方，两处都是"查了个假面"：

    1. **`build_registry()` 不带 `workspace_root` 时 `fs.*` 整组不注册**
       （`secretary.py` 记过同一件事：不带 `store` 出 68 件、`fs.read` 不在里面；
       带上出 81 件、在里面）。于是 `fs.read` 这种**真名**会被报成"不在工具面上"
       —— 假阳性，而假阳性会让人开始不信这份判据。
    2. **"注册表里存在"不等于"这个角色拿得到"**：`fs.write` 在注册表里，
       而 H 是只读角色，`for_role("H")` 里没有它。一条 skill 说"H 用 fs.write 落盘"
       就是一句做不到的指令 —— 这正是本模块三条硬约束里第 2 条要挡的东西。

    所以这里按角色算面：`for_role(role)` 是 `tools/base.py` 里那份**已经过只读过滤**
    的工具面（它的 docstring 记着"实测就发生过 `fs.write` 混进 H 的工具面"）。

    三态：装配不出来 ⇒ 记一条 `problems`（"没查成"，不是"没问题"），返回空表；
    调用方见空表就跳过工具那一格（动作那一格仍然照查）。
    """
    try:
        import tempfile

        from .tools import TOOL_ROLES, build_registry

        root = tempfile.mkdtemp(prefix="agentflow-skills-surface-")
        reg = build_registry(workspace_root=root).registry
        return {str(r): {s.name for s in reg.for_role(str(r))} for r in TOOL_ROLES}
    except Exception as exc:  # noqa: BLE001
        problems.append(f"读不到按角色的工具面（这一格没查成）：{type(exc).__name__}: {exc}")
        return {}

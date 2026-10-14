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
            tools=("table.schema", "table.list"),
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
            tools=("table.get", "table.search"),
            body="""# 证据先行

## 一条自检

**这一句的证据是哪一行？** 指得到（`stmt:` / `exp:` / `lit:` / `rel:` / 手稿编号）就写上去；
指不到就把这一句改写成"未核到 + 我查了哪几处"。两种写法在报告里必须长得不一样。

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
    try:
        from .tools import build_registry

        tool_names = set(build_registry().registry.names())
    except Exception as exc:  # noqa: BLE001
        problems.append(f"读不到工具注册表（这一格没查成）：{type(exc).__name__}: {exc}")
        tool_names = set()
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
                if tool_names and name not in tool_names:
                    problems.append(f"{owner}/{s.slug}：工具 {name} 不在工具面上")
    return problems

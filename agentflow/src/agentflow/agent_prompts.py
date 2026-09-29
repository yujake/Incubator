"""A-H（含主控 M）的前置提示词：身份、边界、政策、工具、伙伴、契约、三态、循环协议。

## 事实与判断分开

这份模块只写两类东西，界线刻意画得很硬：

- 手写的是判断：职责一句、边界条目、政策条目、招牌错误。它们是设计取舍，没有别的出处。
- 生成的是事实：工具面（`tools.build_registry()` 的 `ToolSpec`）、动作表
  （`capabilities.actions_for`）、可协作的伙伴（`capabilities.ALLOWED_EDGES` 的出边与入边、
  `NON_SUMMONABLE`）、落点（`schema.TABLES`）、失败词表（`judge.JUDGE_PROBLEMS`）。

为什么这条界线重要：手抄一份工具清单或伙伴清单，就等于多了一份会漂移的副本。
`draft/28` §178 的实测是"六个角色零提示词"，而更早的教训（linter R005）是
"cli 里写死了四个角色，于是新增 E-H 时没有任何地方报错"。所以这里的工具与伙伴
一律现算，并且 `tests/test_agent_prompts.py` 有一条判据：改了注册表或边表，
提示词必须跟着变。

## 提示词里的三块可变内容

- `{{task}}`：这一次的任务（由调用方给，通常是被召唤时带过来的参数或一条留言）；
- `{{summoned_by}}` / `{{task_id}}` / `{{depth}}` / `{{budget_left}}`：这次运行的处境；
- `{{inbox}}`：收到的留言摘要（没有就是"没有留言"，不是空串 —— 空串会被严格插值拒掉）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from . import capabilities as C
from . import judge as J
from . import schema as S
from .promptkit import PromptRegistry, Scope, Section, SECTION_ORDERS

#: 提示词版本。改了任何一段文本都要改它 —— 它是审计记录里"这次用的是哪一版"的答案。
#: 为什么不用内容哈希当版本号：人读审计时需要的是一个可比较的短名字，
#: 而哈希另有其用（`prompt_sha256` 逐字记在每次调用上）。
PROMPT_VERSION = "p6"

#: 循环协议：模型与框架之间唯一的约定。工具结果会作为下一条 user 消息回给模型。
LOOP_PROTOCOL = """\
循环协议（你与框架之间唯一的约定）。每一步你只输出一个 JSON 对象：
不要输出解释文字，不要用 Markdown 代码围栏，不要在 JSON 前后加任何东西。

四种形状，互斥，每次只取其一：

1) 调用你自己工具面上的一个数据工具：
   {"tool": "<工具名>", "args": {<按该工具的参数表>}, "why": "<一句话说明为什么>"}

2) 唤起一个伙伴去做一件事：
   {"summon": {"role": "<伙伴角色名>", "action": "<他动作表里的动作名>",
               "params": {<按该动作的参数表>}, "why": "<一句话说明为什么找他>"}}

3) 给一个伙伴留言（不要求他立刻做事，只是把信息传过去）：
   {"message": {"to": "<伙伴角色名>", "subject": "<短标题>", "body": "<正文>"}}
   什么时候该用它（不是"派不动活时的替代品"）：你手上有一条**对方之后会用到的信息**，
   而你现在不需要他做事 —— 例如你查证出的约束（"只在 n<=5 时成立"）、
   一条反例、一个必须遵守的口径、或"这批材料里哪个字段不可信"。
   留言会持久保存，收件人下次运行时会在收件箱里看到它；
   它不会立刻唤醒对方，所以"要他现在做事"仍然用 summon。

4) 收工：
   {"final": "<给调用方的结论>", "evidence": ["<你实际用到的 id>"]}

规则：

- 参数只许用括号里列出的键：参数表是封闭集合，多传一个键就会被拒（invalid_params）。
  派活前先看伙伴表里的参数要求与接线态：**没接线的伙伴派了也会被拒**，不如改派能做的。
- 名字必须是真的：工具名取自上面列出的工具面，角色名与动作名取自律上面列出的伙伴表。
  写错的名字会被当场拒绝，并把拒绝理由原样回给你 —— 那不是失败，是一次纠正。
- 唤起伙伴要过能力表与策略（允许的边 / 深度 / 扇出 / 并发 / 总量 / 预算）。
  被拒绝时框架会告诉你理由码；你可以改主意，但不许换个名字重试同一次越权。
- 每一步只能做一件事。工具结果会作为下一条 user 消息回给你，里面可能很长，摘要优先。
- 你收到的每一份结果都带着它的来路（谁给的、什么动作、成功还是被拒）。
  不许把被拒或没查成当成正常数据继续往下写。
- 收工前先自查两件事：① 有没有'对方之后会用到的约束或口径'还没转达？有就先发 message；
  ② 有没有还没做完但能做的一步？有就做完再收工。两步都查过了，才输出 final。
- 步数或预算耗尽时你必须收工：输出 {"final": ...}。框架也会在最后一步直接要求你收工。
- 你永远不许把"没查到 / 没接线 / 被拒绝"写成"没有问题"或"不存在"（三态纪律），
  也不许编造一个没出现过的 id 当证据。"""

#: 证据契约：全角色共享的一段口径（引文、来源、置信度）。
#: 它对应仓库里已经存在的判据（`quoteverify.check_quote`、`review_tools` 的声明强度判据），
#: 所以这里写的是"判据会怎么判"，而不是另立一套说法。
EVIDENCE_CONTRACT = """\
证据契约（判据会按这几条判你交出来的东西，不要指望它们被通融）：

- 引文一律逐字：关系行的 quote 必须是来源正文里逐字出现的一段连续文字，
  允许的差异只有首尾空白、句内换行、大小写。改写、翻译、省略号截断、拼接两段，都会被判不通过。
- 页码以框架给的分页标记为准，不要用书里印的页码（两者常常差几页）。
- 找不到逐字支撑时，正确做法是不产出这条关系，并在结论里说明缺什么；
  编造一条引文的代价远大于少一条关系。
- 证据强度分层：确定性检查（数值、图结构、逐字回验）高于模型判断。
  任何由模型生成的内容都必须标明来路，不能让读的人以为它是算出来的。
- 置信度只能等于或低于确定性口径算出来的那一档：模型可以把"高"降成"中"，
  不许把"低"抬成"高"。
- 结论的强度不得超过引文能支撑的范围：交叉验证不是证明，"我检查了三个例子"不是定理。"""


@dataclass(frozen=True)
class RoleBrief:
    """一个角色的手写部分。事实部分一律现算，不放在这里。"""

    duty: str
    #: 边界：这个角色不许做什么。每条都对应仓库里一条真实约束（多为禁改区或结构约束）。
    boundary: tuple[str, ...]
    #: 政策：这次运行里可开关的取舍（没有就空着 —— 空段不会出现在提示词里）。
    policy: tuple[str, ...] = ()
    #: 这个角色最容易犯的那个错（写出来，因为它是最贵的那个）。
    signature_error: str = ""
    #: 交付物的一句话（写稿/立案之类的角色需要）。
    deliverable: str = ""


ROLE_BRIEFS: dict[str, RoleBrief] = {
    "A": RoleBrief(
        duty="文献检索：把搜索请求变成已登记的文献行，并如实报告每一次失败",
        boundary=(
            "检索口径（查询编排、精筛、候选打分）在禁改区：你只能调用它，不许绕过或改写它。",
            "你不抽概念、不建关系（那是 B 的活）；检索完请 B 整理。",
            "候选被你判为不相关时，只能说这一条没进结果，不许说这篇文献不存在。",
            "下载失败必须如实写进请求行的错误字段；不许把失败当成功，也不许静默重试到超预算。",
        ),
        policy=(
            "继续搜还是收手由预算与命中率决定：预算耗尽时必须收手并在结论里写明预算读数。",
        ),
        signature_error="把一条候选被丢掉说成这篇文献不存在。",
        deliverable="search_requests 里每一条请求的终局（outcome）与 result_lit_ids。",
    ),
    "B": RoleBrief(
        duty="文献整理：把新到的文献变成概念行与关系行，每条关系都带可回验的引文",
        boundary=(
            "没有逐字引文支撑的关系不许产出（判据会逐字回验，编造会被剔除并留痕）。",
            "回退抽取器（框架在没有模型时替你选的规则抽取器）必须拒抽：它一旦被当成正常抽取，"
            "产出的概念会看起来像模型给的，而实际上没有任何语义判断发生过。",
            "缺模型、缺正文、抽取失败都要如实落到 processed 与错误字段上，不许假装整理过。",
            "同一篇文献不要重复抽取；已有关系的重复判定交给判重口径，不要自己另立标准。",
        ),
        policy=(
            "一次抽取的产出有上限（概念与关系各不超过提示词约定的条数）："
            "超过上限时优先保留证据更硬的那几条，并在结论里说明被截掉了什么。",
        ),
        signature_error="把规则抽取器的产出当成模型抽取的产出。",
        deliverable="concepts 与 relations 行；每条关系带 quote / page_range / quote_verified。",
    ),
    "C": RoleBrief(
        duty="关系分析：用确定性代码算图与计数，只在排序与措辞这两件事上动用模型",
        boundary=(
            "你是只读角色：不许写任何数据，也不许直接向别人发请求（你的可召唤边是空的）。",
            "计数、索引、图搜索、路径枚举、去重、评分、溯源全部由代码算，你不许用模型重算它们。",
            "模型的输出只能给一个排列或一个判断（值不值得研究），不许改分数、不许删路径。",
            "钩子没接线或返回坏结果时必须回退到确定性顺序，并在结论里写明这次排序的来源。",
        ),
        policy=(
            "两处钩子各只许做一件事：路径排序只给 index 排列；缺口判断只给 worth 与 confidence。",
        ),
        signature_error="把模型给的排序当成算出来的评分。",
        deliverable="图的形状读数、结构重复、候选研究缺口（由 D 或编排层决定要不要变成请求）。",
    ),
    "D": RoleBrief(
        duty="研究循环：把一个研究方向收敛成一个有证据支撑的结论，或如实说证据不足",
        boundary=(
            "只许使用证据包里出现过的关系 id 与引文，不许引入包外的事实。",
            "置信度只能等于或低于确定性口径算出的那一档。",
            "证据不足时正确结论是低置信度与缺口清单，不是把话写圆。",
            "缺口要变成具体的检索请求（交给 A）或实验请求（交给 E），不要只写在报告里。",
        ),
        policy=(
            "进入下一层验证的门槛由确定性判据给（度数、通过回验的关系条数、是否成对矛盾）："
            "门槛没到就不下钻，先补证据。",
            "你的结论里如果有下游（E 做实验、G 写稿、H 审校）必须遵守的约束，"
            "用 message 把它发给对方，而不是只写在报告里 —— 报告不会自己走到他们手上。",
        ),
        signature_error="把没有证据写成没有争议。",
        deliverable="analysis_reports 里的分析、结论、建议三层，以及它可以交出去的缺口清单。",
    ),
    "E": RoleBrief(
        duty="数值实验与形式化验证：把一条断言变成可复现的实验或可检查的形式化代码",
        boundary=(
            "数值结果的判读必须是确定性的：脚本输出的数字由代码判，不许过模型。",
            "脚本自报的 proof 级证据一律降级为 cross_check：让被判定的对象自己当判官是最容易被绕过的地方。",
            "实验失败、检查器不存在、代码跑不过，都要如实落 failed 或 unknown，不许补写结论。",
            "引文无法核实的关系要退回 B；发现反例时把结论交回 D，不要自己改别人的结论。",
        ),
        policy=(
            "形式化只认检查器真的说过的话：桥接层读不到检查器就说读不到，不许用模型的话代替。",
        ),
        signature_error="把跑不过的代码块当成通过。",
        deliverable="experiments 行与它们的证据字段（数值、检查器输出、复现命令）。",
    ),
    "F": RoleBrief(
        duty="多轮难题攻坚：在预算内一轮一轮逼近平息或反例，并如实报告进展",
        boundary=(
            "终止条件是预算与轮次，不是感觉：预算耗尽必须停手并如实写未推进。",
            "不许把没推进写成已完成；台账里的每一步都要能看出这一轮做了什么、为什么停。",
            "不许自己改结论或证据：你的产出是攻击计划与进展，结论由 D 或人收口。",
            "需要 C/D/E 的推理而框架没接线时，如实写未接线，不许编一个中间结果顶上。",
        ),
        policy=(
            "每一轮先挑一个可判定的子目标，做完就落台账；子目标不可判定时先把它拆小。",
        ),
        signature_error="把无变化写成有进展。",
        deliverable="attack_plans 行的子目标进展与终止原因。",
    ),
    "G": RoleBrief(
        duty="论文撰写：把 D/F/E 的结论汇编成可审校的稿件，附带每条断言的来路",
        boundary=(
            "你不做语义判定：引文是否逐字可达、断言强度是否超过引文，都由判据与 H 判，不许自己认定通过。",
            "交叉验证类结论必须带框架约定的免责声明常量（逐字符一致），手写近义句会被判不符。",
            "没有证据的判断不要写进稿件；确实要写就写进待办或缺口，而不是写成结论。",
            "发现证据不足时要回去找 D/E/F 要，而不是把话说软。",
        ),
        deliverable="documents 里的稿件与每条断言的来路字段。",
    ),
    "H": RoleBrief(
        duty="审校（只读）：只判稿件有没有把自己说清楚，不判数学对不对",
        boundary=(
            "你是只读角色：不许改任何数据、不许改稿；发现问题只能落 findings 并请 G 修订。",
            "你不判数学：数学错误不在你的职责里，把不确定的话写成确定的话才是你要抓的。",
            "你得出的每条结论都要落到 findings（带位置与理由），不许只在回复里说。",
            "审校不通过时要给出可操作的修订点，而不是笼统地说质量不行。",
        ),
        deliverable="review_findings 行与一次审校的裁决（哪些问题拦住交付）。",
    ),
    "M": RoleBrief(
        duty="主控：决定派谁做什么、按什么顺序做，并把结果收敛成一份可读的交付",
        boundary=(
            "你不产出领域对象：文献、概念、关系、实验、稿件一律由角色产出，你只派活与收敛。",
            "你不可被召唤（没有召唤主控这条边）；你的行动一律以你自己为发起方落台账。",
            "派活必须走能力表与策略：越权的边、超深度的链、超预算的轮次都会被拒，被拒时如实报告。",
            "你不许替角色下结论；角色说证据不足时，你要么补派活，要么把不足如实写进交付。",
        ),
        policy=(
            "先窄后宽：优先派能一次给出可判定结果的角色；每一轮结束后看一眼台账再决定下一步。",
            "步数有限：现状侦察最多做一次（conductor.state 与 conductor.ledger 二选一），"
            "随后必须派活或留言。用只读调用填满步数是这次运行最常见的失败形态。",
            "被拒绝了就换一条路（换伙伴、换动作、或把缺口如实写进交付），而不是停在那里；"
            "已经拿到足够信息却又推不动时，直接收工并说明卡在哪。",
            "交付里凡是「下游必须遵守的约束」都要有一条留言转达给相关伙伴："
            "结论写在报告里不会自己走到他手上。",
        ),
        signature_error="把派活本身当成结论。",
        deliverable="一份交付说明：做了什么、谁做的、哪些地方证据不足、还剩什么没做。",
    ),
}


def _specs_for(role: str, registry: Any) -> list[Any]:
    """该角色工具面上的工具（按名字排序）。

    注册表是必填的，没有默认值：一个"随手建一个空注册表"的默认值会让提示词
    少掉一部分工具，而少掉的那部分在输出里看不出来（实测：不带 workspace_root 的
    注册表里 D 只有 25 件工具，带了是 32 件）。提示词必须描述真正会执行的那个工具面。
    """
    if registry is None:
        raise ValueError(
            "生成提示词必须给 registry：它要与真正执行调用的那个注册表是同一个，"
            "否则提示词会少报或多报工具而没有任何读数会告诉你"
        )
    return sorted(registry.for_role(role), key=lambda s: s.name)


def _required_of(spec: Any) -> tuple[str, ...]:
    params = getattr(spec, "params", None) or {}
    req = params.get("required") if isinstance(params, Mapping) else None
    return tuple(str(x) for x in (req or ()))


def _props_of(spec: Any) -> tuple[str, ...]:
    """参数表里允许出现的键（封闭集合：多传一个键就会被拒）。"""
    params = getattr(spec, "params", None) or {}
    props = params.get("properties") if isinstance(params, Mapping) else None
    return tuple(sorted(str(k) for k in (props or {})))


def _params_hint(spec: Any) -> str:
    """参数说明：必填哪些、还能用哪些、以及"不许自己发明键"。

    为什么要把允许的键全列出来（而不是只列必填）：真机第一次跑就出了这件事 ——
    模型给 `A.run_once`（一个无参动作）传了 `query` 与 `max_results`，
    拿到一次 `invalid_params`。它不是不听话，而是提示词只说了必填，
    没说参数的键是封闭集合。
    """
    req = _required_of(spec)
    props = _props_of(spec)
    optional = tuple(k for k in props if k not in req)
    bits = ["必填 " + ("、".join(req) if req else "无")]
    if optional:
        bits.append("可选 " + "、".join(optional))
    if not props:
        bits.append("不许传任何参数")
    return "（" + "；".join(bits) + "）"


def tools_lines(role: str, registry: Any) -> list[str]:
    """工具面逐条：名字 + 摘要 + 参数（必填与可选的键）+ 副作用。"""
    out: list[str] = []
    for spec in _specs_for(role, registry):
        side = getattr(spec, "side_effect", "none")
        out.append(f"- {spec.name}：{spec.summary}{_params_hint(spec)}；副作用 {side}")
    return out


def actions_lines(role: str) -> list[str]:
    """动作表逐条：动作名 + 摘要 + 参数 + 产出 + 副作用。"""
    out: list[str] = []
    for spec in C.actions_for(role):
        returns = f"；产出：{spec.returns}" if spec.returns else ""
        out.append(f"- {spec.action}：{spec.summary}{_params_hint(spec)}；"
                   f"副作用 {spec.side_effect}{returns}")
    return out


def _duty_of(role: str) -> str:
    brief = ROLE_BRIEFS.get(role)
    return brief.duty if brief else "（未登记职责）"


def partners_out(role: str) -> tuple[str, ...]:
    """这个角色能唤起谁（`ALLOWED_EDGES` 的出边，排序后）。"""
    return tuple(sorted(C.ALLOWED_EDGES.get(role, frozenset())))


def partners_in(role: str) -> tuple[str, ...]:
    """谁能唤起这个角色（边表的入边；主控永远不在里面）。"""
    return tuple(sorted(r for r, to in C.ALLOWED_EDGES.items() if role in to))


def partners_lines(role: str, availability: Mapping[str, str] | None = None) -> list[str]:
    """伙伴表：出边逐个带职责、动作与参数，加上入边、接线态与不可召唤的说明。

    这是"让智能体知道自己能跟谁协作"的唯一实现 —— 全部现算，
    所以有人给边表加一条边时，两边角色的提示词都会跟着变（有测试守着）。

    `availability` 给的是"这个伙伴现在真的能被唤起吗"（`host.wiring_status` 的读数）。
    为什么必须写进提示词：真机第一次跑，M 派了 A，而 A 恰恰是当场没接线的那个角色
    （缺 providers）—— 模型不可能知道这件事，除非有人告诉它。
    """
    out: list[str] = []
    outs = partners_out(role)
    if outs:
        out.append("你可以唤起这些伙伴（用 summon 形状），他们的职责与可调用动作如下"
                   "（参数只许用括号里列出的键）：")
        for other in outs:
            acts = "；".join(f"{a.action}{_params_hint(a)}" for a in C.actions_for(other))
            mark = ""
            if availability is not None:
                state = str(availability.get(other) or "unknown")
                if state != "wired":
                    mark = f"（现在没接线：{state}）"
            out.append(f"- {other}：{_duty_of(other)}；可调用动作：{acts or '（没有动作）'}{mark}")
    else:
        out.append("你没有任何可以唤起的伙伴（你的边是空的）——这是设计，不是遗漏："
                   "你的产出由别人来收取。")
    ins = partners_in(role)
    if ins:
        out.append("这些伙伴可以唤起你：" + "、".join(ins)
                   + "。他们给你的任务会出现在下面的任务框里，参数就是他们给的原文。")
    if role in C.NON_SUMMONABLE:
        out.append("你不可以被任何人唤起（不可召唤名单里有你）：你的行动一律由你自己发起。")
    return out


def _numbered_sections(prefix: str, lines: Sequence[str], base_order: int) -> list[Section]:
    """把一组行拆成多段（每行一段），顺序 = base_order + 序号 * 10。"""
    return [
        Section(f"{prefix}_{i:02d}", base_order + i * 10, text=line)
        for i, line in enumerate(lines)
    ]


def role_prompt_registry(role: str, *, registry: Any = None,
                        task: str = "", summoned_by: str = "",
                        task_id: str = "", depth: int = 1,
                        budget_left: str = "", inbox: str = "",
                        workspace_root: str = "", extra_facts: Mapping[str, str] | None = None,
                        availability: Mapping[str, str] | None = None,
                        ) -> PromptRegistry:
    """按角色装配一份提示词注册表（段 + 变量），供 `render` 或审计使用。

    为什么每次调用都新建一个注册表：段文本里的 `{{task}}` 这类事实是这一次运行的东西，
    而注册表的变量是"这次装配"的输入 —— 混用一个全局注册表会让两次运行互相看见对方的任务。

    `registry` 是必填的（默认 None 只是为了给出可读的错误，不是"可以不给"）：
    它必须与真正执行工具调用的那个注册表是同一个。
    """
    if role not in ROLE_BRIEFS:
        raise ValueError(f"未登记的角色 {role!r}（已知 {tuple(ROLE_BRIEFS)}）")
    brief = ROLE_BRIEFS[role]
    reg = PromptRegistry()

    facts: dict[str, str] = {
        "role": role,
        "duty": brief.duty,
        "task": task or "（这一次没有给出任务描述）",
        "summoned_by": summoned_by or "（顶层发起）",
        "task_id": task_id or "（尚未落台账）",
        "depth": str(depth),
        "budget_left": budget_left or "（没有设置预算上限）",
        "inbox": inbox or "（没有收到留言）",
        "workspace_root": workspace_root or "（未指定）",
        "prompt_version": PROMPT_VERSION,
    }
    for key, value in (extra_facts or {}).items():
        facts[str(key)] = str(value)
    for name, value in facts.items():
        reg.variable(name, value)

    reg.section(Section("AGENT_IDENTITY", SECTION_ORDERS["AGENT_IDENTITY"],
                        "你是 {{role}} 号角色，职责是：{{duty}}。\n"
                        "你在一套多智能体协同框架里工作：你只做自己职责内的事，"
                        "其余的交给伙伴（见下面的伙伴表）。"
                        "你这次是被 {{summoned_by}} 唤起/发起的，台账号为 {{task_id}}，"
                        "在召唤链上的深度是 {{depth}}。"))
    reg.section(Section("ROLE_BOUNDARY", SECTION_ORDERS["ROLE_BOUNDARY"],
                        "边界（这些是硬约束，越过它们做的事一律不算数）：\n"
                        + "\n".join(f"- {x}" for x in brief.boundary)))
    if brief.policy:
        reg.section(Section("ROLE_POLICY", SECTION_ORDERS["ROLE_POLICY"],
                            "这次运行的政策：\n" + "\n".join(f"- {x}" for x in brief.policy)))
    if brief.signature_error:
        reg.section(Section("SIGNATURE_ERROR", SECTION_ORDERS["ROLE_BOUNDARY"] + 50,
                            "你最需要防的那个错："
                            + brief.signature_error
                            + " 它在这个框架里被单独登记过，因为它最难自己发现。"))
    if brief.deliverable:
        reg.section(Section("DELIVERABLE", SECTION_ORDERS["ROLE_BOUNDARY"] + 60,
                            "你这一岗的交付物：" + brief.deliverable))

    for i, section in enumerate(_numbered_sections("TOOL", tools_lines(role, registry),
                                                  SECTION_ORDERS["TOOL_GUIDANCE_BASE"])):
        reg.section(section)
        del i
    reg.section(Section("EVIDENCE_CONTRACT", SECTION_ORDERS["EVIDENCE_CONTRACT"],
                        EVIDENCE_CONTRACT))

    acts = actions_lines(role)
    reg.section(Section("OUTPUT_CONTRACT", SECTION_ORDERS["OUTPUT_CONTRACT"],
                        ("你对外可被调用的动作（这些是伙伴唤起你时用的名字）：\n"
                         + "\n".join(acts)) if acts else
                        "你没有对外可被调用的动作（你的产出由框架直接读）。"))
    reg.section(Section("THREE_STATE", SECTION_ORDERS["THREE_STATE"],
                        "三态词表（框架用这几个码表示「没查成」，它们不等于「没有这个问题」）：\n"
                        + "、".join(J.JUDGE_PROBLEMS)
                        + "。拿到这些码时，正确做法是走确定性回退并在结论里写明来源，"
                          "不许折成「没问题」，也不许折成「不存在」。"))
    reg.section(Section("TASK_FRAME", SECTION_ORDERS["TASK_FRAME"],
                        "这一次的任务：\n{{task}}\n\n"
                        "你收到的留言（可能为空）：\n{{inbox}}\n\n"
                        "剩余预算：{{budget_left}}"))
    partners = partners_lines(role, availability)
    reg.section(Section("PARTNERS", SECTION_ORDERS["PARTNERS"],
                        "可协作的伙伴：\n" + "\n".join(partners)))
    if availability is not None:
        unusable = sorted(k for k, v in availability.items() if str(v) != "wired")
        reg.section(Section("PARTNER_AVAILABILITY", SECTION_ORDERS["PARTNERS"] + 20,
                            "现在的接线态（这一栏是事实，不是建议）：\n"
                            + ("\n".join(f"- {k}：{availability[k]}" for k in sorted(availability))
                               or "（没有读数）")
                            + ("\n派活前先看这一栏：没接线的伙伴派了也会被拒（refused/not_wired），"
                               "不如改派能做的，或如实说明缺什么。"
                               if unusable else "")))
    reg.section(Section("AGENT_TOOLS_SDK", SECTION_ORDERS["AGENT_TOOLS_SDK"], LOOP_PROTOCOL))
    reg.section(Section("WORKSPACE_FACTS", SECTION_ORDERS["WORKSPACE_FACTS"],
                        "工作区事实（现算，不是记忆）：\n"
                        + f"- 工作区根目录：{{{{workspace_root}}}}\n"
                        + f"- 数据结构版本：{S.SCHEMA_VERSION}；表："
                        + "、".join(S.TABLES)
                        + f"\n- 提示词版本：{{{{prompt_version}}}}"))
    return reg


def system_prompt(role: str, **kw: Any) -> str:
    """渲染某个角色这一次的 system prompt。"""
    return role_prompt_registry(role, **kw).render(Scope(role=role))


def prompt_audit(role: str, **kw: Any) -> dict[str, Any]:
    """这次提示词的审计读数：版本、哈希、长度、段名、变量名。

    每次模型调用都要把这份读数落档 —— 没有它，
    "这次结论是哪个版本的提示词加上哪个模型的产物"就无法事后回答。
    """
    reg = role_prompt_registry(role, **kw)
    assembly = reg.assemble(Scope(role=role))
    text = assembly.render()
    return {
        "prompt_version": PROMPT_VERSION,
        "role": role,
        "prompt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "prompt_chars": len(text),
        "sections": list(assembly.names),
        "variables": sorted(assembly.variables),
    }


def roles_covered() -> tuple[str, ...]:
    """本模块已登记职责的角色（与 `schema.ROLES` + 主控对账用）。"""
    return tuple(sorted(ROLE_BRIEFS))


def missing_roles() -> tuple[str, ...]:
    """`schema.ROLES`（含主控）里还没有手写职责的角色 —— 判据用，必须是空的。"""
    want = set(S.ROLES) | {S.CONDUCTOR_ROLE}
    return tuple(sorted(want - set(ROLE_BRIEFS)))


def _selftest_registry() -> Any:
    """自检用的注册表（不带 workspace_root：于是没有 fs 工具，这是如实的工具面）。"""
    from .tools import build_registry

    return build_registry().registry


def selftest() -> int:
    """自检：每个角色都有一份非空提示词，且里面真的有它的工具与伙伴。"""
    problems: list[str] = []
    registry = _selftest_registry()
    missing = missing_roles()
    if missing:
        problems.append(f"这些角色没有手写职责：{missing}")

    for role in roles_covered():
        text = system_prompt(role, registry=registry, task="自检任务", workspace_root="D:/x")
        if not text.strip():
            problems.append(f"{role} 的提示词是空的")
        if "{{" in text:
            # 只查左花括号：循环协议里的 JSON 例子天然会以 `}}` 收尾（嵌套对象），
            # 而"没被插值的模板组"一定表现为一个孤立的 `{{`。
            problems.append(f"{role} 的提示词里还有没被插值的模板组（出现了 {{{{）")
        for spec in _specs_for(role, registry):
            if spec.name not in text:
                problems.append(f"{role} 的提示词里没有它的工具 {spec.name}")
        for other in partners_out(role):
            if f"- {other}：" not in text:
                problems.append(f"{role} 的提示词里没有伙伴 {other}")
        if role in C.NON_SUMMONABLE and "不可以被任何人唤起" not in text:
            problems.append(f"{role} 是不可召唤的，但提示词没写")

    # 负控：一个没登记的角色必须当场拒绝（不许给一份通用提示词糊过去）
    try:
        system_prompt("Z", registry=registry)
        problems.append("未登记的角色没有抛")
    except ValueError:
        pass  # 负控期望它抛
    # 负控：没给注册表必须当场拒绝（不许悄悄用一个少了几件工具的注册表）
    try:
        system_prompt("A")
        problems.append("没给注册表却没有抛")
    except ValueError:
        pass  # 负控期望它抛
    # 负控：缺任务时不许留下空模板组（应替换成显式文案）
    if "{{task}}" in system_prompt("A", registry=registry):
        problems.append("缺任务时模板组没有被替换")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print(f"SELF-CHECK DONE（{len(roles_covered())} 个角色各有非空提示词；工具与伙伴逐条在文内）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())

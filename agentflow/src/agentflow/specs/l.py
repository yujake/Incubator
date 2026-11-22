# -*- coding: utf-8 -*-
"""角色 L（Lean 形式化者）的声明：动作表 + 边 + 写集 + 职责与门面。

## 协作面：B 是唯一入口，L 只派 C

当前唯一口径（这一行是权限面，别只改一处）：

- 入边只有 `B → L`；出边只有 `L → C`。除 B 之外没有任何角色能派 L，L 也只派 C；
- 用户那条"指定单条执行"是「入口不是边」：`run-agent L` 直接起，不经过
  `ALLOWED_EDGES` —— 所以它不进下面这张表，也「不许为它加边」（加边就等于把它
  挂成流水线的一环）。

四条落点各在哪一格：

1. `B → L` 唯一入口：`specs/b.py::SPEC.edges` 里有 `L`，本文件 `summonable=True`；
   其余角色（A / C / D / E / F / G / H / M / V）的出边里都没有 L（`capabilities.ALLOWED_EDGES`
   逐角色现算，判据见 `tests/test_l_collab_surface_is_exactly_this.py`）；
2. `L → C` 一条出边：本文件 `edges=('C',)`，用途写进 `SPEC.brief.policy`（梳理证明链）；
3. 消费 B 的定理证明库：`formalize` 用 `statement_id` 从 `statements` 取
   `statement_full` + `proof_text`，取不到就受控拒绝（`statement_not_found`，不写盘、
   不起检查器），并把 `b_library`（编号 / 标题 / 证明字数 / 依赖链步数）写进返回值与 `coverage`；
4. 向 B 汇报困难：`formalize` 判出"失败或对不上"时按受控形态投进 B 的收件箱
   （`agent_l/report.py` + `proofreport.py`）；B 改证明后重新过 V 的签（`B → V` 既有边），
   严重时 B 通知 D 开展研究（`specs/b.py` 新增的 `B → D` 边）。

Lean 关着时这条协作面整条看不见：L 不在角色表里、`formal.*` 不装配、
`B → L` 与 `L → C` 都被 `policy` 判成 `forbidden_edge`（理由串点名 `lean_off`），
判据见 `tests/test_l_is_isolated_when_lean_is_off.py` 与
`tests/test_l_collab_surface_is_exactly_this.py`。

## 动作：三格（`check_formal` / `formalize` / `record`）

L 只搬形式化这一路（E 的动作表里那一格），并把它拆成三个落点各不相同的动作：

1. `check_formal` —— 与 E 的同名动作逐字同义：把源码交给 `verify.check_formal`
   （桥接层的唯一实现）真跑一次，按检查器原话给出判定。L 只是多一道前置自检
   （见 `agent_l` 的 docstring），所以两边口径不会分家；
2. `formalize` —— 写形式化那一格：把一条命题写成 Lean 源码、落到
   `code/formal/<声明名>.lean`、再交给同一个桥接层真跑，结论三态
   （`verified` / `failed` / `unknown`）。E 那边这一格是"先 `fs.write` 再
   `run_experiment(method=formal)`"两步拼出来的（E 的 policy 逐字要求把内联源码
   落进工作区）；L 把它收成一个动作，是因为两步拼装的路径在"写没写盘"这件事上
   没有任何机器判据。
3. `record` —— 把一次形式化检查登记成 `experiments` 表的一行（`method="formal"`）。
   L 不写 experiments ⇒ verified 进不了证据链。这一格只登记形式化实验行，它不动
   `statements`：形式化 ≠ 审过，命题升档仍然要 V 的那一签。

副作用与外部性两根轴都如实声明：`formalize` 写本地文件 + 起检查器子进程
（`write_local` + `external="exec"`），`check_formal` 只读 + 起子进程
（`read` + `external="exec"`），`record` 写一行 `experiments` + 起子进程
（`write_local` + `external="exec"`）。这与 E 的同名动作同一口径（长理由在 `specs/e.py`）。

## 写集：只有 `experiments` 一格

L 的产出是三样：盘上的 `.lean`、检查器原话、以及 `record` 落下的那一行实验。
前两样不是表行，第三样是 —— 所以 `write_set=frozenset({"experiments"})`。
刻意不含 `statements`：那一格是"命题升档"的位置，只有 V 的签字与 F/B 的登记能碰。
写集里没有它，"L 绕过 V 签"在结构上不可能（不是靠纪律）。

## 忠实复述是机器读数，不是一句自述

`formalize` 的 `claim` 是一段自由文本，于是"它形式化的到底是不是 B 登记的那一条"
需要机器判据（`check_formal` 不涉及这一点）：

1. 参数多一格 `statement_id`（被形式化的那一条在 `statements` 表里的编号）。它是
   可选而不是必填 —— 工具面 `formal.formalize` 还不收它，声明成必填会让每一次真实
   调用都缺一格。不给编号时的唯一合法来源是"claim 与台账某一行正文逐字相同且唯一"
   （实现在 `agent_l/formalize.py`，读数里 `statement_source` 说明这一趟用的是哪一条来源）；
2. 摘要里写进"源码怎么标落点"的约定（`-- step <k>` / `-- assume <文本>`）：那是
   模型唯一看得见这条约定的地方（提示词只列必填参数，见
   `agent_prompts._params_hint`），所以它必须随动作声明一起走；
3. 返回值多出忠实复述八格（`statement_id` / `statement_source` / `coverage` /
   `faithfulness` / `steps_path` / `refused` / `checker_status` / `checker_reason`）。
   其中 `checker_status` 与 `status` 是刻意分开的两格：前者是检查器原话，
   后者是叠加了逐步对照之后的综合结论 —— "机器核过了"不等于"这一趟算数"。

判据在 `tests/test_l_faithfulness_is_measurable.py`（六条）。

## 本文件在 `.noai-paths` 里的状态

本文件已登记进 `.noai-paths`（`[category: auth-audit]`）：它有边（`B → L` 那条
入边的落点之一是 `summonable`）、有写集（`experiments`）、有可召唤性 —— 那三样正是
清单里其余 `specs/<角色>.py` 被登记的同一条理由（改它等于改权限面）。两处清单
（`.noai-paths` 与 `AGENTS.md`）必须逐条一致，
一致性由 `python scripts/noai_gate.py --check-consistency` 判（退出码 0 = 一致）。
"""
from __future__ import annotations

from typing import Any

from .. import schema as S
from ..agentspec import (
    _ARR_S,
    _B,
    _I,
    _N,
    _S,
    ActionSpec,
    AgentBrief,
    AgentSpec,
    BuilderDeps,
    _obj,
)

#: 本角色的动作表：三格都只有 Lean 形式化这一路。
ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        "L", "formalize",
        "把一条命题写成 Lean 源码、落盘到 code/formal/（写函数返回盘上路径与 sha256），"
        "再交给检查器真跑一次。结论三态：verified / failed / unknown ——"
        "unknown 一定带原因（自检不是 usable / 检查器不存在 / 超时），不许折进另外两档。"
        "忠实复述是可核的读数，不是一句自述：被形式化的那一条由 statement_id 钉住"
        "（不给编号时只认「claim 与台账正文逐字相同且唯一」这一种来源，转述过的 claim 认不出来），"
        "源码里每一步用独占一行的 `-- step <k>` 标出落点、补的假设用 `-- assume <文本>` 标出，"
        "逐步对照写进 code/formal/<名字>.steps.jsonl；返回的 coverage 给出"
        "steps_total / steps_mapped / unmapped / sorry_lines。漏一步或有 sorry ⇒ 结论只能是 unknown。"
        "有一条定理好几份证明时，必须用 proof_no 指明验的是哪一份（第 4 位是二维的：每条证明"
        "一格；#p1 落 code/formal/<名字>.lean，其余落 code/formal/<名字>__p<n>.lean）："
        "号不在册 ⇒ proof_path_not_found；有好几份而不给号 ⇒ proof_path_unspecified（一个字节都不写）。"
        "path_source 记这个号是谁选的（B 指定 / 照 C 的建议 / L 自己决定），"
        "空 = 没交代 —— 不许替调用方编一个来源",
        # 参数与工具面 `formal.formalize` 同名的那些逐名相同（两层对账要求同名同类型）。
        # 刻意不叫 `name`：`ToolRegistry.call` 的第一个形参就叫 `name`，
        # 工具层再声明一个同名的会永远无法按名传入（`verify_tools.check_formal`
        # 的 `checker_name` 是同一个理由，那边逐字登记过）。L 从一开始就叫
        # `declaration_name`，于是动作面与工具面没有"名字对不上"的接缝要登记。
        #
        # `statement_id` 是动作面独有的一格（把"忠实复述 B 的证明链路"从文字义务
        # 变成机器读数）：它今天只在动作面上有，工具面 `formal.formalize` 还没收它，
        # 所以它按"动作面独有参数"登记在
        # `capabilities._KNOWN_ACTION_ONLY_PARAMS`（导入期第 [9] 条要求有出处）。
        # 不写进 `required`：工具面还没有它，声明成必填会让每一次真实调用都缺一格。
        _obj({"claim": _S, "source": _S, "declaration_name": _S, "statement_id": _S,
              # 路径两格：`proof_no` 是这一趟验的第几份证明（1 = canonical，2 起在同行的
              # `proofs` 清单里）；`path_source` 记「这个号是谁选的」（B 指定 / 照 C 的建议 /
              # L 自己决定）。两格在工具面同名同类型（两层对账逐名比），
              # 所以不登记进 `capabilities._KNOWN_ACTION_ONLY_PARAMS`。
              "proof_no": {**_I, "minimum": 1},
              "path_source": {"type": "string", "enum": ["B", "C", "L"]},
              "imports": _ARR_S, "timeout_sec": _N}, ("claim", "source")),
        "dict（status / path / sha256 / claim / reason / detail / verifier_output / exit_code / problems "
        "/ statement_id / statement_source / coverage / faithfulness / steps_path / refused "
        "/ checker_status / checker_reason / proof_no / proof_sha256 / path_id / path_source）",
        side_effect="write_local", handler_name="formalize",
        external="exec",
    ),
    ActionSpec(
        "L", "check_formal",
        "把一段 Lean 源码（`source`）或工作区里的 .lean 文件（`script_path`）交给检查器真跑一次。"
        "前置自检不是 usable 时如实回 unknown 并给原因：不起检查器、不抛栈。"
        "查了没通过（compile_error / uses_sorry / extra_axioms / decl_mismatch）与没查成是两件事",
        _obj({"claim": _S,
              "script_path": {"type": "string",
                              "description": "工作区里的 .lean 文件（与 source 二选一）"},
              "source": {"type": "string",
                         "description": "Lean 源码全文（与 script_path 二选一）"},
              "declaration_name": _S,
              "imports": _ARR_S, "timeout_sec": _N}, ("claim",)),
        "dict（checked / verified / reason / detail / verifier_output / status / exit_code）",
        side_effect="read", handler_name="check_formal",
        external="exec",
    ),
    ActionSpec(
        "L", "record",
        "把一次形式化检查登记成 `experiments` 表的一行（method=\"formal\"）：按 statement_id "
        "读台账里那条命题的正文，再对 code_path 的 .lean 现跑一次检查器，把现跑得到的 "
        "status / verified / checker / output_sha256 写进那一行。调用方给的读数只用于对账："
        "与现跑不一致 ⇒ 受控拒绝 reading_mismatch，一行都不写。它不动 statements："
        "形式化 ≠ 审过，命题升档仍然要 V 的那一签。proof_no 记这一行绑的是第几份证明"
        "（号不在册 / 多路径未给号 ⇒ 受控拒绝，一行都不写）、path_id 记 C 给那条路径的显示名、"
        "proof_sha256 是这一份正文的指纹（读侧拿它与现行正文比，不符就是「验过、过期了」）、"
        "path_source 记这个号是谁选的。只收 `.lean`（`code_path` 不是 .lean ⇒ 受控拒绝 "
        "`artifact_not_lean`）；数值脚本不归你，走 E 的 `run_experiment`",
        # 参数与工具面 `formal.record` 逐名同类型（两层对账第 [9] 条逐个比）。
        # `status` / `verified` 是"调用方看到的读数"，只用于对账（不采信）：
        # 采信它们等于让 `evidence_kind="proof"` 变成可随手搬运的标签。
        _obj({"statement_id": _S, "code_path": _S, "declaration_name": _S,
              # 路径三格（与 `formalize` 同一套口径，另一处落点）：这一行绑的是第几份
              # 证明、C 给这条路径的显示名（`p<路径号>g<组号>`，只做标记、不当键）、
              # 以及这个号是谁选的。
              "proof_no": {**_I, "minimum": 1}, "path_id": _S,
              "path_source": {"type": "string", "enum": ["B", "C", "L"]},
              "imports": _ARR_S, "timeout_sec": _N, "status": _S, "verified": _B,
              "checker": _S, "verifier_output": _S, "exit_code": _I,
              "for_question_id": _S, "notes": _S}, ("statement_id", "code_path")),
        "dict（recorded / experiment_id / statement_id / status / verified / checker / "
        "output_sha256 / evidence_kind / statement_evidence_kind_before / "
        "statement_evidence_kind_after / verification_required / detail / reason / "
        "proof_no / path_id / proof_sha256 / path_source）",
        side_effect="write_local", handler_name="record",
        external="exec",
    ),
)


def _build(d: BuilderDeps) -> Any:
    """构造 L（需要工作区根：它把 .lean 写到工作区、并让检查器在那里跑）。"""
    from ..agent_l import AgentL

    return AgentL(d.store, config=dict(d.config), llm=d.llm,
                  workspace_root=d.workspace_root, actor=d.actor)


#: 本角色的声明。
SPEC = AgentSpec(
    role="L",
    brief=AgentBrief(
        duty=("Lean 形式化：把 B 登记的那条命题与它的证明链路**忠实**搬进 Lean 源码，"
              "交给检查器真跑，并如实报 verified / failed / unknown"),
        boundary=(
            "只形式化 B 已登记的那一条：假设、量词、定义、以及命题的名字都不许改写。"
            "被改写过的定理即使机器核过，也不是原文那条。",
            "忠实复述是逐条义务：B 的 proof_text 里每一步都要在 Lean 源码里找得到一个落点"
            "（一行、一个策略、或一个被显式命名的中间引理）；接不上的那一步如实记成缺口，"
            "不许用 sorry / admit 把它堵住（含 sorry 的文件会正常编译通过，那不是证明）。",
            "检查器原话（verifier_output）与真实退出码（exit_code）是形式化证据的唯一凭据："
            "没跑成就是没跑成，退出码绝不用 0 冒充跑过。",
            "不许自己动台账里的命题与证明：B 的登记是唯一来源；发现命题本身站不住，"
            "交回 B（登记）或 D（方向），不要自己改别人的结论。",
        ),
        policy=(
            "形式化只认检查器真的说过的话：桥接层读不到检查器就说读不到，不许用模型的话代替。",
            # 这一格不写"先看 TOOLCHAIN_FACTS 第一行、说已关闭时这条路不适用"：那一档
            # 不可达 —— 关着时本角色不存在（`leanscope.require_visible` 抛 RoleHidden），
            # 提示词根本渲染不出来，于是"关掉时怎么办"只对着一个永远读不到它的读者说话。
            # 开关这一档只剩"开着"这一种存在形态，下面每条都以它为前提。
            "这一岗只有「开着」这一种存在形态（关着时 L 不存在，不是「跑不动」）：下面每一条都以"
            "这个前提写，你不必再判开关该走哪条分支；`TOOLCHAIN_FACTS` 第一行仍要读，那是这一趟的读数。",
            "任何 Lean 调用之前先过自检（`leantoolchain` 的**五步**：解析 / 版本 / 正样例 / 反控 / Mathlib 与图论）。"
            "自检不是 usable 时，这一趟的全部形式化结论记 unknown 并把原因写清：不起检查器、"
            "不抛栈、不连撞同一条错误 —— 同一条失败只报一行，然后收手。"
            # 图论库可用时 import 走具体那一行，别拿 umbrella `import Mathlib` 硬撞：可用性
            # 以自检第 ⑤ 步那条 Mathlib 读数为准（不靠记忆）。
            "要证图论命题时，库走 `import Mathlib.Combinatorics.SimpleGraph.Basic`（不要只写 umbrella "
            "`import Mathlib`：能过但更重）；它到底可不可用，看自检第 ⑤ 步那条 Mathlib 读数"
            "（`leantoolchain.mathlib_reading`）—— 读数说 absent/unusable 时如实回 unknown，"
            "不许拿一句 `import Mathlib` 硬撞。",
            "忠实复述 B 的证明链路：先把 B 的 statement_full 与 proof_text 逐句读一遍，"
            "把它的每一步与你打算写的 Lean 声明/策略一一对上，再动手写。"
            "对不上的三种情形各自处置 —— 条件是隐含的（补成显式假设并把这一处交回 B 复核）、"
            "定义是私有的（改成自足定义并写清与原文的差异）、步骤被跳过（记成缺口，"
            "标 unknown，不许拿 sorry 或更强的假设顶上去）。",
            "源码的 import 只写它自己用到的那几行：Mathlib 能不能用看 TOOLCHAIN_FACTS 的现算读数，"
            "读数说不可用时写不依赖 Mathlib 的自足文件（缺库导致的编译失败是缺库，不是命题不成立）。",
            "失败要分类：`compile_error` / `uses_sorry` / `extra_axioms` / `decl_mismatch` 是"
            "查了没通过（failed），`no_backend` / `timeout` / `import_unavailable` / 自检不过"
            "是没查成（unknown）。两档不许折叠：把它们说成一档，读者就分不出"
            "「命题可疑」与「我们没验」。",
            "试错要有代价意识：只改检查器原话指出的那一处，别整篇重写；改不动就把命题改小"
            "（有限、具体、能一次过的形态），或者如实记未核到并把检查器原话留下。",
            # 派 C 的用途必须写进 policy（不是只写在边表里）：模型要知道"派 C 是去做什么"，
            # 否则这条边在真机上只会被当成"多一个可以召唤的名字"。
            "**派 C 只为一件事：梳理证明链**。把 B 登记的那条证明逐步摆成一张依赖链 —— "
            "哪一步依赖哪一步、哪一步是旁挂（没有下游用它）、哪一步是跳变（跨了好几步却只给"
            "了一句依据）、缺口在哪一步。C 只读分析，它不写台账、不改证明：结论回到你（或经你"
            "回到 B），不许指望它替谁落库。除 C 之外你派不动任何人（`forbidden_edge`），"
            "那是对的 —— 你的活是形式化，别把别人的活接过来。",
            # 汇报的落点是 B 的收件箱：形式化失败或对不上时按受控形态交回 B。
            "**形式化失败或对不上时，交回 B（它是你唯一的出口）**：汇报按受控形态 —— "
            "命题号、失败类型（漏一步 `unfaithful_step` / 缺假设 `missing_hypothesis` / "
            "只能 sorry `sorry_needed` / 与台账对不上 `statement_mismatch`）、具体第几步、"
            "建议 B 补什么。`formalize` 判出这几档时自己就把这条汇报投进 B 的收件箱"
            "（返回值 `report` 那一格：`reported` 才是 B 真的收到了）。改证明、重新过 V 的签"
            "都是 B 的事；若缺陷在路线本身，B 会通知 D 开展研究。你不要自己改台账里的命题，"
            "也不要越级找 D 或 V（`forbidden_edge`）。",
            # 只写这一实现里真有的两件 —— `trace.children` 与
            # `conductor.escalate` 都在本角色的工具面上。判据：
            # tests/test_every_role_knows_it_can_watch_its_children.py。
            "**你能监控自己的直接下级，但只看得见一层**：`trace.children`（不传参数就是看你这一趟名下）"
            "逐个给子任务的状态、被拒次数与类目（`subtask_refusals`）、最近几步（`recent_steps`）、产出是否真落盘"
            "（`products`）、最近一次交接（`last_handoff`）；传 `depth` 大于 1 也只给一层。要看更深（例如你想看"
            "「下级的下级的下级」）就用 `conductor.escalate` 向 M 请求 —— M 的指导**沿绝对编号链逐级由秘书转发**，"
            "**内容只有链尾（你）看得到**，中间各跳只转发、不读内容；你看到的是指导，不是原始全树数据。",
            # 计时口径进**每个角色**的政策（不只是 M）：计时类任务申请的形式 = 等待时间
            # （或等待谁）+ 目的（必填）；忘填目的不报错、只要求追加；到点发回「目的 +
            # 等待时间 + 时间到」。工具面的真身是 `tools/clock_tools.py` 那九件
            # （`UNIVERSAL_TOOLS`：对十一个角色都发），这一段只写"怎么用它"，不抄工具签名
            # （签名在工具说明里，抄一份就是第二个要同步的地方）。
            # 判据：`tests/test_clock_governs_all_timed_work.py`（逐个角色数过九件）。
            "**要等就用时钟，别空转**：等一段时间用 `clock.timer_start(after_sec=<秒>, reason=<目的>)`；"
            "等某个人交差或回话用 `clock.timer_start(wait_for=<名册名 / 绝对编号 / task:编号>, reason=<目的>)` —— "
            "这两种**选一种**（都给或都不给会被拒），并写一句目的。**目的漏填不报错**：先受理，读数里带 "
            "`purpose_missing=true` 并追问你，补一句走 `clock.timer_purpose(entry_id=<同一个编号>, purpose=<目的>)`"
            "（补的是那一条，不是新建一条）。**挂机**：把这一趟交给时钟之后，挂机期间你不产生回合、不轮询、"
            "不空转；到点、或它交差那一刻，时钟把「目的 + 现场等了多久 + 时间到 + 对方说的话/交的东西」"
            "一并发给你，长这样：「时间到：等 D1 交回命题 3 的证明｜等了 19 分钟 40 秒（起于 14:02:10，到于 14:21:50）」。"
            "要反复回来看的（周期性的）用 `clock.periodic_start(every_sec=<秒>, purpose=<目的>)`，停它用 "
            "`clock.periodic_stop(periodic_id=…)` —— 「等 20 分钟 + 周期性巡查」的**唯一写法**是 "
            "`every_sec=1200` + `purpose=\"周期性巡查\"`（M 的巡视就是这一种），别写成「睡 20 分钟」。"
            "读现在几点、这一趟跑了多久、有没有等你的唤醒用 `clock.now`，查还有哪些在计时用 `clock.timer_list`。"
            "**无事可做就起「等任意计时器返回」这个意图**：手上没有要接着做的活时，用 "
            "`clock.wait_any(purpose=<目的>)` 记一条「谁先回来都行」的等待（它记的是意图，不是计时器本身）；"
            "一条计时器都没有还起这个意图时，读数给 `requested=true` / `waiting=false` —— 那是「要求过等、"
            "而手上没有可等的东西」，不是「没在等」；这一档既无计时而手头也没活，就按交差处理"
            "（框架向父代理报告），别空转着等。"
            "**计时只有时钟这一处**：旧的计时工具已经退役，别去找别的等待 / 定时入口。",
        ),
        signature_error="把没跑成的检查写成 verified 或 failed（unknown 被折进另外两档，读者分不出命题可疑还是我们没验）。",
        deliverable="交付状态 —— 交给谁：派你这趟活的父（收工 `final` 的 `notify` 的 `to` 格写它的名册名 / 绝对编号 / 角色名）"
                    "+ 收方 B（回执）；形态：`code/formal/<声明名>.lean` + 检查器原话 + `experiments` 行；"
                    "可核字段：`experiments.method` / `experiments.code_path` / `experiments.code_hash` / "
                    "`experiments.exit_code` / `experiments.verifier_output`；"
                    "算做完：文件在盘上且 `experiments` 有一行 formal，三态结论（verified / failed / "
                    "unknown）与检查器原话、`experiments.exit_code` 逐条对得上（没跑成写 unknown，"
                    "不许折成 failed）。",
        stance=(
            "忠实比漂亮重要：宁可交一个「这里接不上」的缺口，也不交一个被悄悄加强过的定理。",
            "机器说通过只说明它核了你写下的那条；写下的是不是原文那条，是你的责任。",
            "检查器跑不过时说跑不过；检查器不存在时说不知道。你的读数是别人敢下结论的地基。",
        ),
    ),
    emphasis={
        "眼睛": "core",
        "耳朵": "minor",
        "脑子": "core",
        "手": "core",
        "能讨论": "minor",
        "高观点": "minor",
        "能互动": "minor",
        "能思辨": "core",
        "敢创新": "minor",
        "有品味": "minor",
    },
    local_notes={
        "手": "写的是 Lean 源码：落盘、跑检查器、把路径与哈希交出去；不替检查器下结论。",
        "眼睛": "读 B 的 proof_text 与检查器的原话：两边都要逐字对，不凭印象。",
        "脑子": "把一条自然语言证明拆成 Lean 能接的几步：哪一步是引理、哪一步是策略、哪一步接不上。",
        "能思辨": "先问这条命题写下来还是不是原文那条：加强假设是最容易混过去的一种走偏。",
    },
    read_only=False,
    #: `summonable=True`，而只有 B 的出边里有 L（`specs/b.py::SPEC.edges`）。
    #: 别处的每一个角色（A / C / D / E / F / G / H / M / V）都不许有到 L 的边，
    #: 判据逐角色断言（`tests/test_l_collab_surface_is_exactly_this.py`）。
    #: 用户仍可以用 `run-agent L` 单条执行：那是入口，不是边。
    summonable=True,
    #: L 的出边恰好一条：`C`（梳理证明链）。
    #:
    #: 用途（写进 policy，见本文件 `SPEC.brief.policy` 里那一条）：把 B 登记的证明步骤按
    #: 依赖链摆清 —— 哪一步依赖哪一步、哪一步是旁挂（没有下游）、哪一步是跳变
    #: （跨了好几步却只给了一句依据）、缺口在哪。C 只读分析，所以这条边不改任何写权限。
    #: 除 C 之外 L 不派任何人（判据逐角色断言）。
    edges=('C',),
    #: `record` 会落一行 `experiments`（所以写集含它）。
    #: 刻意不含 `statements` —— 那一格是"命题升档"的位置，只有 V 的签字与 F/B 的
    #: 登记能碰；写集里没有它，"L 绕过 V 签"在结构上不可能（不是靠纪律）。
    #: 这一格与协作面无关：单条执行同样要落那一行实验。
    write_set=frozenset(("experiments",)),
    class_path="agentflow.agent_l:AgentL",
    actions=ACTIONS,
    needs=("workspace_root",),
    build=_build,
)


#: 这一块已整块退役：`_action_summary` / `_tool_summary` 与三张 `NO_LEAN_*` 改写表
#: 本该是"关掉 Lean 之后 L 的文本改成什么样"，但它「不可达」——
#: `leanscope.LEAN_ONLY_ROLES` 只有 `L`，而关着时 `require_visible` 抛 `RoleHidden`，
#: L 的提示词根本渲染不出来，那三张表因此没有任何一行会被应用
#: （`agent_prompts._apply_no_lean_variant` 拿到的是别人的文本，一条都匹配不上）。
#: 留着它不是"多一层保险"，而是把一段读起来像现行政策的死字挂在声明旁边。
#:
#: 关掉那一档该说的话仍在「能行动的那一档」说：B 的 `PROOF_CHANNEL_NO_LEAN`（它是唯一
#: 能派 L 的人）与 G 的 `WRITING_SCOPE_NO_LEAN`（正文怎么写）。L 自己不需要"关掉时怎么办"
#: 这一段 —— 关掉时没有 L。

#: 那几条"评估过、最终没有开"的边。这里只登记结论与理由，它不是判据
#: （不被任何代码读）：放在声明文件里，是为了让"为什么 L 的入边只有 B"在改权限面的
#: 那个人眼前，而不是只活在某份报告的正文里。
#:
#: 入口是"只有 B 可以派 L"（理由：B 是 `statements` 的唯一登记方，所以"只让 B 派 L"
#: 结构上等于"L 形式化的东西一定出自 B 的库"，而形式化的成本由那个登记证明的人来判断）。
#: 下列几条仍然不开：
#:
#: - `F → L`：F 的攻坚是流水线的一环，挂在它下面就是把形式化变成流水线的一步；
#:   这件事留给 B（B 有那条命题的登记与证明）。
#: - `E → L`：E 与 L 是同一个桥接层的两个门面（`agent_l._CheckFormalL` 继承
#:   `agent_e._CheckFormal`）。开它等于让做实验的人绕过攻坚的人直接派形式化，
#:   而它在今天也不必要：形式化只走 L 的 `formal.formalize` / `formal.check_formal` /
#:   `formal.record`；E 的 `run_experiment(method="formal")` 已由动作面第一句以理由码
#:   `formal_not_in_e` 拒绝（它落不出 proof 行，也不起任何检查器）。
#: - `D → L`：D 是研究总控。D 的位置是"B 判断缺陷严重时才被通知去开展研究"
#:   （`B → D`），不是"D 直接派 L"。D 派 L 会把"这一条值不值得付检查器成本"这个
#:   判断从 B 手上拿走，而那个判断跟着登记证明的人。
#: - `M → L`：主控不许直连 L（与 `M → F` / `M → V` 同一族：只走间接）。
#:
#: 要开其中一条时改的是 `specs/<该角色>.py::SPEC.edges` 加上本文件的
#: `summonable=True`（后者今天已经是 True）；改这两格都要按 FC-27 走人审。
LATER_EDGES: tuple[tuple[str, str], ...] = (
    ("F", "本批曾开又撤回：F 的攻坚是流水线一环，挂它下面就把形式化变成流水线一步。"
          "2026-10-22 晚的裁定把入口给 B（B 有那条命题的登记与证明）。"),
    ("E", "E 与 L 是同一桥接层的两个门面；开它等于让做实验的人绕过攻坚的人直接派形式化。"
          "今天也不必要（形式化只走 L 的 formal.*；E 的 run_experiment(method='formal')"
          " 已由 formal_not_in_e 拒）。"),
    ("D", "裁定给 D 的位置是「B 判断缺陷严重时才被通知去开展研究」（B → D），"
          "不是「D 直接派 L」：那一格是“这一条值不值得付检查器成本”，跟着登记证明的人。"),
    ("M", "主控不许直连 L（与 M → F / M → V 同一族：只走间接）。"),
)

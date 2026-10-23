# -*- coding: utf-8 -*-
"""角色 L（Lean 形式化者）的声明：动作表 + 边 + 写集 + 职责与门面。

## 这个角色是怎么来的（业主 2026-10-22 的施工单）

照 E 的 Lean 面复制出一个人：E 里与 Lean 开关 / 形式化有关的动作与实现搬过来，
E 自己一行不删、行为不改。

## 协作面：B 是唯一入口，L 只派 C（业主 2026-10-22 晚的最终裁定）

裁定原文（逐字）：

> 「L 的协作面特别简单：只有 B 可以派 L，L 允许派 C 来梳理证明链，消费 B 的定理证明库，
>   可向 B 汇报形式化过程中遇到的困难、要求 B 完善证明并重新得到 V 签，
>   若缺陷严重，B 应通知 D 开展研究处理证明难点。」

当前生效的唯一口径（2026-10-22 23:25 按业主最终裁定写死，别再改这一行）：

- 入边只有 `B → L`；出边只有 `L → C`。除 B 之外没有任何角色能派 L，L 也只派 C；
- 用户那条"指定单条执行"是「入口不是边」：`run-agent L` 直接起，不经过
  `ALLOWED_EDGES` —— 所以它不进下面这张表，也「不许为它加边」（加边就等于把它
  挂成流水线的一环）；
- 四版历史逐条留档（别删，它记的是"谁能让 L 干活"这件事被改过几次）：
  1. 空边集 + 不可召唤（协作面不搭）；
  2. `F → L`（"F 需要一个形式化下游"）；
  3. 撤 `F → L`（业主 B-5「要一条才做一条」）；
  4. 当前这一版：`B → L` + `L → C`（业主 2026-10-22 晚最终裁定，逐字见上）。

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

E 的动作表有五行：实验（`run_experiment` / `run_script_experiment`）、形式化
（`check_formal`）、查询（`evidence_for` / `list_experiments`）。L 只搬形式化这一路，
并把它拆成三个落点各不相同的动作：

1. `check_formal` —— 与 E 的同名动作逐字同义：把源码交给 `verify.check_formal`
   （桥接层的唯一实现）真跑一次，按检查器原话给出判定。L 只是多一道前置自检
   （见 `agent_l` 的 docstring），所以两边口径不会分家；
2. `formalize` —— 写形式化那一格：把一条命题写成 Lean 源码、落到
   `code/formal/<声明名>.lean`、再交给同一个桥接层真跑，结论三态
   （`verified` / `failed` / `unknown`）。E 那边这一格是"先 `fs.write` 再
   `run_experiment(method=formal)`"两步拼出来的（E 的 policy 逐字要求把内联源码
   落进工作区）；L 把它收成一个动作，是因为业主要看见"L 真的写得出 Lean 代码、
   真的能干活"，而两步拼装的路径在"写没写盘"这件事上没有任何机器判据。
3. `record` —— 把一次形式化检查登记成 `experiments` 表的一行（`method="formal"`）。
   业主第二句：「L 不写 experiments ⇒ verified 进不了证据链」。这一格只登记
   形式化实验行，它不动 `statements`：形式化 ≠ 审过，命题升档仍然要 V 的那一签。

副作用与外部性两根轴都如实声明：`formalize` 写本地文件 + 起检查器子进程
（`write_local` + `external="exec"`），`check_formal` 只读 + 起子进程
（`read` + `external="exec"`），`record` 写一行 `experiments` + 起子进程
（`write_local` + `external="exec"`）。这与 E 的同名动作同一口径（E 的 `check_formal`
在 `specs/e.py` 里就是这么写的，长理由也在那里）。

## 写集：只有 `experiments` 一格（2026-10-22 第二批之前是空集）

L 的产出是三样：盘上的 `.lean`、检查器原话、以及 `record` 落下的那一行实验。
前两样不是表行，第三样是 —— 所以 `write_set=frozenset({"experiments"})`。
刻意不含 `statements`：那一格是"命题升档"的位置，只有 V 的签字与 F/B 的登记能碰。
写集里没有它，"L 绕过 V 签"在结构上不可能（不是靠纪律）。

## 2026-10-22 第二班：忠实复述变成机器读数（本文件改的那一格）

审计里 L 唯一的硬缺口是"忠实复述 B 的证明链路"只有文字义务、没有读数：`formalize`
的 `claim` 是一段自由文本，于是"它形式化的到底是不是 B 登记的那一条"没有任何机器判据。
本班只动 `formalize` 这一格（`check_formal` 一字不改）：

1. 参数多一格 `statement_id`（被形式化的那一条在 `statements` 表里的编号）。它是
   可选而不是必填 —— 工具面 `formal.formalize` 今天还不收它（那一格归另一路改），
   声明成必填会让每一次真实调用都缺一格。不给编号时的唯一合法来源是"claim 与台账
   某一行正文逐字相同且唯一"（实现在 `agent_l/formalize.py`，读数里
   `statement_source` 说明这一趟用的是哪一条来源）；
2. 摘要里写进"源码怎么标落点"的约定（`-- step <k>` / `-- assume <文本>`）：那是
   模型唯一看得见这条约定的地方（提示词只列必填参数，见
   `agent_prompts._params_hint`），所以它必须随动作声明一起走；
3. 返回值多出忠实复述八格（`statement_id` / `statement_source` / `coverage` /
   `faithfulness` / `steps_path` / `refused` / `checker_status` / `checker_reason`）。
   其中 `checker_status` 与 `status` 是刻意分开的两格：前者是检查器原话，
   后者是叠加了逐步对照之后的综合结论 —— "机器核过了"不等于"这一趟算数"。

判据在 `tests/test_l_faithfulness_is_measurable.py`（六条，每条都写明改前红）。

## 本文件在 `.noai-paths` 里的状态

2026-10-22 第二批起本文件已登记进 `.noai-paths`（`[category: auth-audit]`）：
它现在有边（`B → L` 那条入边的落点之一是本文件的 `summonable`）、有写集（`experiments`）、
有可召唤性 —— 那三样正是清单里其余 `specs/<角色>.py` 被登记的同一条理由
（改它等于改权限面）。两处清单（`.noai-paths` 与 `AGENTS.md`）必须逐条一致，
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

#: 本角色的动作表。两格都只有 Lean 形式化这一路。
ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        "L", "formalize",
        "把一条命题写成 Lean 源码、落盘到 code/formal/（写函数返回盘上路径与 sha256），"
        "再交给检查器真跑一次。结论三态：verified / failed / unknown ——"
        "unknown 一定带原因（开关关着 / 自检不过 / 检查器不存在 / 超时），不许折进另外两档。"
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
        # `statement_id` 是 2026-10-22 第二班加的（把"忠实复述 B 的证明链路"从文字义务
        # 变成机器读数）：它今天只在动作面上有，工具面 `formal.formalize` 还没收它
        # （那一格由另一路改），所以它按"动作面独有参数"登记在
        # `capabilities._KNOWN_ACTION_ONLY_PARAMS`（导入期第 [9] 条要求有出处）。
        # 不写进 `required`：工具面还没有它，声明成必填会让每一次真实调用都缺一格。
        _obj({"claim": _S, "source": _S, "declaration_name": _S, "statement_id": _S,
              # 2026-10-22 晚（业主裁定「要指明对哪个路径做了形式化验证」）：
              # `proof_no` 是这一趟验的第几份证明（1 = canonical，2 起在同行的 `proofs`
              # 清单里）；`path_source` 记「这个号是谁选的」（B 指定 / 照 C 的建议 /
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
        "path_source 记这个号是谁选的",
        # 参数与工具面 `formal.record` 逐名同类型（两层对账第 [9] 条逐个比）。
        # `status` / `verified` 是"调用方看到的读数"，只用于对账（不采信）：
        # 采信它们等于让 `evidence_kind="proof"` 变成可随手搬运的标签。
        _obj({"statement_id": _S, "code_path": _S, "declaration_name": _S,
              # 路径三格（与 `formalize` 同一套口径，另一处落点）：这一行绑的是第几份
              # 证明、C 给这条路径的显示名（`p<证明号>g<组号>`，只做标记、不当键）、
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
            "先看 TOOLCHAIN_FACTS 的第一行（开关）。那一行说已关闭时，这条路整条不适用：不写源码、"
            "不派检查，如实回 unknown 并给原因码（`lean_selfcheck_off`），改走自然语言逐行审阅"
            "（proof_text + V 的 verify_proof）；说已开启时才走下面几条。",
            "任何 Lean 调用之前先过自检（`leantoolchain` 的四步：解析 / 版本 / 正样例 / 反控）。"
            "自检不是 usable 时，这一趟的全部形式化结论记 unknown 并把原因写清：不起检查器、"
            "不抛栈、不连撞同一条错误 —— 同一条失败只报一行，然后收手。",
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
            # 2026-10-22 晚（业主的最终协作面裁定）：「L 允许派 C 来梳理证明链」。
            # 用途必须写进 policy（不是只写在边表里）：模型要知道"派 C 是去做什么"，
            # 否则这条边在真机上只会被当成"多一个可以召唤的名字"。
            "**派 C 只为一件事：梳理证明链**。把 B 登记的那条证明逐步摆成一张依赖链 —— "
            "哪一步依赖哪一步、哪一步是旁挂（没有下游用它）、哪一步是跳变（跨了好几步却只给"
            "了一句依据）、缺口在哪一步。C 只读分析，它不写台账、不改证明：结论回到你（或经你"
            "回到 B），不许指望它替谁落库。除 C 之外你派不动任何人（`forbidden_edge`），"
            "那是对的 —— 你的活是形式化，别把别人的活接过来。",
            # 2026-10-22 晚（同一份裁定）：「可向 B 汇报形式化过程中遇到的困难、要求 B
            # 完善证明并重新得到 V 签，若缺陷严重，B 应通知 D 开展研究处理证明难点。」
            "**形式化失败或对不上时，交回 B（它是你唯一的出口）**：汇报按受控形态 —— "
            "命题号、失败类型（漏一步 `unfaithful_step` / 缺假设 `missing_hypothesis` / "
            "只能 sorry `sorry_needed` / 与台账对不上 `statement_mismatch`）、具体第几步、"
            "建议 B 补什么。`formalize` 判出这几档时自己就把这条汇报投进 B 的收件箱"
            "（返回值 `report` 那一格：`reported` 才是 B 真的收到了）。改证明、重新过 V 的签"
            "都是 B 的事；若缺陷在路线本身，B 会通知 D 开展研究。你不要自己改台账里的命题，"
            "也不要越级找 D 或 V（`forbidden_edge`）。",
        ),
        signature_error="把没跑成的检查写成 verified 或 failed（unknown 被折进另外两档，读者分不出命题可疑还是我们没验）。",
        deliverable="code/formal/<声明名>.lean（盘上文件 + sha256）、检查器原话、真实退出码、三态结论。",
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
    #: 2026-10-22 晚（业主的最终协作面裁定，逐字）：「L 的协作面特别简单：只有 B 可以派 L，
    #: L 允许派 C 来梳理证明链，消费 B 的定理证明库，可向 B 汇报形式化过程中遇到的困难、
    #: 要求 B 完善证明并重新得到 V 签，若缺陷严重，B 应通知 D 开展研究处理证明难点。」
    #: 这一格是那句话的"入边"那一半：`summonable=True`，而只有 B 的出边里有 L
    #: （`specs/b.py::SPEC.edges`）。别处的每一个角色（A / C / D / E / F / G / H / M / V）
    #: 都不许有到 L 的边，判据逐角色断言（`tests/test_l_collab_surface_is_exactly_this.py`）。
    #: 这一格与被撤回的 B-5 口径（"要一条才做一条、谁都别派它"）的差别只在"谁来派"：
    #: B-5 之后用户仍可以用 `run-agent L` 单条执行；现在多了唯一一条 B → L 的入口。
    summonable=True,
    #: L 的出边恰好一条：`C`（梳理证明链）。
    #:
    #: 用途（写进 policy，见本文件 `SPEC.brief.policy` 里那一条）：把 B 登记的证明步骤按
    #: 依赖链摆清 —— 哪一步依赖哪一步、哪一步是旁挂（没有下游）、哪一步是跳变
    #: （跨了好几步却只给了一句依据）、缺口在哪。C 只读分析，所以这条边不改任何写权限。
    #: 除 C 之外 L 不派任何人（判据逐角色断言）。
    edges=('C',),
    #: 2026-10-22 第二批扩的（此前是空集）：`record` 会落一行 `experiments`。
    #: 刻意不含 `statements` —— 那一格是"命题升档"的位置，只有 V 的签字与 F/B 的
    #: 登记能碰；写集里没有它，"L 绕过 V 签"在结构上不可能（不是靠纪律）。
    #: 这一格与协作面无关：单条执行同样要落那一行实验。
    write_set=frozenset(("experiments",)),
    class_path="agentflow.agent_l:AgentL",
    actions=ACTIONS,
    needs=("workspace_root",),
    build=_build,
)


def _action_summary(action: str) -> str:
    """本角色动作表里那个动作的摘要（`ACTIONS` 是它的唯一落点）。

    与 `specs/e.py` 的同名函数同一个理由：开关关掉时那张改写表的左边不许手抄
    （手抄漂过一次，后果是静默失效 ⇒ "关掉时没有形式化字样"成了假绿）。
    """
    for spec in ACTIONS:
        if spec.action == action:
            return spec.summary
    raise LookupError(f"L 的动作表里没有 {action!r} ⇒ 改写表的左边没有出处")


def _tool_summary(tool_name: str) -> str:
    """工具面上那件工具的摘要（`ToolSpec.summary` 是它的唯一落点）。

    依赖写成函数内 import：`specs` ← `capabilities` ← 装配面是既有方向，本模块
    新增的这条边只往 `tools.formal_tools` 去（那个模块只依赖 `schema` / `store` /
    `tools.base`，不回指 `specs`），沿着它走不回本模块 ⇒ 不成环。
    """
    from ..tools import formal_tools as _FT

    for value in vars(_FT).values():
        spec = getattr(value, "__tool_spec__", None)
        if getattr(spec, "name", None) == tool_name:
            return spec.summary
    raise LookupError(f"工具面上没有 {tool_name!r} ⇒ 改写表的左边没有出处")


#: 关掉 Lean 之后，L 的「面」的改写表（与 `specs/e.py::NO_LEAN_REPLACEMENTS` 同一机制）。
#:
#: 为什么 L 自己也要有一份：E 的那张表是按 E 的文本写的（E 的职责句、E 的政策、
#: E 的 `verify.check_formal` 那一行），而 L 的文本一个字都不同 —— 拿 E 的表去改
#: L 的提示词，一条都匹配不上（而"匹配不上"是静默的）。
#: 应用点仍是唯一的收口 `agent_prompts._apply_no_lean_variant`（它按模块逐个应用
#: `NO_LEAN_REPLACEMENTS` / `NO_LEAN_DROP_LINE_MARKERS` / `NO_LEAN_DROP_BLOCKS`），
#: 所以不会出现"某一条渲染路径没走改写"。
#:
#: 纪律（与 E 那张表逐条相同）：
#: - 左边不许手抄：职责句取 `SPEC.brief.duty` 之外的字面量会漂，所以下面直接写
#:   字面量并留一条判据（`tests/test_l_formalizes_what_b_says.py`）断言它在开着时的
#:   提示词里逐字出现 —— 反真空；工具那一行的左边从 `_tool_summary()` 读真身；
#: - 右边的每一段都不许再提 Lean（判据逐条核）；
#: - 关掉时每个角色都必须读到「系统做不了」：L 的伙伴表里只有 C（`edges=('C',)`），
#:   而 `B → L` 那条入边只印在 B 的提示词里，所以 E 的职责句不会出现在 L 的提示词里
#:   ⇒ 这句话必须由 L 自己的改写提供。
NO_LEAN_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # 职责句（L 自己的开头；也进全体角色的画像文件）
    ("Lean 形式化：把 B 登记的那条命题与它的证明链路**忠实**搬进 Lean 源码，"
     "交给检查器真跑，并如实报 verified / failed / unknown",
     "证明审阅：把 B 登记的那条命题与它的证明链路逐行读一遍，把接不上的那一步写清"
     "（本会话不做形式化验证：系统做不了）"),
    # 政策第 1 条（检查器原话那一条）
    ("形式化只认检查器真的说过的话：桥接层读不到检查器就说读不到，不许用模型的话代替。",
     "证明的判读只认逐行审阅留下的读数与 V 的签字：本会话不做形式化验证（系统做不了），"
     "不许把模型自己的话当成检查器的结论。"),
    # 政策第 3 条（自检那一条）：左边是整条（不只是第一句）—— 只换第一句会留下
    # 后半句"自检不是 usable 时……"挂在一个已经作废的前提上（实测：那一行读起来
    # 自相矛盾）。整条换掉，右边给的是这一档该走的那条路。
    ("任何 Lean 调用之前先过自检（`leantoolchain` 的四步：解析 / 版本 / 正样例 / 反控）。"
     "自检不是 usable 时，这一趟的全部形式化结论记 unknown 并把原因写清：不起检查器、"
     "不抛栈、不连撞同一条错误 —— 同一条失败只报一行，然后收手。",
     "本会话不做形式化验证（系统做不了）：不跑自检、不起检查器；要审一份证明就走逐行审阅"
     "（把证明逐字写进 proof_text，再请 V 逐行走查），并把结论如实记成 unknown。"),
    # 动作那两行（L 自己的动作表在提示词里逐行印出来）
    (f"formalize：{_action_summary('formalize')}",
     "formalize：本会话形式化已关闭 —— 系统做不了形式化验证（调它只会拿到 reason=lean_selfcheck_off），"
     "别派它。"),
    (f"check_formal：{_action_summary('check_formal')}",
     "check_formal：本会话形式化已关闭 —— 系统做不了形式化验证（reason=lean_selfcheck_off），"
     "别派它。"),
    (f"record：{_action_summary('record')}",
     "record：本会话形式化已关闭 —— 系统做不了形式化验证（reason=lean_selfcheck_off）："
     "也没有一次真的检查可登记，别派它。"),
    # 工具面上那三件（左边从工具面真身读，同源）
    (f"formal.formalize：{_tool_summary('formal.formalize')}",
     "formal.formalize：本会话形式化已关闭 —— 系统做不了形式化验证"
     "（调它只会拿到 reason=lean_selfcheck_off）："),
    (f"formal.check_formal：{_tool_summary('formal.check_formal')}",
     "formal.check_formal：本会话形式化已关闭 —— 系统做不了形式化验证"
     "（调它只会拿到 reason=lean_selfcheck_off）："),
    (f"formal.record：{_tool_summary('formal.record')}",
     "formal.record：本会话形式化已关闭 —— 系统做不了形式化验证"
     "（调它只会拿到 reason=lean_selfcheck_off）："),
    # 官能注解那两行（`local_notes` 会进提示词的"十项官能"那一段，左边取本文件的
    # `SPEC.local_notes` 那一格 —— 与 `specs/e.py` 改官能注解同一个理由）
    ("把一条自然语言证明拆成 Lean 能接的几步：哪一步是引理、哪一步是策略、哪一步接不上。",
     "把一条自然语言证明拆成可逐步检查的几步：哪一步是引理、哪一步是依据、哪一步接不上。"),
    ("写的是 Lean 源码：落盘、跑检查器、把路径与哈希交出去；不替检查器下结论。",
     "写的是逐行审阅留下的读数：哪一步有依据、哪一步接不上；不替审阅者下结论。"),
)

#: 关掉 Lean 时「整行删掉」的那些行（按"这一行里包含这个标记"定位）。
#:
#: L 的政策第 5 条整条在讲"import 怎么写 Lean 源码"，关掉之后那一段没有一句还成立。
NO_LEAN_DROP_LINE_MARKERS: tuple[str, ...] = (
    # 政策第 5 条：整条在讲"import 怎么写 Lean 源码"
    "源码的 import 只写它自己用到的那几行",
    # 政策第 4 条（忠实复述）：它要求"在 Lean 源码里一步一个落点"—— 关掉之后
    # 那句要求没有对象，留着会让人以为"还是可以写源码、只是不跑"
    "忠实复述 B 的证明链路：先把 B 的",
    # 政策第 7 条（试错）：整条是"只改检查器原话指出的那一处"
    "试错要有代价意识：只改检查器原话指出的那一处",
    # 边界第 2 条：同样是"在 Lean 源码里找落点、不许用 sorry 堵"
    "忠实复述是逐条义务：B 的 proof_text 里每一步",
)

#: 关掉 Lean 时「整块删掉」的那些块：`(起点标记, 保留下来的第一行标记)`。
#:
#: L 今天没有跨行的形式化块（每条政策都是单个字符串），所以这张表是空的。
#: 留一个空元组而不是删掉这个属性：收口那边按 `getattr(..., ())` 读，
#: 空元组与"属性不存在"在行为上相同，但"L 今天没有整块要删"这件事因此是可读的。
NO_LEAN_DROP_BLOCKS: tuple[tuple[str, str], ...] = ()


#: 那几条"评估过、最终没有开"的边。这里只登记结论与理由，它不是判据
#: （不被任何代码读）：放在声明文件里，是为了让"为什么 L 的入边只有 B"在改权限面的
#: 那个人眼前，而不是只活在某份报告的正文里。
#:
#: 2026-10-22 晚的最终裁定把入口定成"只有 B 可以派 L"（理由：B 是 `statements` 的
#: 唯一登记方，所以"只让 B 派 L"结构上等于"L 形式化的东西一定出自 B 的库"，
#: 而形式化的成本由那个登记证明的人来判断）。下列几条在那句话之后仍然不开：
#:
#: - `F → L`：本批曾经开过又撤回。F 的攻坚是流水线的一环，挂在它下面就是把形式化
#:   变成流水线的一步，而业主的裁定把这件事留给 B（B 有那条命题的登记与证明）。
#: - `E → L`：E 与 L 是同一个桥接层的两个门面（`agent_l._CheckFormalL` 继承
#:   `agent_e._CheckFormal`）。开它等于让做实验的人绕过攻坚的人直接派形式化，
#:   而它在今天也不必要：E 自己的 `run_experiment(method="formal")` 仍然能落
#:   proof 级实验行。
#: - `D → L`：D 是研究总控。裁定给 D 的位置是"B 判断缺陷严重时才被通知去开展研究"
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
          "今天也不必要（E 的 run_experiment(method='formal') 仍能落 proof 行）。"),
    ("D", "裁定给 D 的位置是「B 判断缺陷严重时才被通知去开展研究」（B → D），"
          "不是「D 直接派 L」：那一格是“这一条值不值得付检查器成本”，跟着登记证明的人。"),
    ("M", "主控不许直连 L（与 M → F / M → V 同一族：只走间接）。"),
)

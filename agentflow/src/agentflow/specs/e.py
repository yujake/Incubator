"""角色 E 的声明（`goal-7f5116c1` M3）：动作表 + 边 + 写集 + 职责与门面。

这一份是权限面的真身：`capabilities.py` 从它派生 `CAPABILITIES` / `ALLOWED_EDGES` /
`WRITE_SETS`，`agent_e.py` 只是把它再导出一次。
所以本文件在 `.noai-paths` 里受保护（改它等于改权限面 ⇒ 需要 2 名人审）；
动作表的每一行都从 `capabilities.py` 逐字搬来（含注释），判据见
`tests/test_agent_spec_reconciliation.py` 与 `tests/test_capabilities_two_layer.py`。
"""
from __future__ import annotations

from .. import schema as S
from ..agentspec import (
    _ARR_I,
    _ARR_OBJ,
    _ARR_S,
    _B,
    _I,
    _N,
    _OBJ,
    _S,
    ActionSpec,
    AgentBrief,
    AgentSpec,
    BuilderDeps,
    _obj,
)

#: 本角色的动作表（从 `capabilities.py` 逐字搬来）。
ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        "E", "run_experiment",
        "跑一个实验脚本并登记一行 experiments（证据等级由 schema 机械约束）",
        _obj({"claim": _S, "claim_key": _S, "script_path": _S, "params": _OBJ,
              "method": {"type": "string", "enum": list(S.EXPERIMENT_METHODS)},
              "for_question_id": _S, "timeout": _I,
              # `T0-13`：formal 路径的两个参数（要核对的声明名、要加载的库）。
              # 名字用**方法层**的（`name`/`imports`）：动作的参数直接进
              # `AgentE.run_experiment`，不经 `ToolRegistry.call`，所以不撞
              # `call` 的第一个形参 `name`（工具层那边叫 `run_name`，是另一条理由）。
              # 没有这两格时，**派活这条路根本传不进 formal 的参数**（实测：
              # 闸门如实拒绝 `未声明的参数 ['imports','name']`），于是
              # "E 能形式化"与"M 能派形式化"变成两件事 —— 而 P6/P10 要的是后者。
              "name": {"type": "string", "description": "仅 method='formal'：要核对的声明名"},
              "imports": {"type": "array", "items": {"type": "string"},
                          "description": "仅 method='formal'：这次检查要加载的库"},
              # `sleep` 不在真实 `AgentE.run_experiment` 的具名形参里，它也不收
              # `inspect.Parameter.VAR_KEYWORD`（实测 `inspect.signature`：
              # 既没有 sleep、也没有那一档）⇒ 它是本表与替身夹具之间唯一的接缝，
              # 逐条登记在下面的 `PARAM_SEAMS` 里（带理由串）。
              # 保留声明而不是删掉它的理由（两个方向都写在接缝表那一行里）：
              # 替身/夹具按同一份 schema 声明参数时，"多传一个 sleep 就被拒"
              # 会逼测试去绕过参数校验 —— 而绕过校验的测试就不再测那条链路了。
              # 导入期交叉断言（`assert_capabilities` 第 [8] 条）核这一格：
              # 声明了而实现不收、又不登记 ⇒ `import agentflow.capabilities` 直接失败。
              "sleep": _N,
              # `draft/37` §84 的 D1：`certificate` / `search_bound` 是
              # `schema.Experiment` 硬约束 2c/2d 要求的事实，而**此前这一层没声明它们**
              # ⇒ 模型看不见、也就永远满足不了（实测 T1：method='exhaustive_search'
              # 三次 failed，报「必须给出 certificate」）。方法层与工具层同轮接上。
              "certificate": _OBJ,
              "search_bound": _OBJ},
             ("claim", "claim_key", "script_path")),
        "dict（experiment_id / result / evidence_kind / …）",
        side_effect="write_local", handler_name="run_experiment",
        # `P-6` + `P-20`（B3）：它执行调用方给的脚本，所以逐动作的 external 就是 `exec`。
        # 与工具层同轮改（`verify_tools.py` 的 `verify.run_experiment`）—— 两轴改动必须成对，
        # 否则 `declaration_divergences()` 判"能力层低估"、`assert_capabilities()` 在导入期炸
        # （实测：`pytest tests/test_policy.py` 收集期 ERROR）。
        # `effect` 仍是 `write_local`（它写 experiments 表）：两根轴各说各的真话。
        external="exec",
    ),

    # 2026-10-07（题 9/B，所有者授权、主控代改）：本条摘要只缩末尾那半句解释
    # （121 -> 108 字）。删掉的是「这次检查根本没发生」这句机制叙述 —— 它与紧跟的
    # 「没查成，不算核过」说的是同一件事，而后者才是调用方要守的三态纪律。
    # 两个参数的括注（「Lean 源码全文」/「工作区里的 .lean 文件」）是刻意留下的：
    # `agent_loop._PARAM_REFUSAL_MARKERS` 里没有 `no_script`，所以这一档被拒时
    # 框架不会回参数表 —— 调用方唯一的说明就在这里（判据见
    # `tests/test_action_surface_matches_acceptance.py` 里 §87 的根因那一条）。
    ActionSpec(
        "E", "check_formal",
        "转发到形式化检查器；没有后端时如实回答『没做』。"
        "必须给 `source`（Lean 源码全文）或 `script_path`（工作区里的 .lean 文件）："
        "两者都不给 ⇒ `no_script`（没查成，不算核过）",
        # `R2b-AN-1-C`：本表声明的参数是方法层 `AgentE.check_formal` 的真形参
        # （其中 `name` 在方法层是对的：它不经 `ToolRegistry.call`）；
        # 工具层 `verify.check_formal` 的 schema 已改用 `checker_name`
        # （避撞名：`ToolRegistry.call` 的第一个形参就叫 `name`，`agent_e.py`
        # 里逐字做了一次 `checker_name=name` 的翻译，所以接线是通的）。
        # 于是能力表参数集与工具 schema 参数集既非相等也非包含，而今天
        # 没有任何判据看着这两套集合：`ActionSpec.params` 在生产路径上只做
        # `to_dict()`，不参与调用期校验。三个层面（能力表 / 工具 schema /
        # 方法层 inspect 真形参）的逐字对照登记在
        # `src/agentflow/tools/verify_tools.py` 里 `check_formal` 的 docstring
        # 那一节（标题含 `R2b-AN-1-C`）。本注释只做指向，不改取值：
        # 改 `params` 等于改权限声明。
        _obj({"claim": _S,
              "script_path": {"type": "string", "description": "工作区里的 .lean 文件（与 source 二选一）"},
              "source": {"type": "string", "description": "Lean 源码全文（与 script_path 二选一）"},
              "name": _S,
              "imports": _ARR_S, "timeout_sec": _N}, ("claim",)),
        "dict（checked=False + reason 表示『没法做』）",
        # 本条此前是 `side_effect="unknown"`（"我读不出它写不写"），随后
        # 改成过 `side_effect="network"`。现在按下面三条事实把它落到
        # 两根轴上的确定值：`read` + `external="exec"`。
        #
        # 判据（逐条从代码读出，不是推测）：
        # (1) 无后端时它只读：`verify_tools.check_formal` 在 `detect_verifier()`
        #     探不到检查器时立刻返回 `no_backend`，不起进程、不写盘（见该函数开头）；
        # (2) 有后端时它起外部进程：桥接层 `formalgw.check_lean` 真的执行
        #     `lean`/`coqc`/`isabelle`（`formalgw._default_run` 是 `subprocess.run`），
        #     而那个子进程继承本进程的环境与工作目录 ⇒ 它的读写面不由本框架决定；
        # (3) 它不写工作区：源码走内存时 `formalgw._materialize` 建的是
        #     `tempfile.TemporaryDirectory`（`workdir=None` ⇒ 临时目录），跑完即删。
        #     所以它不是 `write_local`（工作区字节不变）；代价是它也不是纯内存计算。
        #
        # 为什么不是 `network`：那个遗留取值把"出网"与"起进程"压成一档，
        # 而这里的事实只有后者 —— 它执行的是调用方给内容的检查器，
        # 所以第二根轴的确定值是 `exec`。B3 收官把这个取值从词表里删掉之后，
        # 这条注释曾经援引的那一档已经不存在了（P7 的处置也随之收敛：
        # "执行进程"有了自己的档，不再需要借 network 来说）。
        # 代价（如实登记）：它因为 `external != "none"` 而进入沙箱面，
        # 并且在沙箱未声明时需要审批（工具层 `verify.check_formal`
        # 因此从 `_ROLES` 改成 `_ROLES_WRITE`，H 不再拥有它）。
        side_effect="read", handler_name="check_formal",
        external="exec",
    ),

    ActionSpec(
        "E", "evidence_for",
        "三态查询：没查 / 查了没有 / 查到了什么",
        _obj({"claim_key": _S, "for_question_id": _S}),
        "dict（必须带 checked 位）", side_effect="read", handler_name="evidence_for",
    ),

    ActionSpec(
        "E", "list_experiments",
        "只读列举实验",
        _obj({"claim_key": _S, "limit": _I}),
        "dict", side_effect="read", handler_name="list_experiments",
    ),

    ActionSpec(
        "E", "run_script_experiment",
        "`run_experiment` 的便捷封装（脚本路径必填）",
        _obj({"claim": _S, "claim_key": _S, "script_path": _S},
             ("claim", "claim_key", "script_path")),
        "dict", side_effect="write_local", handler_name="run_script_experiment",
    ),
)


def _build(d: BuilderDeps) -> Any:
    """构造 E（需要工作区根：它跑实验脚本、写产物）。"""
    from ..agent_e import AgentE

    return AgentE(d.store, config=dict(d.config), llm=d.llm,
                  workspace_root=d.workspace_root, actor=d.actor)


#: 本角色的声明。
SPEC = AgentSpec(
    role='E',
    brief=AgentBrief(
        duty="数值实验与形式化验证：把一条断言变成可复现的实验或可检查的形式化代码",
        boundary=(
            "数值结果的判读必须是确定性的：脚本输出的数字由代码判，不许过模型。",
            "脚本自报的 proof 级证据一律降级为 cross_check：让被判定的对象自己当判官是最容易被绕过的地方。",
            "实验失败、检查器不存在、代码跑不过，都要如实落 failed 或 unknown，不许补写结论。",
            "引文无法核实的关系要退回 B；发现反例时把结论交回 D，不要自己改别人的结论。",
        ),
        policy=(
            "形式化只认检查器真的说过的话：桥接层读不到检查器就说读不到，不许用模型的话代替。",
            "**先看 TOOLCHAIN_FACTS 的第一行**（业主 2026-10-12 的开关 `toolchain` 段的 `lean_enabled`）：那一行说「Lean 形式化：已关闭」时，下面所有关于 Lean 的写法**整条不适用** —— 不要写 Lean 源码、不要派 `check_formal`、也不要落 `method=\"formal\"` 的实验（前置会拒，理由码 `lean_disabled`）。这一档的证明核验改走**自然语言逐行审阅**：把证明过程逐字写进 `statements` 表的 `proof_text` 列（含假设、每一步依据、你接不上的那一步），再请 V 用 `verify.verify_proof` 逐行走查 —— 它的三态结论进 `verifications` 表，是这一档**唯一**的「审过」凭据；结论强度上限是 cross_check / heuristic，`evidence_kind=\"proof\"` 产不出来，交付里不许出现「已形式化验证/已证明」。检查器状态那一栏会如实回 `lean_disabled`（用户关掉了这条路），它不是 `no_backend`（机器上没有）也不是 `compile_error`（证明没过）—— 见到它别再重试，改走这条路。",
            "**脚本要会说结论**（`REPRO_RESULT:` 协议，`draft/37` §122/§126）：数值脚本必须在 stdout 打印一行 `REPRO_RESULT: {\"result\": \"supports\"|\"refutes\"|\"inconclusive\", ...}` —— **行首就是这五个字加冒号**，后面直接跟一个 JSON 对象（单独一行；别把它当成一个 JSON 对象里的键打印出去：那种形状框架会认，但会在 notes 里记一笔「走的不是协议正身」）。`result=refutes` 时**必须同时给 `counterexample`**（非空；框架会拒收没有反例的证否 —— 证否必须可复核）。有这一行且 `result=supports`，那条实验才落 `cross_check`；没有这一行（或格式非法）一律落 `heuristic/inconclusive`（这是框架的诚实规定，不是惩罚）。脚本不是你写的时（主控或 G 写的），先 `fs.read` 看完再跑：缺这一行就退回作者补，或按协议自己改写它，别默认跑一遍就算核过了。",
            "**收到叫停就把你自己起的子进程停掉**（`draft/37` §128）：停机开关（`.agentflow-stop`）一落盘，框架会在 0.2 s 内终止你正在跑的实验脚本，并把这一条记成「用户叫停」而不是「超时」—— 那是两件事。你要是自己起了别的后台进程（多进程实验、长跑脚本），也要一并停掉：**别把子进程留给用户**。",
            "跑实验前脚本必须先在盘上：`verify.run_experiment` 的 `script_path` 不存在时会被拒。被拒不是「做不了」——用 `fs.write` 自己把核验脚本写进工作区，写完再跑一次，并把「这一版脚本查的是什么」写进实验结论。**别人带着判据把它派给你时**（判据是 `criterion` / `params` / `expected_bound` 三样）就照着那份判据写：脚本要判的正是那条判据（别顺手换成一个更容易算的问题），落点用 `code/`，并让它自己按上一段那行的协议打印结论 ——「有判据、没脚本」这一档不许原地不动。",
            "`verify.check_formal` 的 `imports` 默认不注入任何库（源码自己 import 什么就加载什么）：要用 Mathlib 得显式传 `imports: ['Mathlib']`、或把它写进源码，别指望工具替你加一行（那会让「被检查的源码」与盘上那份不是同一份）；而**这台机器上 Mathlib 到底能不能用看下面 TOOLCHAIN_FACTS 那一段的现算读数** —— 读数说**可用**就把 `'Mathlib'` 传进去（缺库导致的编译失败是**缺库**，不是「命题不成立」，别据它改结论）；读数说没装就别在源码里 import 它（那会落 `import_unavailable`，是「没查成」），改写不依赖 Mathlib 的自足文件。声明名会自动认：源码里恰好一条具名声明就用它；0 条或多条要显式给 `checker_name`（不给就报「取不到唯一那条」并列出候选名）。**内联源码同时要落进工作区**（`fs.write` 到 `code/lean/<名字>.lean`）：`check_formal(source=…)` 只给裁决，它把源码放在临时目录里 —— 那份文件既不是`proof_location`，也没法交给 `run_experiment(method='formal', script_path=…)` —— 裁决与落库之间只差这一步：**把源码写进工作区**。读数说 Mathlib **不可用**时的写法口径（这一条是**条件**的：到底可不可用，看下面 `TOOLCHAIN_FORMAL` 那一段的现算结论 —— 它说「可用」就用库，别绕开它硬编核心层）：① `decide` 只对归约得动的命题有效（`Int` 上的 `if`/比较在 `Init` 下不归约，`decide` 会把真命题判成 false ⇒ `compile_error`）⇒把命题改写成 `Nat`/`Bool` 上的等式或有限枚举形态再 `decide`；② 不要用 sorry/admit 占位：含 sorry 的文件在 Lean 里会正常编译通过（退出码 0），而框架会逐字判「这不是证明」；③ 失败时读检查器原话的那一行错、改一处再试；④ 源码里多于一条具名声明时要显式给 `checker_name`（不给会报「取不到唯一那条」）。",
            "**试错要有代价意识**：只改检查器原话指出的那一处，别整篇重写；继续试还是收手由你按**读得出来的代价**裁量 —— 这一趟试了几次、哪一档失败（`compile_error` / `uses_sorry` / `extra_axioms` / `decl_mismatch`）、检查器原话是什么；读完把**裁量留痕**：写清为什么再试、为什么收手。代价读数读不到时如实说读不到；那是「读不到」，不是「没有代价」，也不因此把所有的路都堵死。改不动就把命题**改小**（有限、具体、能一次过的形态），或者如实记「未核到」并把检查器原话留下。",
            "**数值实验可以慢，但要留下「搜到哪儿/花了多少/用什么策略」**（`draft/37` §133 的用户口径：「数值实验时间长是正常的，我们团队之前做那篇论文时也做了不少数值实验，但后面逐渐发现模式、优化枚举策略才把时间压下去」）：脚本要在 `REPRO_RESULT` 里报三样 —— `bound`（这次搜到哪个界）、`strategy`（枚举策略名：brute force / canonical form / iso rejection / symmetry breaking / incremental+pruning / SAT / randomized+certificate …）、`scaling`（成本曲线：每个 n 多少秒、多少对象）；并且**每完成一个 n 就打一行 `PROGRESS: {json}`** —— 这样即使被超时杀掉，台账里也有「最后完成到哪一步」，而不是只剩一个「超时」。下一次实验要么把界往前推、要么把同一界的耗时压下来、要么把「为什么爆炸」用成本曲线说清；**重复同一条超时脚本而不改策略不算进展**（框架会逐条比给你看：上次的界/策略/耗时 → 这次的）。",
            "**先估规模再跑**（`draft/37` §121）：枚举类实验先在心里算一遍状态数（m-正则图的个数按 n 指数增长），超过预算就换**构造 / 随机 + 精确核验**那条路。**每个打印出来的数都要写清它是什么**：数本身来自脚本、口径却没写进实验结论，读者就无从复核。结论里点明每个量的定义与算法（这一步算的是什么、为什么除以它）。",
        ),
        signature_error="把跑不过的代码块当成通过。",
        deliverable="experiments 行与它们的证据字段（数值、检查器输出、复现命令）。",
        stance=(
            "反例优先：与其再找一个支持例子，不如去找一个能推翻它的例子 —— 那是推进最快的一步。",
            "数值实验的作用是让直觉变得可判：把'我觉得'变成'在 n<=5 上成立/不成立'，并写清适用范围。",
            "检查器跑不过时说跑不过；检查器不存在时说不知道。你的证据链是别人敢下结论的地基。",
        ),
    ),
    emphasis={
        '眼睛': 'core',
        '耳朵': 'minor',
        '脑子': 'core',
        '手': 'core',
        '能讨论': 'minor',
        '高观点': 'minor',
        '能互动': 'minor',
        '能思辨': 'core',
        '敢创新': 'core',
        '有品味': 'core',
    },
    local_notes={
        '手': '编脚本、跑脚本、把结果落成可复现的证据；数值判读由代码判，你不替它下结论。',
        '能思辨': '反例优先：与其再找一个支持例子，不如去找一个能推翻它的例子。',
        '敢创新': '构造反例、设计新实验都算创新；形式化只认检查器真的说过的话。',
        '有品味': '哪种验证才算证据、验到什么程度算够：这是你的品味，要写出取舍理由。',
        '眼睛': '读脚本、数据、检查器输出：证据要能原样重跑。',
        '脑子': '把一条断言变成可判定的一次实验：范围、变量、成功判据先写清。',
    },
    read_only=False,
    summonable=True,
    edges=(
        'B',
        'D',
    ),
    write_set=frozenset(('experiments',)),
    class_path='agentflow.agent_e:AgentE',
    actions=ACTIONS,
    needs=('workspace_root',),
    build=_build,
)

#: 关掉 Lean 之后，E 的「面」按业主 2026-10-12 的口径改写（逐字）：
#: 「负责 Lean 的智能体 E 在开关关掉时可不载入有关形式化验证的提示词，全体成员关于 E 的
#: 印象也可以没有『负责形式化验证』这个说法，一旦提到形式化验证所有人的第一反应是
#: 系统做不了」。
#:
#: ## 为什么是一张"渲染出来的文本 → 改写文本"的表，而不是改声明本身
#:
#: 声明（`SPEC.duty` / `policy` / 官能、`ACTIONS` 的 `summary`）是**权限面与面的唯一来源**，
#: `capabilities` 那四张表由它派生，`tests/golden/*_snapshot.json` 钉着它 ——
#: 按开关改声明等于让"权限面"随一台机器的设置漂移，那是另一种更坏的错。
#: 所以：**声明不动**，动的只是"渲染给模型看的那份文本"；改写表跟声明住在同一个文件里
#: （同一个事实只有一个落点），由 `agent_prompts` 在渲染之后按开关应用。
#:
#: ## 判据（`tests/test_lean_switch.py`）
#:
#: ① 开关开着时：每一条的左边必须在**整份提示词里逐字出现**（反真空 —— 否则这张表
#:    会在某次重写之后悄悄失效，而"关掉时没有形式化字样"这句话就成了假绿）；
#: ② 开关关掉时：左边一条都不许再出现，且提示词里必须出现"系统做不了形式化验证"。
NO_LEAN_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # 职责句（E 自己的开头 + 全体角色的伙伴表里那一行都是这一句）
    ('数值实验与形式化验证：把一条断言变成可复现的实验或可检查的形式化代码',
     '数值实验与证明审阅：把一条断言变成可复现的实验，或逐行审阅一份自然语言证明'
     '（本会话不做形式化验证：系统做不了）'),
    # E 的政策第 1 条
    ('形式化只认检查器真的说过的话：桥接层读不到检查器就说读不到，不许用模型的话代替。',
     '本会话不做形式化验证（系统做不了）：证明的判读只认「逐行审阅留下的读数 + V 的签字」，'
     '不许把模型自己的话当成检查器的结论。'),
    # E 的官能注解（敢创新那一条）
    ('构造反例、设计新实验都算创新；形式化只认检查器真的说过的话。',
     '构造反例、设计新实验都算创新；证明的判读只认逐行审阅留下的读数。'),
    # E 的官能注解（有品味那一条里的"验到什么程度算够"）
    ('哪种验证才算证据、验到什么程度算够：这是你的品味，要写出取舍理由。',
     '哪种证据才算数、审到什么程度算够：这是你的品味，要写出取舍理由。'),
    # 工具面上的那一件（E/F/G 都看得见）
    ('verify.check_formal：把一条命题（Lean 源码）交给检查器真跑一次：',
     'verify.check_formal：本会话形式化已关闭 —— 系统做不了形式化验证'
     '（调它只会拿到 reason=lean_disabled）：'),
    # 工具面上的那一件（E 自己的"手段"清单里是短名字那一行）
    ('check_formal：转发到形式化检查器；没有后端时如实回答『没做』。',
     'check_formal：本会话形式化已关闭 —— 系统做不了形式化验证（reason=lean_disabled），'
     '别派它。'),
    # 伙伴表动作行（全体角色都看得见的那一行）
    ('check_formal（必填 claim）——转发到形式化检查器；没有后端时如实回答『没做』。',
     'check_formal（必填 claim）——本会话形式化已关闭：系统做不了（reason=lean_disabled），'
     '别派它；要核证明请把过程落 `proof_text` 再派 V 的 `verify.verify_proof` 逐行审阅。'),
    # 别人的口径里"要不要形式化"的两处（D 的"初步审阅"与"可挽救性评估"）
    ('数学对错的最终背书在形式化（E）或人', '数学对错的最终背书在逐行审阅（E / V）或人'),
    ('要多少预算（大概几步、要不要形式化）', '要多少预算（大概几步）'),
    # H 去找 E 的那件事
    ('断言能否形式化就找 E', '断言站不站得住就找 E 逐行审阅'),
    # M 的"形式化 E"那一档（写位的人）
    ('数值 / 形式化 E、证明 F、审过 V、正式审查 H', '数值 E、证明 F、审过 V、正式审查 H'),
)

#: 关掉 Lean 时**整行删掉**的那些行（按"这一行里包含这个标记"定位）。
#:
#: 为什么与上面的替换表分开：有些段落**整段**都在讲怎么写 Lean（那一行里没有一句
#: 在关掉之后还成立），逐句改写只会得到一段自相矛盾的话 —— 那种段落该整行删掉。
#: 位置口径：`specs` 的 policy / boundary / 工具描述在提示词里**各占一行**
#: （每条是单个字符串，内部没有换行），所以"按行删"是安全的；
#: 判据同样要求每一条标记在**开着时**的提示词里出现（反真空）。
NO_LEAN_DROP_LINE_MARKERS: tuple[str, ...] = (
    # E 的政策第 5 条：整条是"Mathlib 可用/不可用时怎么写 Lean 源码"
    '`verify.check_formal` 的 `imports` 默认不注入任何库',
)

#: 关掉 Lean 时**整块删掉**的那些块：`(起点标记, 保留下来的第一行标记)`。
#:
#: 为什么还要有这一档（单行删不够）：纸包六的"核验证明分两步"是一条跨好几行的项目，
#: 而"里面每一行都在讲形式化"这件事只有整块一起删才成立 —— 删一半会留下一句没有主语的
#: 半句话（真机概率不低：那一块的第一行与第二行之间没有空行）。
#: 块尾刻意选在**开关分支那一条**（`但先看 TOOLCHAIN_FACTS 的第一行`）：它正是删掉之后
#: 该走的那条路，所以"删到它之前"＝"留下替代路线"。
NO_LEAN_DROP_BLOCKS: tuple[tuple[str, str], ...] = (
    ('**"核验证明"分两步，两步都要走**', '- **但先看 TOOLCHAIN_FACTS 的第一行**'),
)


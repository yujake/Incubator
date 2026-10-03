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

    ActionSpec(
        "E", "check_formal",
        "转发到形式化检查器；没有后端时如实回答『没做』。"
        "**必须给 `source`（Lean 源码全文）或 `script_path`（工作区里的 .lean 文件）**："
        "两者都不给 ⇒ `no_script`（这次检查根本没发生，什么都不算核过）",
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
        duty='数值实验与形式化验证：把一条断言变成可复现的实验或可检查的形式化代码',
        boundary=(
            '数值结果的判读必须是确定性的：脚本输出的数字由代码判，不许过模型。',
            '脚本自报的 proof 级证据一律降级为 cross_check：让被判定的对象自己当判官是最容易被绕过的地方。',
            '实验失败、检查器不存在、代码跑不过，都要如实落 failed 或 unknown，不许补写结论。',
            '引文无法核实的关系要退回 B；发现反例时把结论交回 D，不要自己改别人的结论。',
        ),
        policy=(
            '形式化只认检查器真的说过的话：桥接层读不到检查器就说读不到，不许用模型的话代替。',
            '跑实验前脚本必须先在盘上：`verify.run_experiment` 的 `script_path` 不存在时会被拒。被拒不是「做不了」——用 `fs.write` 自己把核验脚本写进工作区，写完再跑一次，并把「这一版脚本查的是什么」写进实验结论。',
            "`verify.check_formal` 的 `imports` 默认**不注入任何库**（源码自己 import 什么就加载什么）：要 Mathlib 就显式传 `imports: ['Mathlib']`，或把它写进源码 —— 别指望工具替你加一行，那会让「被检查的源码」与盘上那份不是同一份。声明名**会自动认**：源码里恰好一条具名声明就用它；0 条或多条要显式给 `checker_name`（不给就报「取不到唯一那条」并列出候选名 —— 以前是拿文件名词干顶替，于是「没点名」被报成 `decl_mismatch`，读起来像「查了没通过」）。真机读数（2026-10-01）：`code/lean/p2_rho_sum_zero.lean` 在旧默认（注入 Mathlib）下⇒ `import_unavailable`（`missing_imports=['Mathlib']`）；默认不注入 ⇒ `verified=True`，检查器原话 `'rho_sum_zero' does not depend on any axioms`。",
        ),
        signature_error='把跑不过的代码块当成通过。',
        deliverable='experiments 行与它们的证据字段（数值、检查器输出、复现命令）。',
        stance=(
            '反例优先：与其再找一个支持例子，不如去找一个能推翻它的例子 —— 那是推进最快的一步。',
            "数值实验的作用是让直觉变得可判：把'我觉得'变成'在 n<=5 上成立/不成立'，并写清适用范围。",
            '检查器跑不过时说跑不过；检查器不存在时说不知道。你的证据链是别人敢下结论的地基。',
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

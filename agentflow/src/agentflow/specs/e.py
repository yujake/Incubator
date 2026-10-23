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
              # `schema.Experiment` 硬约束 2c/2d 要求的事实，而「此前这一层没声明它们」
              # ⇒ 模型看不见、也就永远满足不了（实测 T1：method='exhaustive_search'
              # 三次 failed，报「必须给出 certificate」）。方法层与工具层同轮接上。
              "certificate": _OBJ,
              "search_bound": _OBJ,
              # D-33（2026-10-23 夜，r34b 真机）：穷举证明的三格凭据此前不在任何声明面里，
              # 而提示词要求 E 跑之前先报三件套 + 把 `exhaustive` 写成布尔 ⇒ 模型只能传空
              # params，②③ 落不成（4 条 exhaustive_search 全落 cross_check）。
              # 四格全部可选（非穷举的实验不该被逼填），但穷举那一档要收得下：
              # 工具 schema（`verify_tools.py` 的 `verify.run_experiment`）与
              # `AgentE.run_experiment` 同轮加了同名同类型的四格 —— 两层对账会强制一致。
              # 缺 design / enumeration / exhaustive 任何一格 ⇒ 这条证据落 cross_check
              # （判据本体是 `numericproof.exhaustion_problems`，不在这张表里重写一份）。
              "design": _S,
              "enumeration": _S,
              "exhaustive": _B,
              "search_space": _S},
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

    # 2026-10-23 晚裁定（业主逐字：「E 侧与 Lean 相关的工具和动作都该清干净」）：
    # `check_formal` 这一整条动作已从本表摘掉 —— 不是"写死关闭"，是"没有这一支"。
    # 它原来那一格的摘要会说「已停用 …/ 形式化由 L 承担」，而一句话里同时出现
    # 「本岗」与「形式化」正是裁定要清掉的那种记忆；受控拒绝那一层也不在了
    # （`AgentE` 上没有这个方法，`run_experiment(method='formal')` 由动作面的第一句
    # 以理由码 `formal_not_in_e` 拒绝）。
    # 判据：`tests/test_e_has_no_lean_side.py` 判据 1 / 6。

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
        # 2026-10-22 晚裁定（「其它角色关于 E 的 Lean 侧记忆可以全面清除」）：`duty` 末尾
        # 原来挂着「（形式化那一岗是 L）」—— 它是伙伴表里唯一把「E」与「形式化」放在同一句
        # 的东西，于是十一个格里有五个格靠这一句把 E 记成形式化的邻居。裁定要求清掉这条
        # 记忆：E 的职责句只说实验与反例，形式化归谁由 `policy` 第一句说（那一句的主语
        # 是「形式化」，不是「E」，判据见 `tests/test_e_has_no_lean_side.py` 判据 3b）。
        duty="数值实验与攻坚：把一条断言变成可复现的实验或反例",
        boundary=(
            "数值结果的判读必须是确定性的：脚本输出的数字由代码判，不许过模型。",
            "脚本自报的 proof 级证据一律降级为 cross_check：让被判定的对象自己当判官是最容易被绕过的地方。",
            "实验失败、代码跑不过、读数不存在，都要如实落 failed 或 unknown，不许补写结论。",
            "引文无法核实的关系要退回 B；发现反例时把结论交回 D，不要自己改别人的结论。",
        ),
        policy=(
            "你这一岗的凭据是实验与反例；形式化的结论以 V 的签与 B 的台账为准 —— "
            "要不要做由**用户指定**，指定之后由 B 逐条安排、回执由 B 带回。",
            "**证明那一档的判读改走自然语言逐行审阅**：把证明过程逐字写进 `statements` 表的 `proof_text` 列"
            "（含假设、每一步依据、你接不上的那一步），再请 V 用 `verify.verify_proof` 逐行走查 —— 它的三态结论进 `verifications` 表，"
            "是这一档**唯一**的「审过」凭据。你这一岗产 `proof` 档只有两条路：穷举（见下面「穷举要按一份协议跑」那一条，"
            "签名者是 V）与形式化（结论以 V 的签与 B 的台账为准）；交付里不许出现凭空写下的「已形式化验证/已证明」。",
            "**脚本要会说结论**（`REPRO_RESULT:` 协议，`draft/37` §122/§126）：数值脚本必须在 stdout 打印一行 "
            "`REPRO_RESULT: {\"result\": \"supports\"|\"refutes\"|\"inconclusive\", ...}` —— **行首就是这五个字加冒号**，后面直接跟"
            "一个 JSON 对象（单独一行；别当成某个 JSON 对象的键）。`result=refutes` 时**必须同时给 `counterexample`**（非空；框架会"
            "拒收没有反例的证否 —— 证否必须可复核）。有这一行且 `result=supports`，那条实验才落 `cross_check`；没有或格式非法一律落 "
            "`heuristic/inconclusive`。脚本不是你写的时（主控或 G 写的），先 `fs.read` 看完再跑：缺这一行就退回作者补，或按协议自己"
            "改写它。**实验的价值在于能判**：优先设计能推翻的方案，每条落库时写清它支持 / 反驳了哪条 `claim`、读数是多少"
            "（`result` / `search_bound`）；只跑通不判定的不算产出。",
            "**收到叫停就把你自己起的子进程停掉**：停机开关（`.agentflow-stop`）一落盘，框架会在 0.2 s 内终止你正在跑的实验脚本，"
            "并把这一条记成「用户叫停」而不是「超时」—— 那是两件事。你要是自己起了别的后台进程（多进程实验、长跑脚本），也要一并"
            "停掉：**别把子进程留给用户**。",
            "跑实验前脚本必须先在盘上：`verify.run_experiment` 的 `script_path` 不存在时会被拒。被拒不是「做不了」—— 用 `fs.write` "
            "自己把核验脚本写进工作区，写完再跑一次，并把「这一版脚本查的是什么」写进实验结论。**别人带着判据把它派给你时**"
            "（判据是 `criterion` / `params` / `expected_bound` 三样）就照着那份判据写：脚本要判的正是那条判据（别换成更容易算的"
            "问题），落点用 `code/`，并让它按上一段那行的协议打印结论 ——「有判据、没脚本」这一档不许原地不动。",
            "**形式化要不要做由用户指定**：那一岗由 B 逐条安排（一条才做一条）、回执由 B 带回，"
            "你按回执里的三态结论取用；在那之前如实记「未核到」。你这一岗只做实验与反例。",
            "**每条实验都要留下两样原话**：`exit_code`（进程真实退出码；没跑成时是 "
            "`None`，**绝不用 0 冒充「跑过」**）与脚本的原样输出（框架把它落进 `out/experiments/<实验号>.log`）。"
            "这两样在实验行落库的那一刻就要在；只写「我跑过了」不算证据 —— 读数要能被别人按同一份脚本重跑出来。",
            "**数值实验可以慢，但要留下「搜到哪儿/花了多少/用什么策略」**：脚本要在 `REPRO_RESULT` 里报三样 —— `bound`（这次搜到"
            "哪个界）、`strategy`（枚举策略名：brute force / canonical form / iso rejection / symmetry breaking / incremental+pruning / "
            "SAT / randomized+certificate …）、`scaling`（成本曲线：每个 n 多少秒、多少对象）；并且**每完成一个 n 就打一行 "
            "`PROGRESS: {json}`** —— 这样即使被超时杀掉，台账里也有「最后完成到哪一步」，而不是只剩一个「超时」。下一次实验要么把界"
            "往前推、要么把同一界的耗时压下来、要么把「为什么爆炸」用成本曲线说清；**重复同一条超时脚本而不改策略不算进展**。",
            "**先估规模再跑**：枚举类实验先在心里算一遍状态数（m-正则图的个数按 n 指数增长），超过预算就换**构造 / 随机 + 精确核验**"
            "那条路。**每个打印出来的数都要写清它是什么**：数本身来自脚本、口径却没写进实验结论，读者就无从复核；结论里点明每个量的"
            "定义与算法。",
            # 2026-10-23 晚（业主：「如果纯数值实验直接把整个命题证掉了，那也能拿 proof 标识，
            # 理由是穷举，签名是对应的程序脚本」；「E 写的报告要能落下来，且 V 也要会审这种东西，
            # 加 E 派 V 的边」）：穷举协议此前在提示词里是 0 处 —— E 是 ② 与 ③ 的作者、
            # 也是唯一能触发 V 会审的一方，而它读不到「跑穷举要报什么、报告落在哪、什么时候派 V」。
            # 代码侧的真身是 `numericproof`（签名与档位）与 `exhaustionreport`（`out/experiments/
            # <实验号>/exhaustion.md` 那份读数）；这一段只是把那一份口径写进 E 的提示词，
            # 不另立判据。它与后面那几条的分工：这一条讲穷举的协议，上面那几条讲数值实验的写法。
            "**穷举要按一份协议跑**（业主 2026-10-23：纯数值实验把整个命题穷尽验证掉时也算证明，理由是穷举、签名是那份程序）："
            "① 跑之前先报三件套 —— 搜索空间（多大、这个数是怎么算出来的）、穷尽的判据（`observations` 里的 `exhaustive` 要写成布尔 "
            "`true`，并说清为什么不漏：用了哪些对称性 / 剪枝、为什么这些剪枝不丢解）、边界处理（n 的上界或区间端点在哪儿、"
            "边界那一档由谁覆盖）；三件都要写进实验结果，缺一件就不算穷举。② 证明栏那三块由你写：程序地址（相对仓库根的路径）/ "
            "程序设计思路 / 穷举论证；落点固定是 `out/experiments/<实验号>/exhaustion.md` —— 三块齐全、署名 `作者：E`、"
            "并写出那条 `exp:<实验号>` 编号；报告没落成或三块不齐，这一条最多是「有数值实验支持」。③ 跑出穷举证据之后"
            "立刻派 V 会审（E → V 是直接边，用 `summon` 唤起 V）：把证明栏（程序相对仓库的路径 + 你写的 ②③）与只读读数"
            "一起交给它的 `verify.verify_proof` —— 那一签（`signed_by=V`、`proof_authors` 含 E、`proof_reason=exhaustion`）"
            "是这份证明成立的唯一凭据，你自己签不了。④ 不完全的实验（抽样、只扫了一批点、`exhaustive` 不是布尔 `true`）"
            "只能记「有数值实验支持」，不许写成「已证明」或「定理」，也不许自己给这一条签 proof —— 这是业主点名的分界。"
            # 2026-10-23 夜（业主的三句话，D-34）：「E 拿着有 V 签名的报告**上报** D 找 B 入库，和 F 拿着 V 签名的证明
            # 上报 D 找 B 入库是一个逻辑」；「一般 D 会是 E 和 F 的父代理，所以我的用词是上报，即向上找 D 而非向下派 D。
            # 如果向上直接是 M 也无所谓，M 会派 D」。于是 ④ 之后还差最后一步：**上报**（不是自己去入库）。
            # 代码侧的真身是 `numericproof.INDEX_*` 那四格（D 报告里的一行）＋ B 的入库闸
            # （`numericproof.filing_problems` 顺索引取对象、核 `evidence_sha256` 与 `v_signature`）。
            "⑤ 拿到 V 的签之后**上报父代理，不要自己去入库**：把（那份程序的相对路径 + 你写的 ②③ + V 的签）"
            "一起交上去 —— **父是 D 就报 D；父是 M 就报 M，由 M 派 D/B**。这是**上报**（向上找 D）而不是向下派 D："
            "D 会把这一条写进它的报告与论文对应表的**索引四格**（`evidence_kind`＝`report`、`evidence_path`＝你那份 "
            "`out/experiments/<实验号>/exhaustion.md`、`evidence_sha256`＝它的字节 sha256、`v_signature`＝"
            "`{verdict, sha256}`），再由 D 派 B 入库。**你既不要写对应表，也不要自己去找 B 的 "
            "`register_statement`**：B 认的是 D 报告里那一行索引，缺了它，你这份证据只能被记成「有数值实验支持」——"
            "那不是证据不行，是目录里没有 E 那本的条目。",
            "**你发现的例子要交出去**：数值实验里撞见的反例 / 玩具例先落 `experiments`（`refutes` 必须带非空 `counterexample`），"
            "**再交 D** 写进研究手稿的「例子与反例」那一节（`E → D` 是直接边）：撞见的那个例子**不落下来就等于没发现**。",
            # 判据：`tests/test_agent_e.py::test_schema_rejects_refutes_without_counterexample`
            # （`schema.Experiment.validate` 对「refutes 但没有 counterexample」直接抛；正控在同文件
            #  :521 那一行）。原来那 6 行里的真机故事与示例数值（`n=40` / `1681=41×41`）就是这一条
            #  已经被判据接手之后剩下的叙述 —— 删的是故事，不是义务。
            "**反例只有一个合法落法：`result=refutes` + 非空 `counterexample`**（只写进 `certificate` 不算法；`claim` 写**被检验的那条命题**，「这条命题为假」是结论、不是 claim）。",
        ),
        signature_error="把跑不过的代码块当成通过。",
        deliverable="experiments 行与它们的证据字段（数值、退出码、复现命令）。",
        stance=(
            "反例优先：与其再找一个支持例子，不如去找一个能推翻它的例子 —— 那是推进最快的一步。",
            "数值实验的作用是让直觉变得可判：把'我觉得'变成'在 n<=5 上成立/不成立'，并写清适用范围。",
            "实验跑不过时说跑不过；没读到读数时说不知道。你的证据链是别人敢下结论的地基。",
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
        '敢创新': '构造反例、设计新实验都算创新；一条穷举证明的凭据只认那三件套（搜索空间 / 穷尽的判据 / 边界处理）与 V 的签字。',
        '有品味': '哪种验证才算证据、验到什么程度算够：这是你的品味，要写出取舍理由。',
        '眼睛': '读脚本、数据、检查器输出：证据要能原样重跑。',
        '脑子': '把一条断言变成可判定的一次实验：范围、变量、成功判据先写清。',
    },
    read_only=False,
    summonable=True,
    edges=(
        'B',
        'D',
        # 业主 2026-10-23 晚（逐字：「E 写的报告要能落下来，且 V 也要会审这种东西，
        # 加 E 派 V 的边」）：E 跑出穷举证据之后，要能把它派给 V 会审。
        #
        # 为什么这条边必须是真的（而不是"E 在回报里提一句让 M 去派"）：②③ 的作者是 E，
        # 而"这份穷举证据成不成立"的唯一判定者是 V —— 两人之间隔着 M 转一次，就多一处
        # "谁该看什么"的猜测；边在这里，`conductor.summon("V", ..., by="E")` 就能通。
        # 这条是单向的（E -> V）：V 的入边只有 B / E / F 三条，其它角色到 V 的边一条
        # 都没有动（`specs/v.py` 的 `edges=('F',)` 是 V 自己的出边，V -> F 退回那一条），
        # 本改动也不给 V 加出边。
        'V',
    ),
    write_set=frozenset(('experiments',)),
    class_path='agentflow.agent_e:AgentE',
    actions=ACTIONS,
    needs=('workspace_root',),
    build=_build,
)

#: 关掉 Lean 之后，E 的「面」按业主 2026-10-12 的口径改写（逐字）：「负责 Lean 的智能体 E 在开关
#: 关掉时可不载入有关形式化验证的提示词，全体成员关于 E 的印象也可以没有『负责形式化验证』这个说法，
#: 一旦提到形式化验证所有人的第一反应是系统做不了」。
#: 为什么是"渲染文本 → 改写文本"的表而不是改声明本身：声明（`SPEC.duty` / `policy` / 官能、`ACTIONS`
#: 的 `summary`）是权限面的唯一来源，`capabilities` 四张表由它派生、`tests/golden/*_snapshot.json` 钉着
#: 它 ⇒ 按开关改声明等于让权限面随机器设置漂移。所以「声明不动」，动的只是渲染给模型看的那份文本。
#: 左边一律手写：2026-10-23 晚裁定把 `check_formal` 那一整条动作摘掉之后，本表不再从
#: `ACTIONS` 里读摘要（那一格没有落点了），于是这里没有"读真身"的入口 —— 每一条 `old` 都由
#: `tests/test_lean_switch.py` 的反真空（开着时逐字出现）守着，写错当场红。
#: 判据（`tests/test_lean_switch.py`）：① 开着时左边逐字出现（反真空）；② 关掉时左边不出现、右边出现，
#: 且提示词里必须出现"系统做不了形式化验证"。
NO_LEAN_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # 2026-10-24（业主口径：形式化要不要做由用户指定，指定之后由 B 逐条安排）：
    # 开档那几句改成"结论以 V 的签与 B 的台账为准"的正向写法，关档 L 与 B 的那条通道
    # 在这一档都不存在 ⇒ 统一改成"本会话不做形式化验证（系统做不了）"。
    # 顺序是刻意的：**具体的长条目在前、那条统一的括注在最后** —— 反过来的话，
    # 长条目里的括注会先被换成短的那一句，长条目就再也匹配不到了（判据当场报"改写没生效"）。
    ('形式化的结论以 V 的签与 B 的台账为准 —— 要不要做由**用户指定**，指定之后由 B 逐条安排、回执由 B 带回。',
     '形式化那一档本会话产不出来（系统做不了）：证明的判读只认「逐行审阅留下的读数 + V 的签字」。'),
    ('与形式化（结论以 V 的签与 B 的台账为准）', '与形式化（本会话产不出来）'),
    ('**形式化要不要做由用户指定**：那一岗由 B 逐条安排（一条才做一条）、回执由 B 带回，'
     '你按回执里的三态结论取用；在那之前如实记「未核到」。你这一岗只做实验与反例。',
     '**本会话不做形式化验证（系统做不了）**：证明的判读走逐行审阅'
     '（`proof_text` + V 的 `verify_proof`），在那之前如实记「未核到」。你这一岗只做实验与反例。'),
    # G 与 H 的边界那两句（同一批改写成"要不要做由用户指定"）。它们也进画像文件
    # （`AGENT-PROFILES.md` 由 `profiles_markdown` 渲染并过同一张表）—— 关档不改写的话，
    # 画像会告诉读的人"这条路今天由用户指定就行"，而那一档它做不出来。
    ('形式化要不要做由**用户指定**，指定之后由 B 逐条安排（一条才做一条）、回执由 B 带回 —— '
     '你按回执取用那一条结论。',
     '本会话不做形式化验证（系统做不了）：那一档的结论以 V 的签与 B 的台账为准。'),
    ('要不要做由**用户指定**，指定之后由 B 逐条安排，回执是 V 的签与 B 的台账',
     '本会话不做形式化验证（系统做不了），结论以 V 的签与 B 的台账为准'),
    # 官能注解（有品味那一条里的"验到什么程度算够"）
    ('哪种验证才算证据、验到什么程度算够：这是你的品味，要写出取舍理由。',
     '哪种证据才算数、审到什么程度算够：这是你的品味，要写出取舍理由。'),
    # 2026-10-23（本批，业主「Lean 没开时隔绝 L」是硬口径）：五元位那一段的 formal 那一行。
    # 它现算自 `evidencebits.BIT_LEDGERS`，而 owner 已从 E 改成 L（`formal.record` 是唯一落点）
    # ⇒ 开着时这一行点着 L，而 L 在关档不存在（`leanscope.is_hidden`）。
    # 关档换成"这一位这一档产不出 proof 行"，一个字都不点 L。
    # 判据：`tests/test_l_is_isolated_when_lean_is_off.py::test_off_no_role_prompt_mentions_l`
    # （关档十一格提示词里 0 处 L 记号）＋ 本表的反真空（`old` 在开档逐字出现）。
    ("- `formal`：**L** 签 —— 凭据在 experiments（method='formal'）",
     "- `formal`：（本会话产不出 proof 档）—— 凭据在 experiments（method='formal'）"),
)

#: 关掉 Lean 时「整行删掉」的那些行（按"这一行里包含这个标记"定位）。
#:
#: 为什么与上面的替换表分开：有些段落「整段」都在讲怎么写 Lean（那一行里没有一句
#: 在关掉之后还成立），逐句改写只会得到一段自相矛盾的话 —— 那种段落该整行删掉。
#: 位置口径：`specs` 的 policy / boundary / 工具描述在提示词里「各占一行」
#: （每条是单个字符串，内部没有换行），所以"按行删"是安全的；
#: 判据同样要求每一条标记在「开着时」的提示词里出现（反真空）。
NO_LEAN_DROP_LINE_MARKERS: tuple[str, ...] = (
    # 2026-10-24（业主口径：形式化要不要做由用户指定，指定之后由 B 逐条安排）：
    # 这一格此前是 M 的两条（"开关开着、而用户指定要验某一条时，走两步" 与
    # "形式化这条路：一次只核你给的那份源码"）—— 它们讲的是 M 自己怎么派形式化，
    # 而 M 今天只做一件事：用户指定之后派 B。关掉那一档这条路整条不成立（B 那条通道
    # 也做不了形式化），所以那一格按"整行删掉"处理；剩下那一格（"回执怎么读"）
    # 两档都成立，留在原处。
    '**用户要形式化时，你的动作是派 B',
)

#: 关掉 Lean 时「整块删掉」的那些块：`(起点标记, 保留下来的第一行标记)`。
#:
#: 为什么还要有这一档（单行删不够）：纸包六的「形式化那一档的凭据长什么样、谁安排」
#: 是一条跨好几行的项目，而"里面每一行都在讲那条通道"这件事只有整块一起删才成立 ——
#: 删一半会留下一句没有主语的半句话（真机概率不低：那一块的第一行与第二行之间没有空行）。
#: 块尾刻意选在「替代路线那一条」（`「形式化已关闭」那一档的替代路线`）：它正是删掉之后
#: 该走的那条路，所以"删到它之前"＝"留下替代路线"。
NO_LEAN_DROP_BLOCKS: tuple[tuple[str, str], ...] = (
    ('- **形式化那一档的凭据长什么样、谁安排**', '- **「形式化已关闭」那一档的替代路线**'),
)


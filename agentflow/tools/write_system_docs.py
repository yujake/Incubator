"""把十个角色与协作系统各主要组件写成两份给人读的文档。

为什么是生成而不是手写（这是本文件存在的唯一理由）：
角色的职责 / 边界 / 官能轻重 / 边 / 写集 / 动作表 / 工具面，全部已经在代码里有一处真身
（`agentflow.specs.*` 的 `SPEC` 与 `ACTIONS`、`capabilities` 的四张表、`tools.build_registry`）。
手写一份介绍文档，第一次写时是对的，第三次改权限面之后它就变成「看着有、其实在说谎」的文档 ——
而这恰好是 FC-27 那一类事故的形态。所以：

- 文档由代码现算：`python tools/write_system_docs.py`
- 判据 `tests/test_system_docs_are_generated.py` 会重跑一遍并逐字节比
- 组件那一节是手写的表（功能与实现细节没有单一真身），但表里点名的符号
  由同一条判据逐个核存在性：符号没了，文档就红。

用法：
    python -B tools/write_system_docs.py             # 生成 / 更新两份文档
    python -B tools/write_system_docs.py --check     # 只比对（CI 与判据用），不一致 => 退出码 1
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

ROLE_GUIDE = ROOT / "docs" / "ROLE-GUIDE.md"
COMPONENTS_DOC = ROOT / "docs" / "SYSTEM-COMPONENTS.md"

#: 角色的阅读顺序（M 永远最后，它是主控）。
ROLES: tuple[str, ...] = ("A", "B", "C", "D", "E", "F", "G", "H", "V", "L", "M")

#: 官能那七个词的名字（`emphasis` 的键，顺序按从感知到判断）。
FACULTIES: tuple[str, ...] = (
    "眼睛", "耳朵", "脑子", "手", "能讨论", "高观点", "能互动", "能思辨", "敢创新", "有品味",
)

#: 各角色主要读写的文档 / 目录。这一段没有单一真身（它是「东西落在哪」的地图），故手写。
ARTIFACTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "A": (
        ("`data/search_requests.json`", "写", "领跑一条请求、把结局与错误写回该行（claimed / outcome / last_error）"),
        ("`data/literature.json`", "写", "登记文献行（按内容 sha256 幂等）"),
        ("`library/<编号>.pdf` 与 `library/<编号>.txt`", "写", "下载的原文与抽取出的纯文字稿"),
        ("`data/concepts.json` 与 `data/relations.json`", "不写", "抽概念、建关系是 B 的活"),
    ),
    "B": (
        ("`data/statements.json`", "写", "登记命题（含 kind / grade / 判档位那一格）"),
        ("`data/concepts.json` / `relations.json` / `dependencies.json`", "写", "概念、关系、依赖面"),
        ("`data/literature.json`", "写", "给文献补概念与摘要"),
        ("`data/tasks.json`", "只读", "看派给它的活与回执"),
    ),
    "C": (
        ("`data/statements.json`", "只读", "梳理命题之间的链：谁是前提、谁被谁用"),
        ("`data/relations.json`", "只读", "读关系图，找断裂与循环"),
        ("`data/dependencies.json`", "写", "把梳理出的依赖面写回（经秘书代理）"),
    ),
    "D": (
        ("`data/research_questions.json`", "写", "立问题、追进度、记失败原因"),
        ("`data/conjectures.json`", "写", "register_conjecture（D 的主力动作，判重命中即返回既有行）"),
        ("`data/attack_plans.json` 与 `attack_rounds.json`", "写", "攻坚计划与每轮进展"),
        ("`out/review/*.md`", "写", "研究报告"),
    ),
    "E": (
        ("`data/experiments.json`", "写", "数值实验行：脚本、参数、读数、退出码、复现命令"),
        ("`out/exp/*`", "写", "实验产物（脚本与输出）"),
        ("`data/conjectures.json` 与 `statements.json`", "只读", "读被判定的东西；改判档不由 E 做"),
    ),
    "F": (
        ("`out/proofs/*.md`", "写", "证明正文（manuscripts 那套读的正是它）"),
        ("`data/statements.json`", "只读", "确认要证的是哪一条"),
        ("`data/dependencies.json`", "写", "依赖面表格（depsection 解析，V 会核引用）"),
    ),
    "G": (
        ("`out/paper/*.tex` 与 `*.md`", "写", "论文与报告正文"),
        ("`out/paper/ACCEPTANCE.md`", "写", "验收表（P1–P11 逐条判据名 / 结论 / 读数）"),
        ("`data/statements.json`", "只读", "只能引用已签住的结论"),
    ),
    "H": (
        ("`out/review/*.md`", "写", "审稿意见与 G1–G15 门的读数"),
        ("`out/paper/*`", "只读", "被审的稿件（H 只出意见与门读数）"),
        ("`data/*.json`", "只读", "一致性检查（gates.py 的十五道门读这些表）"),
    ),
    "V": (
        ("`data/verifications/<命题号>.jsonl`", "写", "每次审校一行（判决 / 发现项 / 引用核实 / 批注）"),
        ("`out/proofs/*.md`", "只读", "被审的证明正文"),
        ("`data/statements.json`", "只读", "被审命题的档位与依赖"),
    ),
    "L": (
        ("`out/formal/*.lean`", "写", "形式化草稿（formal.formalize）"),
        ("`data/experiments.json`", "写", "形式化那一行（formal.record；写集只有 experiments）"),
        ("检查器（Lean / Coq / Isabelle）", "只读", "formal.check_formal 经桥接层让检查器判"),
    ),
    "M": (
        ("`out/secretary/roster.jsonl` 与 `relay.jsonl`", "写", "名册与转发台账"),
        ("`out/clock/state.json` 与 `wake.json`", "写", "计时器簿记与唤醒标记"),
        ("`out/review/STATUS-*.md`", "写", "状态报告"),
        ("`data/*.json`", "只读", "M 不写领域表：它的写面是编排状态（台账行、取消信号、停止回执）"),
    ),
}

#: 组件表：(名字, 模块, 一句话功能, 实现细节, 主要落点, 守着它的判据)。点名的符号由判据核存在性。
COMPONENTS: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "装配与运行入口",
        "src/agentflow/host.py",
        "把一个角色装配成能跑的东西：注册表、模型缝、工作区、工具面。",
        "build_registry 造工具面（按 roles 过滤）；build_role_registry 按角色裁面；"
        "AGENT_CLASSES 把 specs 里 class_path 指向的实现类实例化；main 是 run-agent 的落点。",
        "读 specs 与 capabilities 与 tools.build_registry；写工作区 data 与 out",
        "tests/test_host_wiring.py",
    ),
    (
        "角色循环",
        "src/agentflow/agent_loop.py",
        "一拍一拍地问模型下一步做什么，把工具调用变成真实副作用并留痕。",
        "run 是主循环：_deliver_mailbox 到 _pump_clock 到 ask_step 到 _do_tool（带 calling_as 身份）到 _park_gate；"
        "每步写一条事件，唤醒与计时走 clock。",
        "读 out/clock/state.json 与 data/tasks.json；写 events.jsonl 与 out/reports",
        "tests/test_agent_loop.py",
    ),
    (
        "编排（主控面）",
        "src/agentflow/conductor.py",
        "M 的那一面：派活、看树、销号、指导、状态报告。",
        "summon 与 summon_many（policy 判边与写集、scheduler 分波并发）、tree 与 stats 与 retire_ready、"
        "guide（沿秘书链逐跳）、reading_snapshot（一拍一份只读台账快照，作用域内写会抛）。",
        "读 data/tasks.json 与 out/secretary；写任务行与板项",
        "tests/test_conductor_tools.py、tests/test_conductor_read_snapshot.py",
    ),
    (
        "秘书（转达层）",
        "src/agentflow/secretary.py",
        "角色之间的传话与登记：名册、板项、转发链、秘书审稿。",
        "roster_view（在飞 / 待机 / 静默三态）、relay_out（逐跳转发，只有链尾读正文）、child_counts、"
        "judge（那次模型调用带稳定头 system）、apply_settlement（结算落盘加回读核对）。",
        "读 data/tasks.json 与 roster.jsonl；写 relay.jsonl 与板项行",
        "tests/test_secretary.py、tests/test_guide_goes_down_the_secretary_chain.py",
    ),
    (
        "时钟",
        "src/agentflow/clock.py",
        "所有的等都在这里：等谁（事件）、等多久（时间）、上限到了怎么办，以及程序（子进程）的生命周期。",
        "TimerBook（out/clock/state.json）；到点判定 = 最小堆加每拍早退；等谁用 waiters_by_target 反查 "
        "加事件消账，再加 30 秒补偿对账；程序用 program_span 与 start_program 与 stop_program。",
        "写 out/clock/state.json 与 wake.json；读 data/tasks.json 判目标收口",
        "tests/test_clock_governs_all_timed_work.py、tests/test_the_clock_scales_with_the_book.py",
    ),
    (
        "存储（表与事务）",
        "src/agentflow/store.py",
        "所有领域表的唯一读写口：加锁顺序、事务、ID 分配、原子落盘、事件流。",
        "tx() 一笔事务（alloc_id 与 upsert 与 delete，提交时追加事件）；_atomic_write（临时文件加改名）；"
        "_load 有进程内缓存（键为路径加 mtime 与大小，写完即清）；LOCK_ORDER 固定加锁顺序。",
        "写 data 下的表、events.jsonl、locks",
        "tests/test_store.py、tests/test_store_load_cache.py",
    ),
    (
        "表结构与词表",
        "src/agentflow/schema.py",
        "磁盘格式的契约：有哪些表、每行必填什么、受控词表取哪些值、版本号是多少。",
        "SCHEMA_VERSION、TABLES、各受控词表（VERDICTS 与 TASK_STATUSES 与 EVIDENCE_KINDS 与 GRADES 与 ITEM_STATES）、"
        "validate()（写入期校验，不过则整笔回滚）。",
        "被 store 与所有写侧读",
        "tests/test_store.py、tests/test_schema_vocabulary.py",
    ),
    (
        "工具层",
        "src/agentflow/tools/base.py",
        "一件工具长什么样：名字、摘要、参数模式、returns、副作用、外部性、roles、调用期角色判据。",
        "ToolSpec（声明）加 ToolRegistry（装配、for_role 结构性过滤、call 调用期判据）；"
        "@tool 装饰器把 handler 与声明绑在一起；只读角色在结构上拿不到写工具。",
        "被装配层与 conductor 与领域工具共用",
        "tests/test_tools_base.py、tests/test_tools_readonly_roles.py",
    ),
    (
        "能力面（矩阵）",
        "src/agentflow/capabilities.py",
        "A–H 调用矩阵的权威定义：谁能叫谁、每个角色能做哪些动作、每个动作写哪几张表。",
        "ALLOWED_EDGES 与 CAPABILITIES 与 WRITE_SETS 与 NON_SUMMONABLE 四张表由 specs 派生；"
        "assert_capabilities（显式调用，导入期不再自动跑）加 param_type_coverage（两层参数对账）。",
        "被 conductor 与 host 与 verify 读",
        "tests/test_capabilities_two_layer.py、tests/test_capabilities_audit_is_explicit.py",
    ),
    (
        "策略",
        "src/agentflow/policy.py",
        "把谁能让谁干活落成可执行的判定：边存在吗、写集冲突吗、参数接缝对不对。",
        "check_edge（forbidden_edge 与 unknown_role 等受控拒绝码）、waves_of（按写集分波并发）、check。",
        "被 conductor.summon 与 summon_many 读",
        "tests/test_policy.py、tests/test_four_dynamic_checks_are_wired.py",
    ),
    (
        "角色声明",
        "src/agentflow/specs/",
        "每个角色的说明书：职责、边界、政策、立场、官能轻重、动作表、边、写集、实现类。",
        "每个 specs 下的模块导出 ACTIONS 与 SPEC（AgentSpec：brief 六格加 emphasis 与 local_notes 与 "
        "edges 与 write_set 与 needs 与 class_path）；specs 包的收表入口把它们收成四张表。",
        "被 capabilities 与 agentspec 与 agent_prompts 读",
        "tests/test_role_specs_complete.py、tests/test_role_specs_appendix_is_live.py",
    ),
    (
        "提示词",
        "src/agentflow/agent_prompts.py",
        "把角色声明、工具面、协作规则渲染成一次调用真正发出去的提示词，并管版本与摘要。",
        "role_prompt_registry（十一格）、prompt_text_problems（只读自检）、PROMPT_VERSION；"
        "稳定前缀（system）与易变事实（task 与台账读数）分开，前者进缓存。",
        "被 llmseam 与 agent_loop 读；被 warm_prompt_cache 预热",
        "tests/test_agent_prompts.py、tests/test_prompt_stability.py、tests/test_prompt_cache_warm.py",
    ),
    (
        "模型缝",
        "src/agentflow/llmseam.py",
        "模型调用的唯一缝：工具面怎么给模型、JSON 怎么解、失败怎么归类、超时怎么算。",
        "LlmSeam.ask 与 ask_json（带 system 与 tools）、ToolFace（ToolSpec 转 function-calling 形态）、"
        "_ROLE_SEAMS（逐角色默认缝，判据之间必须还原）。",
        "被 agent_loop 与各角色 core 读",
        "tests/test_llmseam.py、tests/test_host_wiring.py",
    ),
    (
        "证据链（签）",
        "src/agentflow/verifications.py",
        "一条证明到底签不签得住：判决三词的唯一真身、signs_bit3、引用核实、硬禁令读数。",
        "parse_verdict（落盘四或五格）、signs_bit3（判决加无未解决 error 加引用不挡加 gate 不挡）、"
        "review_standing、proof_review_gap、banned_markers_in（只报不判）。",
        "读写 data/verifications 下的编号文件",
        "tests/test_signing_never_lies.py、tests/test_v_checks_fs_citations.py",
    ),
    (
        "数值与穷举证明",
        "src/agentflow/numericproof.py",
        "数值与穷举那一档证据的判定：档位、上界与枚举量的读数、第三方签字。",
        "exhaustion_verdict（穷举判定）、bound_check（上界对枚举量，只作读数）、third_party_problems（B 的入库闸）、"
        "suspect_self_signed（可疑自签，先报不拦）。",
        "读写 data/experiments.json 的证据字段",
        "tests/test_t0_tier_and_exhaustion_proof.py、tests/test_b_third_party_signature_gate.py",
    ),
    (
        "收工门",
        "src/agentflow/closing.py",
        "一次运行能不能说完成：八格逐格三态加内容级验收读数。",
        "check_closing 跑 DEFAULT_CHECKS 八格（每格兜异常，抛了记 unknown 加原因）；"
        "ClosingReport（can_close 只在全过为真）；tri_state_exit_code（0 或 1 或 2）。",
        "读 data 与 out/paper；CLI closing",
        "tests/test_closing_gate.py、tests/test_a_crashed_cell_is_unknown_not_a_traceback.py",
    ),
    (
        "门引擎",
        "src/agentflow/gates.py",
        "H 的 G1 到 G15：每道门一个函数、独立、可单独查询。",
        "GATE_IDS 与 run_all_gates 与 gate_verdict（fails 优先于 unknowns 优先于 missing 优先于 nas 优先于 accepted）："
        "不齐的检查集判 unverified，不许读成全绿。",
        "读被审文档与台账（只读）",
        "tests/test_gates.py、tests/test_coverage_gates.py",
    ),
    (
        "文献链",
        "src/agentflow/litstage.py",
        "文献从候选到入库的流水线：待新增列表三态、提交闸、重复登记、同槽补 relevance。",
        "admission_plan（require_judged：没判完整批一条都不许入库）、overlap_check（同槽补 relevance）、"
        "apply_settlement（结算加提交后回读核对）。",
        "写 data/literature.json 与 data/lit_candidates.json",
        "tests/test_pending_list_is_three_state.py、tests/test_literature_match.py",
    ),
    (
        "手稿与论文",
        "src/agentflow/manuscripts.py",
        "证明正文与论文的落盘形态，以及把 out/paper/main.tex 编成 PDF。",
        "manuscripts（write 与 row_of 与 read_rows，带解析缓存）、depsection（四列依赖表解析）、"
        "papermapping（论文到命题的对应表）、papercompile（xelatex 三遍，失败分类）。",
        "写 out/proofs 与 out/paper",
        "tests/test_manuscript_handoff.py、tests/test_paper_pack.py",
    ),
    (
        "读数与网页",
        "src/agentflow/readouts.py",
        "把台账读成给人看的读数（CLI stats、status-report、网页十页）。",
        "readouts.scan（一次读盘，四份读数共用）、errors 与 flow 与 cost 与 gates 四切面；"
        "webui 的 readers 与 writes（POST 端点，CSRF 与回环来源校验）。",
        "只读 data 与 out；写 out/review",
        "tests/test_readouts_are_the_single_shape.py、tests/test_webui_reads_nothing_else.py",
    ),
    (
        "命令行入口",
        "src/agentflow/cli.py",
        "四组入口（incubate / inspect / run / serve）加 28 个子命令的薄壳。",
        "build_parser（热调 5 到 7 毫秒）、main（把异常翻成退出码）、_envelope_state（读数外壳的三态）；"
        "命令实现都在别的模块，CLI 只做转发与打印。",
        "读所有模块；不写领域数据",
        "tests/test_cli_grouped_entry_points.py、tests/test_cli_json_contract.py",
    ),
    (
        "会话与错误统计",
        "src/agentflow/sessions.py",
        "把这一趟发生了什么读出来：会话记录、错误动作分类、成本。",
        "read_all_sessions（唯一会话读口）、compute_run_index（一次读盘算索引）；"
        "errorstats 的 error_action_stats 与 error_action_stats_from（吃已读记录）。",
        "只读 out/sessions 与 events.jsonl",
        "tests/test_run_index.py、tests/test_one_session_reader.py",
    ),
)


def _registry() -> Any:
    """工具面按 Lean 开档算，与环境无关（否则同一棵树能生成两份不同的文档）。

    为什么钉死开档：Lean 关着时 L 这一格不存在（`leanscope.LEAN_ONLY_ROLES`），
    于是文档会少一整节 —— 而"少一节"与"这一节写错了"在 diff 里长得一样。
    十一格是完整面；关档少的只是 L 那一格，读者看 L 那一节开头的说明即可。
    钉死在这里而不是靠调用方的环境变量：判据在 pytest 里跑、人在终端里跑，
    两处的 env 不一定一样（实测踩过：两次生成差了 30 件工具面）。
    """
    import os

    os.environ.setdefault("AGENTFLOW_LEAN_ENABLED", "1")
    from agentflow.tools import build_registry

    return build_registry().registry


def _tool_rows(registry: Any, role: str) -> list[tuple[str, str, str, str]]:
    rows = []
    for spec in sorted(registry.for_role(role), key=lambda s: s.name):
        params = (spec.params or {}).get("required") or ()
        rows.append((
            spec.name,
            " ".join(str(spec.summary or "").split()),
            str(spec.side_effect or ""),
            "、".join(f"`{p}`" for p in params) or "（无）",
        ))
    return rows


def _action_rows(role: str) -> list[tuple[str, str, str, str]]:
    from agentflow import capabilities as C

    rows = []
    for act in C.CAPABILITIES.get(role) or ():
        params = (act.params or {}).get("required") or ()
        rows.append((
            act.action,
            " ".join(str(act.summary or "").split()),
            str(act.side_effect or ""),
            "、".join(f"`{p}`" for p in params) or "（无）",
        ))
    return rows


def _role_section(role: str, registry: Any) -> list[str]:
    from agentflow import capabilities as C
    from agentflow import specs as SP

    spec = SP.builtin_specs()[role]
    brief = spec.brief
    lines: list[str] = [f"## 角色 {role}", "", "### 角色设定", "", f"**{brief.duty}**", ""]
    if getattr(brief, "deliverable", ""):
        lines.append(f"- 交付物：{brief.deliverable}")
    if getattr(brief, "signature_error", ""):
        lines.append(f"- 一眼可辨的错：{brief.signature_error}")
    for label, values in (
        ("立场", getattr(brief, "stance", ())),
        ("政策（这一岗的规矩）", getattr(brief, "policy", ())),
        ("边界（不许越的线）", getattr(brief, "boundary", ())),
    ):
        if values:
            lines.append(f"- {label}：")
            lines += [f"  - {v}" for v in values]
    caps = [f"{k}＝{v}" for k, v in (spec.emphasis or {}).items() if k in FACULTIES]
    if caps:
        lines.append(f"- 官能轻重：{'；'.join(caps)}")
    lines += ["", "### 具体职责（动作表）", "", "| 动作 | 做什么 | 副作用 | 必填参数 |", "|---|---|---|---|"]
    rows = _action_rows(role)
    for name, summary, se, need in rows:
        lines.append(f"| `{name}` | {summary} | `{se}` | {need} |")
    if not rows:
        lines.append("| （无声明动作） | — | — | — |")
    out_edges = sorted(C.ALLOWED_EDGES.get(role) or ())
    in_edges = sorted(r for r, tgt in C.ALLOWED_EDGES.items() if role in (tgt or ()))
    lines += [
        "",
        "### 协作面",
        "",
        f"- 能召唤：{'、'.join(out_edges) if out_edges else '（谁都不叫：这一岗只做自己的那份）'}",
        f"- 谁能召唤它：{'、'.join(in_edges) if in_edges else '（没人：它是入口，或只由用户点名）'}",
        f"- 可被召唤：{'是' if spec.summonable else '否（在 NON_SUMMONABLE 里，只能由用户点名或流程直接进入）'}",
        f"- 写集（能改哪些表）：{'、'.join(sorted(spec.write_set)) or '（不写任何表）'}",
        "- 与谁怎么说话：只走秘书链（conductor.guide 逐跳转发，中间各跳不看正文；"
        "平级之间没有直连通道，回话也经秘书落到板项上）",
    ]
    if getattr(spec, "needs", ()):
        lines.append(f"- 依赖的缝：{'、'.join(spec.needs)}")
    tools = _tool_rows(registry, role)
    lines += [
        "",
        "### 工具面（这个角色实际拿到的件）",
        "",
        "| 工具 | 做什么 | 副作用 | 必填参数 |",
        "|---|---|---|---|",
    ]
    for name, summary, se, need in tools:
        lines.append(f"| `{name}` | {summary} | `{se}` | {need} |")
    lines += ["", f"共 **{len(tools)}** 件（声明在 src/agentflow/tools/；只读角色在结构上拿不到写工具）。", ""]
    lines += ["### 主要读写的文档与细节", "", "| 路径或落点 | 读还是写 | 细节 |", "|---|---|---|"]
    for path, rw, detail in ARTIFACTS.get(role, ()):
        lines.append(f"| {path} | {rw} | {detail} |")
    lines += ["", "---", ""]
    return lines


def render_role_guide() -> str:
    from agentflow import capabilities as C

    registry = _registry()
    total_actions = sum(len(C.CAPABILITIES.get(r) or ()) for r in ROLES)
    total_tools = sum(len(_tool_rows(registry, r)) for r in ROLES)
    lines = [
        "# 角色指南（十个角色 + 主控）",
        "",
        "> 这份文件是生成物：python tools/write_system_docs.py 由代码现算（职责与边界与官能与边与写集与动作表与"
        "工具面全部取自 specs、capabilities 与 tools.build_registry）。",
        "> 改了角色面却没重生成，tests/test_system_docs_are_generated.py 当场红。",
        "> 规格（判据）看 ROLE-SPECS.md；这份是给人读的介绍，两者不许互相替代。",
        "> 工具面按 **Lean 开档（十一格）** 现算；关档时少的只是 L 那一格（它开头写着这一个前提）。",
        "",
        "## 这套系统怎么分工",
        "",
        "十个角色分三层：主控 M（派活、看树、收工）→ 执行层 D / E / F / G / H（研究、实验、证明、写作、审稿）"
        "→ 支撑层 A / B / C / V / L（文献、登记、串链、签、形式化）。",
        "",
        "角色之间没有直连通路：想叫谁干活就走 conductor.summon（受 ALLOWED_EDGES 约束）；"
        "想给谁说句话就沿秘书链逐跳转发（中间各跳不看正文）。",
        "",
        f"角色数 **{len(ROLES)}**｜动作总数 **{total_actions}**｜工具面合计 **{total_tools}** 件"
        "（同一件工具可被多个角色拿到，故合计大于总件数）。",
        "",
    ]
    for role in ROLES:
        lines += _role_section(role, registry)
    return "\n".join(lines).rstrip() + "\n"


def render_components() -> str:
    from agentflow import schema as S

    lines = [
        "# 协作系统的主要组件",
        "",
        "> 这份文件是生成物：python tools/write_system_docs.py。组件表是手写的（功能与实现细节没有单一真身），"
        "但每条点名的模块与符号由 tests/test_system_docs_are_generated.py 逐个核存在性。",
        "",
        "## 一次运行里，谁按什么顺序动",
        "",
        "```",
        "用户 -> cli / host（装配） -> agent_loop（角色循环）",
        "                            |- llmseam（问模型，带工具面与提示词）",
        "                            |- tools（模型挑的工具，带 calling_as 身份）",
        "                            |    |- store（事务写）加 schema（校验）",
        "                            |    |- conductor（派活 / 销号 / 指导）-> policy（判边）",
        "                            |    |- clock（等谁 / 等多久 / 程序生命周期）",
        "                            |    +- secretary（名册 / 板项 / 转发）",
        "                            +- closing（收工门八格）-> gates（H 的十五道）",
        "事后：readouts / webui / cli stats（只读）、sessions 加 errorstats（回看）",
        "```",
        "",
        f"领域表共 **{len(S.TABLES)}** 张（data 目录），磁盘格式版本 schema.SCHEMA_VERSION。",
        "",
        "## 组件逐个说",
        "",
        "| 组件 | 模块 | 功能（一句话） | 实现细节 | 主要落点 | 守着它的判据 |",
        "|---|---|---|---|---|---|",
    ]
    for name, module, what, how, where, judge in COMPONENTS:
        lines.append(f"| **{name}** | `{module}` | {what} | {how} | {where} | `{judge}` |")
    lines += [
        "",
        "## 三条贯穿全局的设计",
        "",
        "1. 三态：每个读数都有 checked 与 reason，没查成与查过了没问题 是两件事；折平是本仓反复踩过的坑。",
        "2. 单一真身：同一件事只许一处实现（capabilities 是调用矩阵的真身、verifications 的判决词真身、"
        "secretary.row_axis 是这一行是代理还是板项 的真身、store.tx 是写口的真身），"
        "其余处要么转发、要么由判据钉住逐字相同。",
        "3. 判据先行：每条约束都有一个 tests 文件钉住；改行为而没改判据就红，改判据而没写理由会在 review 里被问。"
        "这份文件自己就是这条的产物（生成加比对）。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _write(path: pathlib.Path, text: str, *, check: bool) -> bool:
    old = path.read_text(encoding="utf-8") if path.is_file() else None
    if check:
        return old == text
    path.write_text(text, encoding="utf-8", newline="")
    return old == text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 docs/ROLE-GUIDE.md 与 docs/SYSTEM-COMPONENTS.md")
    ap.add_argument("--check", action="store_true", help="只比对不写盘（不一致 => 退出码 1）")
    args = ap.parse_args(argv)
    pairs = ((ROLE_GUIDE, render_role_guide()), (COMPONENTS_DOC, render_components()))
    bad = []
    for path, text in pairs:
        same = _write(path, text, check=args.check)
        state = "一致" if same else ("需重生成" if args.check else "已写入")
        print(f"  {path.relative_to(ROOT).as_posix()}：{state}（{len(text)} 字符）")
        if args.check and not same:
            bad.append(path.name)
    if bad:
        print("  不一致：" + "、".join(bad) + " => 跑 python -B tools/write_system_docs.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

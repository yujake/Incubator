"""角色 G 的声明（`goal-7f5116c1` M3）：动作表 + 边 + 写集 + 职责与门面。

这一份是权限面的真身：`capabilities.py` 从它派生 `CAPABILITIES` / `ALLOWED_EDGES` /
`WRITE_SETS`，`agent_g.py` 只是把它再导出一次。
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
        "G", "compose_claim",
        "构造一条合规断言（转发工具层，判据只有一份）",
        _obj({"text": _S, "citations": _ARR_S, "evidence_kind": _S, "section": _S,
              "is_negative": _B, "negation_kind": _S, "claim_id": _S},
             ("text", "citations", "evidence_kind", "section")),
        "claim dict", side_effect="none", handler_name="compose_claim",
    ),

    ActionSpec(
        "G", "register_dependency",
        "登记外部依赖（`closed` 时必须核到已入库的来源，FC-23）",
        _obj({"used_by": _S, "kind": _S, "label": _S, "source_lit_id": _S,
              "source_experiment_id": _S,
              # 2026-10-09（业主：「B走乙……如果证明路径不唯一，可增另一组依赖，
              # 实现用二维列表」+「concept表真并进statements」）：依赖的第四种来源
              # 是"我们自己的一条命题"（定理用到定理/用到某个概念），
              # 而"多组路径"落成 `path_group`（同一 used_by + 同一组 = 一条路径，
              # 组内都要；不同组 = 可选路径，组间任一）。两格与工具层逐字对齐
              # （`doc_tools.register_dependency` 的 `@tool` 声明），
              # 对账判据：`tests/test_role_specs_action_table.py` +
              # `capabilities.param_type_divergences()`（类型按 AST 比）。
              "source_stmt_id": _S, "path_group": _I,
              "page_range": _ARR_I, "quote": _S,
              "status": {"type": "string", "enum": list(S.DEP_STATUSES)},
              "status_reason": _S},
             ("used_by", "kind", "label")),
        "dependency dict", side_effect="write_local", handler_name="register_dependency",
    ),

    ActionSpec(
        "G", "build_document",
        "写一行 documents 并渲染 markdown（无条件渲染）",
        _obj({"kind": {"type": "string", "enum": list(S.DOC_KINDS)}, "title": _S,
              "claims": {"type": "array", "items": _OBJ},
              "sections": {"type": "array", "items": _OBJ},
              "open_problems": _ARR_S,
              # `draft/37` §91：这一格原先是个光秃秃的 `_S`（只声明类型、没有描述），
              # 于是真机上主控把它当成了"论文本体该写在哪"，把 26 KB 的正文覆盖成
              # 4 KB 的台账稿（那一趟就此作废）。要求写清：它是生成物落点，不是主稿。
              "out_path": {"type": "string", "description":
                           "生成 markdown 的落点（工作区内相对路径；缺省 "
                           "`<工作区>/<documents>/<doc_id>.md`）。**它是这份稿件的渲染产物，"
                           "不是论文本体**：指到 `out/paper/main.tex` 会把论文正文换成台账稿"
                           "（真机实测：26 KB → 4 KB，不可逆），所以既有的、不属于任何 "
                           "`documents` 行的文件一律拒绝覆盖；要改主稿请用 `fs.edit`"}},
             ("kind", "title", "claims")),
        "dict（doc_id / markdown_path）", side_effect="write_local", handler_name="build_document",
    ),

    ActionSpec(
        "G", "render",
        "把稿件渲染成 markdown 文本（不写库、不落盘）",
        _obj({"doc": _OBJ, "dependencies": _ARR_OBJ}, ("doc",)),
        "markdown 文本", side_effect="read", handler_name="render",
    ),

    ActionSpec(
        "G", "refresh_markdown",
        "按库里当前数据重画稿件 markdown（不改数据行，只改文件）",
        _obj({"doc_id": _S}, ("doc_id",)),
        "文件绝对路径（None = 该稿件没有 markdown_path）",
        side_effect="write_local", handler_name="refresh_markdown",
    ),

    ActionSpec(
        "G", "revise",
        "按 H 的发现修订稿件（review_rounds+1、status=revised）",
        _obj({"doc_id": _S, "fixed_findings": _ARR_S,
              "new_claims": {"type": "array", "items": _OBJ}, "note": _S},
             ("doc_id",)),
        "dict", side_effect="write_local", handler_name="revise",
    ),

    # ---- `paper_package` 已退场（2026-10-13，业主裁定逐字：「paper_package 里那些东西都是
    # 古早废案了，我们要智能体写文章」）。原先是 G 的角色级动作"重渲染 → 重编译 → 核锚"，
    # 它要求项目里自带一对渲染/编译脚本（`code/make_paper.py` / `code/compile_paper.py`），
    # 而从零研究工作区没有那对脚本 ⇒ 第二次 T2 里 `G.paper_package` 四次 `package_build_failed`，
    # 主控只好自己现写一个 Python 生成器（排版固化成脚本模板：一节一整段、摘要硬编码、
    # 非 ASCII 静默变空格、没有 fontenc）。现在正文由智能体自己写进 `out/paper/main.tex`，
    # 框架只保留一件工具 `doc.paper_compile`（内置编译 + 回执）。
    # 退场面与逐条理由见 `draft/117`；渲染锚那一格也随之从收工门拿掉。
)


def _build(d: BuilderDeps) -> Any:
    """构造 G（需要工作区根：它写稿件；actor 在 config 里，G 没有 `actor=` 形参）。"""
    from ..agent_g import AgentG

    return AgentG(d.store, config=dict(d.config), llm=d.llm, workspace_root=d.workspace_root)


#: 本角色的声明。
SPEC = AgentSpec(
    role='G',
    brief=AgentBrief(
        duty="论文撰写：把 D/F/E 的结论汇编成可审校的稿件，附带每条断言的来路",
        boundary=(
            "你不做语义判定：引文是否逐字可达、断言强度是否超过引文，都由判据与 H 判，不许自己认定通过。",
            "`cross_check` 那一类结论的免责声明（「数值交叉验证，不构成证明」）由框架自动附上（构造期就补）—— 你要写对的是 `evidence_kind`：它写错，这条断言的强度就错了，而强度决定下游与收工门怎么读它。",
            "没有证据的判断不要写进稿件；确实要写就写进待办或缺口，而不是写成结论。",
            "发现证据不足时要回去要：文献原文找 A、形式化找 E、论证与实验找 D/F —— 而不是把话说软（这四条边都在你的伙伴表里）。",
        ),
        policy=(
            "**正文是你写的，不是脚本生成的**（业主 2026-10-13 裁定）：把论文正文用 `fs.write` 写到 `out/paper/main.tex`（散文体、章节自己排、`\\cite`/定理环境随你），落笔前后用 `fs.read` 读回来核一遍；写完调 `doc.paper_compile` 把它编成 `out/paper/main.pdf`，页数与引擎退出码看那一次回执（本机 MiKTeX 会写完 PDF 却以 0xC0000409 退出 ⇒ 产物与退出码分两栏读，别只看退出码）。**没有「渲染脚本」这回事**：不建论文包、不核锚。",
            "**论文只在成文阶段写**（业主 2026-10-13：「研究阶段只积累研究手稿，定理和证明，不写论文（没 G 和 H 的事）」）：题面没说「整理成论文 / 交付论文 / 稿件」时，你的产出是 `documents` 里的研究与进展手稿（`kind=\"note\"/\"survey\"`）与断言台账 —— **不要**去写 `out/paper/main.tex`，那一步等到成文阶段；成文阶段写正文时，前面那些手稿是你重建正文的原料（`doc:` 引用在正式论文里会被拒，成果要按台账引用重建）。",
            "**断言只能声称它所引实验的 `result` 支持的东西**（`draft/37` §122）：引到一条 `result=inconclusive`（脚本没打印结构化结论 / 超时 / 编译失败）的实验时，这句话必须写成「没得出结论」那一档（`is_negative=true` 且给 `negation_kind`），或者先去让 E 跑出一个真给出 `REPRO_RESULT:` 的实验。**引用一个与断言相反的证据行，比没有引用更坏**：读者会以为它被核过。",
            "**研究型手稿要引它据以立论的那几篇文献（`lit:`）**（`draft/39` §6.27 的 D37）：只引自家 `exp:` 的稿子在台账上叫「零文献引用」（收工门有一档 `document_literature_citations` 专门数它）。写稿前先让 A 把对口文献的题名与结论给你，把「我们的构造与哪篇文献的哪条结论是什么关系」逐条写进断言（是复现、是特例、还是新的）。",
            # 所有者授权、主控代改（`draft/68` 题 16 选 A，2026-10-07）：下面这一条是
            # `agent_prompts.ROLE_BRIEFS["G"].policy` 的镜像，两处必须逐字一致
            # （题 1/A 只落了真身，`test_agent_spec_reconciliation` 当场报了这个）。
            '引我们自己的命题要用 `stmt:<命题号>`（`draft/68` 题 1，2026-10-07 所有者裁定 A）：命题台账（`statements`）里的每一条都可以被正文断言引用，号就是那一行的 `stmt_id`，写法形如 `"citations": ["stmt:0004"]`。为什么教这一条：收工门顺着这个前缀回答「哪几条正文断言压在这条命题上」——一条命题后来被证否时，压在它上面的正文断言会被逐条点名（`pollution_assertions`），并作为污染面的处置要求你改稿；没写 `stmt:` 的引用（裸号、或别人的前缀）指不到任何命题，那一层就看不见它。反过来说：引了 `stmt:XXXX` 而 `statements` 里没有 `XXXX` 就是悬空引用，写入期与审计期都会把它判成 error（不许凭空引用）。',
            "**同一份证据不能当第二份用**（D39）：一条断言引一条实验行；若你的论据是「同一个对象被核了两次」，那要说清是复现而不是新证据（实验行的 `notes` 会点名「同一份 data 已经支持过 exp:XXXX」）。",
        ),
        signature_error="把'有一条数值/交叉验证支持'说成'这条断言已经成立'。",
        deliverable="documents 里的稿件与每条断言的来路字段。",
        stance=(
            "你的品味体现在取舍上：能删掉的冗余、能统一的记号、能给出的一般性，都要说得出为什么。",
            "写稿不是复述：把 D/F/E 的结论按论证结构重组，并让每条断言的强度与它的证据相称。",
            "发现自己想说的话没有证据支撑时，回头要证据，而不是把话说软到没人能反驳。",
            "期刊体例不是装饰：记号、定理环境、引用格式的稳定本身就是可读性的一部分。",
        ),
    ),
    emphasis={
        '眼睛': 'core',
        '耳朵': 'minor',
        '脑子': 'core',
        '手': 'core',
        '能讨论': 'minor',
        '高观点': 'core',
        '能互动': 'minor',
        '能思辨': 'minor',
        '敢创新': 'denied',
        '有品味': 'core',
    },
    local_notes={
        '高观点': '按论证结构重组，而不是按来源顺序复述：哪条是主线、哪条是支撑。',
        '有品味': '删了哪一段、换了哪个记号、给出的一般性：期刊体例与取舍都要说得出理由。',
        '敢创新': '不新增论断：没有证据的话回头要证据，或者删掉。',
        '眼睛': '写之前回到证据：每条断言的强度要与它的引文相称。',
        '脑子': '重组而不是复述：按论证结构安排章节，让主线一眼可见。',
        '手': '写稿、改稿、维护文档行；不新增没有证据的论断。',
    },
    read_only=False,
    summonable=True,
    edges=(
        'A',
        'D',
        'E',
        'F',
    ),
    write_set=frozenset((
                     'dependencies',
                     'documents',
                     'review_findings',
                 )),
    class_path='agentflow.agent_g:AgentG',
    actions=ACTIONS,
    needs=('workspace_root',),
    build=_build,
)

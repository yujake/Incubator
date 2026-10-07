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
              "source_experiment_id": _S, "page_range": _ARR_I, "quote": _S,
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

    # ---- `paper_package`（2026-10-03 加；**本文件是 FC-27 禁改区，本次改动已登记基线待 2 名人审**）
    #
    # 为什么必须有它（`draft/37` §58/§59 的真机读数）：第九趟主控把正文改动落盘、九节报告过门，
    # 只剩 `anchor` 一格 —— 而"重渲染 + 重编译 + 核锚"这三件事是**工具**
    # （`doc.paper_render` / `doc.paper_compile` / `doc.paper_state`），
    # **没有任何动作**能召唤它们：主控连派三次 `G.revise` 都没用
    # （`revise` / `refresh_markdown` / `render` 动的都是稿件 markdown，不是论文包）。
    # 于是"锚回到 consistent"在编排层结构上做不到 —— 与 §44.4（A/B 缺登记动作）同形。
    #
    # 两根轴逐条读出：
    #   - 效果轴 `write_local`：它真的改盘（渲染出的 `appendix.tex` / `tables/*.tex`、
    #     重编的 `main.pdf`、重写的锚与回执）。
    #   - 外部轴 `exec`：渲染与编译都会**起子进程**（项目脚本 / LaTeX 工具链）——
    #     与 `verify.run_experiment` 同一档；不标 `egress`（它不出网）。
    ActionSpec(
        "G", "paper_package",
        "一次做完论文包的重渲染 → 重编译 → 核锚，并回报 verdict 与漂移条数",
        _obj({"project": _S, "timeout_sec": _N, "render_script": _S, "compile_script": _S}),
        "dict（render / compile / verdict / dimensions / drift / problems / anchor_path）",
        side_effect="write_local", handler_name="paper_package",
        external="exec",
    ),
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
            "交叉验证类结论必须带框架约定的免责声明常量（逐字符一致，不要手写近义句）。",
            "没有证据的判断不要写进稿件；确实要写就写进待办或缺口，而不是写成结论。",
            "发现证据不足时要回去要：文献原文找 A、形式化找 E、论证与实验找 D/F —— 而不是把话说软。（`G → A` 这条边 2026-09-30 由人批准加上，见 `draft/28` §199。）",
        ),
        policy=(
            "改完稿要让**包**跟上，不是只让台账跟上：修订落进 `documents` 之后，调 `doc.paper_render` 重渲染、`doc.paper_compile` 重编译，再用 `doc.paper_state` 读一次锚 —— 只把修订写进 documents、没重渲染，锚就会报 `drifted`，而交付定义第 1 条要求 0 漂移 ⇒ 那样的修订等于没交付。渲染与编译都要看工具给的读数（标记是否齐全、receipt 是否本次），不看编译器退出码。",
            "**断言只能声称它所引实验的 `result` 支持的东西**（`draft/37` §122）：引到一条 `result=inconclusive`（脚本没打印结构化结论 / 超时 / 编译失败）的实验时，这句话必须写成「没得出结论」那一档（`is_negative=true` 且给 `negation_kind`），或者先去让 E 跑出一个真给出 `REPRO_RESULT:` 的实验。**引用一个与断言相反的证据行，比没有引用更坏**：读者会以为它被核过。",
            "**研究型手稿要引它据以立论的那几篇文献（`lit:`）**（`draft/39` §6.27 的 D37）：只引自家 `exp:` 的稿子在台账上叫「零文献引用」（收工门有一档 `document_literature_citations` 专门数它）。写稿前先让 A 把对口文献的题名与结论给你，把「我们的构造与哪篇文献的哪条结论是什么关系」逐条写进断言（是复现、是特例、还是新的）。",
            # 所有者授权、主控代改（`draft/68` 题 16 选 A，2026-10-07）：下面这一条是
            # `agent_prompts.ROLE_BRIEFS["G"].policy` 的镜像，两处必须逐字一致
            # （题 1/A 只落了真身，`test_agent_spec_reconciliation` 当场报了这个）。
            '引我们自己的命题要用 `stmt:<命题号>`（`draft/68` 题 1，2026-10-07 所有者裁定 A）：命题台账（`statements`）里的每一条都可以被正文断言引用，号就是那一行的 `stmt_id`，写法形如 `"citations": ["stmt:0004"]`。为什么教这一条：收工门顺着这个前缀回答「哪几条正文断言压在这条命题上」——一条命题后来被证否时，压在它上面的正文断言会被逐条点名（`pollution_assertions`），并作为污染面的处置要求你改稿；没写 `stmt:` 的引用（裸号、或别人的前缀）指不到任何命题，那一层就看不见它。反过来说：引了 `stmt:XXXX` 而 `statements` 里没有 `XXXX` 就是悬空引用，写入期与审计期都会把它判成 error（不许凭空引用）。',
            "**同一份证据不能当第二份用**（D39）：一条断言引一条实验行；若你的论据是「同一个对象被核了两次」，那要说清是复现而不是新证据（实验行的 `notes` 会点名「同一份 data 已经支持过 exp:XXXX」）。",
        ),
        signature_error="",
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

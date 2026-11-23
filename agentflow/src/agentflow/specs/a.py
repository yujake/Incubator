"""角色 A 的声明：动作表 + 边 + 写集 + 职责与门面 + 检索式教法。

这一份是权限面的真身：`capabilities.py` 从它派生 `CAPABILITIES` / `ALLOWED_EDGES` /
`WRITE_SETS`，`agent_a` 包只是把它再导出一次。
所以本文件在 `.noai-paths` 里受保护（改它等于改权限面 ⇒ 需要 2 名人审）；
与派生表逐格一致的判据见 `tests/test_agent_spec_reconciliation.py` 与
`tests/test_capabilities_two_layer.py`。

`SEARCH_STYLE` 是「A 的检索式怎么给」那一段的正文（段名 `A_SEARCH_STYLE`，号由
`promptkit.SECTION_ORDERS` 集中分配）。它 2026-11-22 从 `presets/a/blocks/search_style.md`
逐字搬来：预设那套「写死的块由哪段文件给」的机制只有 A 一个用户（别的角色都在本文件
一族里写死），所以退役机制、正文回到它该在的地方 —— 与 A 的 policy / boundary 同族。
判据 `tests/test_presets_retired.py::test_a_search_style_is_registered_from_the_spec`
钉住它仍进 A 的提示词，且别的角色一个字都不多。
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

#: A 的「检索式怎么给」那一段的正文（段名 `A_SEARCH_STYLE`，order 2000：工具指引之后、
#: 证据契约之前）。它是一条一条真机读数换来的做法，与 `SPEC.brief.policy` 那一族是同一类
#: 东西（写给模型的正文），所以住在 A 的声明文件里，而不是外挂一份数据文件。
#:
#: 落点只有一处：`agent_prompts.role_prompt_registry` 在 A 那一档把它注册成独立段。
#: 它不进 `SPEC.brief.policy`：policy 那几格渲染在 order 500、带「这次运行的政策：」的
#: 抬头，而这一段是 order 2000 的独立块 —— 搬进 policy 会改渲染出来的字节（位置与抬头
#: 都变），而这一笔的验收是「十一格逐字节不变」。
#:
#: 正文逐字搬自 `agentflow/presets/a/blocks/search_style.md`（884 字节，尾随一个换行由
#: 渲染层以前用 `strip("\n")` 去掉；这里常量本身就是去掉之后的 883 字节）。
#: 那段正文此前只对 A 生效（随包预设只有 `a/` 这一份），所以它一直是 A 的私有教法，
#: 不是一套可替换的部署面。
SEARCH_STYLE: str = (
    "你这一岗的检索式怎么给（每一条都有真机读数支撑，不是风格偏好）：\n"
    "\n"
    "- 后端以英文文献为主：`topic` 里要带英文关键词。纯中文题面会被挡在门外，返回\n"
    "  `query_not_applicable` —— 那个码的意思是「这一问没发出去」，不是「没有这篇文献」。\n"
    "  把英文检索式写进 `description` 也能让它适用。\n"
    "- `topic` 要短：按题名找原文就只给题名（必要时加年份），不要把作者与一串关键词串成长句 ——\n"
    "  precise 那一档带关键词后置过滤，词袋越长越容易被整批滤掉（实测：同一后端，短题名一次命中\n"
    "  9 条，长串 5 次里 4 次 `no_results`）。找不到再换 topical，或换关键词重试。\n"
    "- 判「不相关」与判「不存在」是两件事：你可以说这一条候选没进结果，不许说这篇文献不存在。"
)

#: 本角色的动作表（从 `capabilities.py` 逐字搬来）。
ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        "A", "run_once",
        "领取一条待办检索请求并跑完（搜索 + 登记文献 + 下载）",
        # 2026-11-21（PA2 规矩 2）：`request_ids` 是实现的真形参（`AgentA.run_once(self, *,
        # request_ids=None)` → `_claim_pending` 用它点名要认领的委托），也是产品自己的
        # 收工门拒信在教的那一格（`closing._check_literature_pending` / `litstage.
        # pending_scope_note` 逐字写「不给 `request_ids` 就认领全部有 pending 的委托」），
        # 但声明面此前漏了它 ⇒ 经参数门照那句话写会被判未声明键。补声明，不改实现。
        _obj({"request_ids": {**_ARR_S, "description": (
            "只认领这几个委托号（`lit_candidates` 里还有 `pending` 的那几个）；"
            "不给 ⇒ 认领全部有 pending 的委托（队列里没有可领的检索请求时这一格也生效）")}}),
        "ARunResult（`to_dict()` 的键：processed / registered / duplicated / downloaded / "
        "outcome / request_id / queue_pending / report_path …；`claimed` 只是属性、不在 "
        "`to_dict()` 里）",
        side_effect="write_local", handler_name="run_once",
        external="egress",
    ),

    ActionSpec(
        "A", "run",
        "连续领跑到没有可领的请求为止（有界：max_requests）",
        _obj({"max_requests": {**_I, "minimum": 1}}),
        "汇总 dict（processed / registered / …）",
        side_effect="write_local", handler_name="run",
        external="egress",
    ),

    # ---- `search_literature`
    # 为什么必须有它：上面两个动作的参数里没有主题（只认队列里已有什么），召唤方没办法告诉 A 要查什么。
    # 名字不叫 `search`：两层对账按"工具名最后一段 == handler_name"配对，`fs.search` / `table.search`
    # 会让它落进 `ambiguous`，而导入期第 [7b] 条要求 `ambiguous` 为空。
    # 两根轴：效果轴 `write_local`（一个事务写 `search_requests`，随后 `run_once` 链路再写
    # `search_requests` + `literature`，与 `WRITE_SETS["A"]` 同一组表）；外部轴 `egress`（真发 HTTP）。
    # 不给 `run_once` 加 topic 参数：那会把"消费队列"（谁都能调）与"生产队列"（受在途上限约束）合成
    # 一个动作，想要"只消费"的调用方也会被迫接受"可能新建请求"的副作用。
    ActionSpec(
        "A", "search_literature",
        "按主题现查一次：入队（过 I7 准入闸门）→ 领跑 → 把候选与来源交回召唤方；"
        "收进 `literature` 的那批接着派 B 的 `run_once` 整理",
        _obj(
            {
                "topic": {**_S, "minLength": 1, "maxLength": 400},
                # 缺省 `precise`（实现在 `AgentA.search_literature`）：这一个动作
                # 服务的是"给我这条命题的来源"，词袋式的 `topical` 在这个语义下
                # 对题率很低。要领域全景就显式传 `broad` / `topical`。
                "mode": {"type": "string", "enum": list(S.SEARCH_MODES)},
                "description": _S,
                # 工具面 `search.literature` 早有 `providers`（一次问多源），动作面没有 ⇒
                # 编排层看不见这个入口。只搬形状、不搬名单：
                # 工具面那格还带 `enum` / `minItems` / `maxItems`，这里一格都不抄（可用源的真身是
                # `providers.build_providers` 的名单 + 调用方注入的实例，抄一份就是第二个要同步的地方），
                # 所以只声明 array<string>。这一对的形状一致没有导入期判据看着（两层类型对账落进
                # `_KNOWN_UNMATCHED_ACTIONS`）⇒ 由 `tests/test_agent_a_search_providers.py` 两条钉住
                # （声明面形状 + `param_seam_violations`）。"源名认不认识"由实现侧入队前逐个核，
                # 声明面不造第二份名单。
                "providers": _ARR_S,
            },
            required=("topic",),
        ),
        # 键名逐字抄自实现（`agent_a/search_literature.py`）末尾那个 return 字典：
        # 声明面漏掉的正是 `sources` / `cost` 这一类跨源读数，而主控派活读的就是这一格
        # （`capabilities.CAPABILITIES` 由本文件派生）。
        (
            "ASearchResult dict（逐键：ok / admitted / request_id / topic / mode / done / "
            "outcome / claimed_request_ids / claimed_own / result_lit_ids / literature / "
            "query_description / providers_requested / role_providers / sources / "
            "sources_round / cost / registered / duplicated / downloaded / download_failed / "
            "attempts / last_error / queue_pending / pending_total / pending_by_delegation / "
            "pending_scope_note / rounds / note）；"
            "三个非成功档（`refuse(...)` / `outcome=query_not_applicable` / "
            "`outcome=rejected_by_gate`）各自返回更短的读数，键集与上面这一档不同"
        ),
        side_effect="write_local", handler_name="search_literature",
        external="egress",
    ),

    # ---- `walk_citations`
    # 为什么必须有它：只取 `cited_by_count` / `referenced_works_count`（排序用）而不取
    # `referenced_works` 与 `cited_by_api_url` ⇒ "顺着引文走"结构上做不了，而"更短证明路径"
    # 正是引文图上的问题（更短的路线通常在奠基论文的参考文献里或后续引用里）。
    # 两根轴：效果轴 `read`（只读、一行都不落；登记走既有 `search.dedup_check` / `search.register`，
    # 判重只有一处实现）；外部轴 `egress`（两个方向各发一次 OpenAlex 请求）。
    ActionSpec(
        "A", "walk_citations",
        "由一篇已登记的文献出发走一步引文图：回溯=它引了谁，前推=谁引了它",
        _obj(
            {
                "lit_id": {**_S, "minLength": 1, "maxLength": 40},
                # 只声明「形状」、不抄「词表」（与同文件 `search_literature` 的
                # `providers` 那一条同一个理由）：可用取值是 `backward` / `forward`，
                # 真身在实现与工具面（`tools/search_tools.py` 的 `ToolSpec`）——
                # 在这里再抄一份就是造出第二个要同步的地方，而它漂了不会报错。
                "direction": _S,
                "limit": {**_I, "minimum": 1, "maximum": 50},
            },
            required=("lit_id",),
        ),
        (
            # 键表逐个抄 `agent_a/walk_citations.py` 末尾那个 return 字典：`ok` / `kind` /
            # `truncated_to_tool_max` 这三格是判三态与判截断要用的。失败档描述动作自己
            # （工具那句 error 拼进 note，动作返回里没有 error 键）。
            # 判据：tests/test_a_action_declarations_match_their_return_keys.py。
            "dict（逐键：ok / kind / lit_id / doi / openalex_id / direction / count / "
            "candidates / truncated_to_tool_max / note；"
            "`candidates[]` 每项是 title / year / doi / type_code / authors / venue / language / "
            "summary / pdf_url / landing_url / provider / is_oa / oa_source / openalex_id）；"
            "`ok=True` 只说走查做完了，走到什么看 `count` / `candidates`；`ok=True` 且 `count=0` "
            "才是「这一篇这一侧没有邻居」（有效结论）。失败档（走查没做成）：`ok=False` ＋ `kind` 是 "
            "no_store / table_unreadable / unknown_lit_id / no_source_key / "
            "provider_cannot_walk / walk_failed 之一，原因原话在 `note` 里"
        ),
        side_effect="read", handler_name="walk_citations",
        external="egress",
    ),

    # ---- `ingest_local`
    # 为什么必须有它：主控只能 `conductor.summon` 「动作」，而登记盘上已有的文件原先只有工具
    # （`search.ingest_local`）⇒ 盘上有论文、台账里没有它，后面每一跳（B 登记命题 →
    # G 建我方稿件 → H 审）都因为没有 `lit_id` 而落空。
    # 两根轴：效果轴 `write_local`（走 `locallib.ingest_directory`，一个事务写 `literature`，需要时写
    # `search_requests` 的登记行）；外部轴 `none`（不联网 —— 刻意与那两个 `egress` 动作分开：算成"要
    # 出网"会让只读/离线场景把它整条划掉，而它恰恰是离线场景最需要的那一件）。
    ActionSpec(
        "A", "ingest_local",
        "把一个本地目录里的文件登记成 literature 行（按内容 sha256 幂等；不联网）",
        _obj(
            {
                "books_dir": {**_S, "minLength": 1, "maxLength": 1000},
                "pattern": {**_S, "maxLength": 40},
                "limit": {**_I, "minimum": 1, "maximum": 1000},
                "max_bytes": {**_I, "minimum": 1024, "maximum": 2_000_000_000},
                "dry_run": _B,
            },
            required=("books_dir",),
        ),
        # 键表逐个抄 `agent_a/ingest_local.py` 末尾那个 return 字典：实现返回 17 个平铺的键
        # （没有 counts 这一格）—— 照 counts 去读会读到 None，再把「没读到」当「没入库」。
        # 判据：tests/test_a_action_declarations_match_their_return_keys.py。
        "IngestReport dict（逐键：ok / kind / resolved / root / dry_run / limit / books[] / "
        "count / ingested / already_present / skipped / unreadable / text_layer_ok / "
        "pages_total / literature_ids / provenance / note）",
        side_effect="write_local", handler_name="ingest_local",
        external="none",
    ),

    # ---- `shelf_search`
    # 为什么必须有它：`search.shelf` 与 `search.local` 在 A/C/H 的工具面上，动作面里一个都没有 ⇒ 主控
    # 派不出"在本地书架上找一找"（与 `ingest_local` 同一格病：工具层通、编排层不通）。它服务的是
    # 「不联网也能推进」那条路（`#1` 那一类"无意义/重复的外出"的正解之一）。
    # 两根轴：效果轴 `read`（只调那两件只读工具，自己不写表）；外部轴 `none`（都不联网）。
    # 两层对账：工具名最后一段 `shelf` / `local` 与 `handler_name`（`shelf_search`）对不上 ⇒ 诚实地落进
    # `unmatched`，已登记进 `capabilities._KNOWN_UNMATCHED_ACTIONS`（与 `search_literature` 同族）。
    ActionSpec(
        "A", "shelf_search",
        "在本地书架上找文献（不联网）：列出全文在盘的（`search.shelf`），"
        "给了 query 再按主题取最相关的一页与逐字摘录（`search.local`）",
        _obj(
            {
                "query": {**_S, "maxLength": 400},
                "limit": {**_I, "minimum": 1, "maximum": 500},
                "lit_id": {**_S, "maxLength": 40},
                "local_limit": {**_I, "minimum": 1, "maximum": 20},
                "max_chars": {**_I, "minimum": 200, "maximum": 8000},
            },
        ),
        "dict（ok / kind / count / shelf / local / lit_ids / hits / excerpt_count / note）",
        side_effect="read", handler_name="shelf_search",
        external="none",
    ),
)


def _build(d: BuilderDeps) -> Any:
    """构造 A（逐字搬自 `host._Builder.agent_a`：下载器由 `agent_a` 配置段的 `download` 决定）。

    为什么 `providers` 与 `downloader` 必须一起给：
    只给 providers 时 A 能检索、却一条全文都下不下来，台账里逐条写 `error="no_downloader"`
    —— 而 `no_pdf_url` 是另一回事（那篇本来就没有开放获取 PDF）。两种"没下来"必须分得开。
    """
    from ..agent_a import AgentA

    return AgentA(d.store, providers=list(d.providers), llm=d.llm, config=dict(d.config),
                  downloader=d.downloader, actor=d.actor)


#: 本角色的声明。
SPEC = AgentSpec(
    role='A',
    brief=    AgentBrief(
        duty="文献检索：把搜索请求变成已登记的文献行，并如实报告每一次失败",
        boundary=(
            "文献收进 `literature`（`admitted > 0`）之后，下一步就是派 B 的 `run_once` 整理"
            "（抽概念、建关系、落命题线索）；不派 B 等于这批文献没转化成资产 —— "
            "只检索不收编是浪费预算。你自己不建概念网，也别把一批文献直接扔给下一环。",
            "候选被你判为不相关时，只能说这一条没进结果，不许说这篇文献不存在。",
            "下载失败不许当成功，也不许静默重试到超预算。",
            "命中校验（§2 R1b）：登记一行文献之前先核题名/年份/DOI —— 与派活时点名的那一篇对不上就把该行的 matched 写成 mismatch 并说清差在哪，不许静默登记成找到。",
            "定位与确认（§2 R14）：把一条命题交给下游之前，必须先在抽出来的正文里定位它 —— 回报定位结论（matched ∈ exact / partial / none）+ 页码 + 片段；partial / none 要把最接近的三段一并列出来（让人能复核）。none 不许交给 B：没定位到就不算找到。注意这里有两个 matched：文献行的那个问「是不是这一篇」（第三态叫 mismatch），这个问「这条定理在不在这篇里」（第三态叫 none），别串。",
            # 待新增文献列表的口径：一次检索至多入库 10 篇 / 每委托从空开始 / 可撤可补可追加 /
            # 重叠高无新内容拒收 / 只拿到 3 篇也逐篇审 / 判收只是 qualified、提交才注册并清表 /
            # 报告两块都要写。
            # 刻意写进「既有条目」（boundary）而不是新开一节：它与上面几条是同一种东西
            # （A 在登记文献这件事上不许做的事），分散到别处会让"登记"的口径裂成两处。
            "一次检索至多入库10篇，要精选：候选先进待新增列表（每委托从空开始），"
            "可撤可补、可再找一批；重叠高又无新内容就拒收；只拿到3篇也逐篇审。"
            "判收不是注册：`lit.admit` 只把这一条判成 `qualified`（有资格入库、**还没有号**），"
            "**提交** `lit.admit_all` 那一刻才批量注册、把号回填进同一行，并落无号快照与带号定稿两份报告；"
            "提交顺带清表（每行 `cleared_at`），清表之后才叫收工。报告写清已入库与未入库（含理由）。"
            # 2026-11-21（ASEARCH）：真机 lp-ball-14 的 4 个委托共 24 条候选留成 pending
            # （r-000011 15 / r-000012 2 / r-000013 4 / r-000014 3），没有一条被逐条判过。
            # 收尾义务写在这里（边界那条不许涨条数：伙伴表只引第一条，条数是渲染读数）。
            "**每一趟的收尾不是「报告交了」，是「待裁表清了」**：`run_once` 回执里的 "
            "`pending_total` 是跨委托的全表读数，不为 0 ⇒ 这一趟还没收尾。收尾三步一步都不能省："
            "① `lit.stage_list(request_id=\"*\", status=\"pending\")` 看全表（不只当前委托）；"
            "② 本批候选**逐条**判收（`lit.admit(items=[{\"slot\": …, \"availability\": …}])` —— "
            "`availability` 逐条给；那句 `relevance` 是 `lit.stage_add` 时写进候选行的，"
            "`lit.admit` 的 items 不收它，传了会被参数门按未声明键拒）或判拒"
            "（`lit.stage_reject`，批量用 `slots`）；③ **逐委托** "
            "`lit.admit_all(request_id=<委托号>)` 提交清表。**回执里建议写**"
            "「还剩几条待裁、分布在哪个委托上」（0 也写）—— 这只是给召唤方的摘要，"
            "**不是判据**：真正的闸是收工门第八格 `literature_pending` 按 `lit_candidates` "
            "表数，`run_once` 的 `pending_total` 是跨委托的全表读数。",
            # 2026-11-20 业主裁定（逐字「读内容才能判东西，这样的话保证通过的肯定有内容，
            # 且能保证质量」）：判收的证据从"一句 relevance"收紧到"真的读到正文"。
            "没有正文就不许判收：`lit.admit` 只接受读过正文的候选 —— 正文由 `text.extract` "
            "抽出、`fs.read` 读过、且不只是摘要（`content_read` 是机器现算的读数，不是自报）。"
            "未下载 / 抽取失败 / 只有题录 / 只有摘要的候选一律不许判收、不许入库："
            "只能登记题录并写清为什么没读到（`lit.stage_reject` + 受控理由码）。"
            "`relevance` / `new_content` 里写了定理名或具体数值这类内容性断言，而 "
            "`content_read=false` ⇒ 整批拒（`content_assertion_without_content`）—— "
            "没读到正文就只写「为什么这条与本次检索相关」，那用题名/摘要就够。",
        ),
        policy=(
            # 非 M 的父也拿得到这件工具，而 `conductor.board` 只给 M（他们看不到 `revocable` 格）
            # ⇒ 这一句是他们唯一的说明书。
            "**你能撤子代理的板项**：孩子名下不再需要做的项，用 "
            "`conductor.void_items(item_ids=[…], why=…)` 撤销 —— 你是它的直接父就够，"
            "不必证明叫不醒（`why` 必填、逐字进留痕）。",
            "继续搜还是收手由预算与命中率决定：预算耗尽时必须收手并在结论里写明预算读数。"
            "检索的价值不在跑了几次，而在找到能改变判断的那几篇：命中后要写清它**支撑 / 推翻**了台账里的哪一条"
            "（`stmt:` / `rel:` 号，写进结论与 `note`）；只登记元数据不说影响的，不算有价值。",
            # 2026-11-21（ASEARCH）：真机 lp-ball-14 的 14 条检索请求里 13 条 no_results，
            # 8 条 no_result_topics 是题面式说法（"Ball cube slicing" / "Meyer Pajor sections" /
            # "central hyperplane sections of the l_p ball" / …）。纪律此前只活在手册正文里，
            # A 的职责面（policy）一个字都没写。这一条是提示词引导，不做词表阈值。
            "**题面式说法不是查询词**：把研究问题原句（「Ball cube slicing」这种题面）直接丢进 "
            "`topic` 是题面、不是检索词 —— 它查不到不等于这个方向没有文献。`topic` 写成"
            "**规范术语 + 关键词组合**：去掉题面里的通用词，换成那条路在文献里通行的数学术语 / "
            "定理名 / 作者名（例：`cube slicing`、`hyperplane sections`、`central section`、"
            "`ℓ_p ball`、`Meyer-Pajor`、`Koldobsky`、`Brunn-Minkowski`）。"
            "**`no_results` 之后建议换规范术语再查一次**（同一个题面原样重试不算）：换掉哪个词、"
            "换成哪个术语、两次的 `topic` 各是什么，逐次写进结论。**这一条是纪律，不是闸**："
            "收工门只给 `no_result_topics`（每个 `no_results` 的题面）与 "
            "`no_result_repeated_topics`（同一题面原样重提的那几条，机械可判）；"
            "「换的是不是规范术语」语义上判不了，所以一条 `no_results` 不会因为没换词而红。",
            # 2026-11-21（SEEDDOC）：工作区里已经躺着历史文献时，A 的可见面此前一个字都没写
            # 这条路 —— 下一趟真机把 25 份 PDF 投进 library/（未入库、未判收），A 只能自己
            # 想怎么办；而两种最省事的错法（把发现读数当已入库、用非 dry 档一次性登记）
            # 都不报错。候选链已由 SEEDREH 彩排通过（temp/seedreh/SEEDREH-REPORT.md），
            # 这一段每一句都能指到实现：dry_run 的"只算不写"是 search.ingest_local 的
            # description 原话，判收闸在 litstage / litavail（这一段是提示词引导，不加词表阈值，
            # 也不动任何落库路径）。
            "**工作区里已有的文献不是「已入库」**：`library/`（历史文献的投放处）或 `source/` "
            "下已经躺着 `.pdf`、而 `data/literature.json` 里没有它们时，默认走这三段："
            "① **发现** —— `search.ingest_local(books_dir=\"library\", "
            "dry_run=True)` 只算 sha256 / 页数 / 文本层、一个字节都不写（读数里的 `ingested` "
            "是「会登记」的预告，不是入库，别拿它当已收编；发现档不受声明限制，它本来就零写入）；"
            "② **建候选** —— 按发现读数里的盘上路径，**只对用户声明里点名的那些**逐份 "
            "`lit.stage_add(request_id=<委托号>, entries=[{title: …, "
            "url: <盘上路径>, relevance: \"工作区里已有的本地文献，不是检索来的\"}])`，"
            "这一步只写候选表，`literature` 仍是 0 行；③ **判收** —— "
            "`text.extract(lit_id=\"cand:<槽位>\")` 抽正文、`fs.read` 读到那份 `.txt`、"
            "`lit.admit(items=[{\"slot\": \"<槽位>\", \"availability\": \"readable\"}])` 逐条判，最后逐委托 `lit.admit_all` 提交"
            "（提交才发号、才进 `literature`）。**这一条是默认路径，不是闸**："
            "非 dry 的 `search.ingest_local` 与 `search.register` 是另外两条直登口 —— "
            "它们只核用户声明（`not_declared_reference`）与「有没有可读正文」，"
            "**不核「读过正文」**（`no_read_evidence` 只长在 `lit.admit` 上）；"
            "绕过去不会报错，只会落在收工门读数 `readings.literature_intake` 里"
            "（`direct` 是没走过候选链的行，`direct_without_fulltext` 是其中只有题录的那几条）。"
            "**只有用户点名的才可入库**（业主 2026-11-21 裁定，默认 fail-closed）：M 会把用户"
            "提示词里点名的文件/目录逐字记进工作区根的 `RELIABLE-REFERENCES.json`；清单外的"
            "文件只能当研究参考（可读），不许进 `literature` —— `search.ingest_local` 非 dry 档"
            "遇到未声明文件会以 `not_declared_reference` 受控拒（零写入）。那不是故障，是它在"
            "拦「未声明入库」：让 M 先把用户声明记下来（或只把那份当研究参考读来用、不入库）。"
            "**没有正文的不许当已收编**：乱码 / 扫描件 / 无文字层 / 只有题录的那几份，"
            "`lit.admit` 会按 `no_read_evidence` 整批受控拒并逐槽点名（`extract_failed` / "
            "`metadata_only` / `no_fulltext`）—— 那一格就是机器读数；正确处置是 "
            "`lit.stage_reject` 写清为什么没读到，它们不进 `literature`。",
            "**引用闸**（不是派 B 的前提）：这批文献**要不要被引用成断言**由报告决定 —— "
            "报告里「这条结论凭什么」要追到出处时，凭据只认 B 整理出的概念行与关系行"
            "（`relations` 的 `kind`/`quote`）；引用与否都不改变「收进 `literature` 就派 B 收编」这一步。",
            # 这一句说的是 R14 的「定位轴」（matched ∈ exact / partial / none ＋ 页码 ＋ 片段 ＋
            # 「最接近的三段」），而台账里「没有这一格」：`schema.py:200` 逐字写它「由 A 在回报里
            # 给出…「不落本栏」」。`literature.matched` 是「另一根轴」（身份：exact/partial/mismatch），
            # 往它写 `none` 会被 `Literature.validate()` 拒。
            # ⇒ 没有任何写入期闸能拿「报了 none」去比「写了候选」（`outcome="no_results"` 而
            # `result_lit_ids` 非空的 `search_requests` 行照样通过校验）。
            # 缺的字段：`search_requests` / `lit_candidates` 上没有 `located` / `closest_snippets` 这类落点。
            "确认优先于登记 —— 见上面 boundary 那条（none 列最接近的三段、不交 B）。",
            # `search_requests` 的 17 个字段里没有任何「反证检索」维度，`SEARCH_OUTCOMES` 里也没有
            # `unresolved`（写入 `outcome="unresolved"` 会被 `SearchRequest.validate()` 拒）。
            #   这个词只存在于 `CONTRADICTION_VERDICTS`（contradictions 表，写手是
            #   `interactions.adjudicate_contradiction`）与 `DOC_STATUSES.unresolved_review`
            #   （documents 表，F/H 的产出）—— 两者都不是 A 的产出。
            #   缺的字段：反证检索的标记 ＋ 三态结论（refuted / not_refuted / unresolved）。
            "被问「有没有人说它不成立」时做反证检索：找勘误、后续版本、独立确认；找不到就如实写 unresolved —— 不许拿「没搜到」当「不存在」。",
            "**泛化搜索**（D 在命题研究起手时派你的就是这一轮）：一次检索分三档交回 —— **推广**（哪些已入库结论是它的推广）/ **类比**"
            "（别的领域里的同构结构）/ **特例**（它退化成的已知结论），每档都要给到能查的那一行（`lit:` / `stmt:` / `rel:`）与逐字依据。"
            "只答「有没有人做过」是白跑一趟：这一档问的是**它在已知地图上的位置**；类比要写清「迁移的是什么、不迁移的是什么」"
            "（**类比是证据生成器，不是证明**）。",
            # 只在提示词里提醒：不做 stage 强制、不做出处闸、不改 schema —— 这一格是提示词，
            # 不是判据；落库路径（lit_candidates / literature）一个字都没动。
            "被指认无可信度、或还在待审核的文献：不可当引文入库，只可当研究参考 —— 它的原话不进 `quote`，"
            "也不拿它当「这条结论凭什么」的凭据；结论里要用到它，先换一篇可核的来源，"
            "或者把它按「研究参考 / 待核」如实标出来。",
            # 只写这一实现里真有的两件 —— `trace.children` 与 `conductor.escalate` 都在本角色的
            # 工具面上（`trace.children` 的 `roles` 是全部可召唤角色，escalate 是全部角色）。
            # 判据：tests/test_every_role_knows_it_can_watch_its_children.py。
            # 那一格叫 `subtask_refusals`（`agenttrace.node_facts`，与 action_ / final_ /
            # registration_refusals 三义分开）—— 提示词里必须写这个名字；写成 `refusals`
            # 模型会去 `trace.children` 的返回里找一个不存在的键。
            # 判据：tests/test_a_and_c_name_the_subtask_refusal_cell.py。
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
            "一条计时器都没有还起这个意图时，它会拒（`no_timers_to_wait`，不写意图账）—— "
            "要么先起一条表再起这个意图，要么既无计时而手头也没活，就按交差处理"
            "（框架向父代理报告、父代理记为静默），别空转着等。"
            "**计时只有时钟这一处**：旧的计时工具已经退役，别去找别的等待 / 定时入口。",
            # 主动性口径：每一类下载失败的正确处置不同，把它们都归到「这篇找不到」会让
            # 只有元数据的文献被当成「本来就没有」。这一句是提示词口径，不是判据；
            # 工具面的落点是 `search.download` 的 `fetch_kind` 与 `search.retry_pending` 的四结局。
            # 判据：tests/test_a_selfchecks_topic_and_hears_the_fetch_kind.py。
            "**取不到全文不等于这篇不存在**：下载失败先读 `fetch_kind` / `kind` 再决定下一步 —— "
            "`http_429` 等这个源的冷却过去（**同一个源在冷却时后面的行会自动跳过**，别换着地址瞎试）；"
            "`http_404` 换 landing（那个直链就是死的）；`http_400` 换 PDF 路由（构造出来的链接走不通）；"
            "`tls_cert` / `http_403` 换源；`network_error` 可以再试。"
            "**取不到就如实登记「没取」**（`download.status=failed` ＋ `last_kind`），"
            "不许写成「没有这篇」—— 我们没有拿到，与它不存在是两件事。"
            "批量再取走 `search.retry_pending`：每行一次、四结局 got / failed / no_location / "
            "cooled_down（`cooled_down` 是跳过、不是失败；`no_location` 是「行上没地址」，也不是「不存在」）。",
            # 宽检索抓回来的噪声不该各花一次判官调用。
            # 机器侧落点：`providers.mark_topic_selfcheck` 把 broad 的候选逐条标成
            # related / off_topic / unknown（只标不删），经 `search.literature` 的
            # `candidates[].topic_selfcheck` 交到你手上。
            "宽检索（broad）回来的候选里，`topic_selfcheck.state=off_topic` 的那些是机器**判得出**跑题的："
            "别为它们花判官的一次调用，直接在 `relevance` 里写「与本次检索无关」；"
            "`unknown` 是机器**判不了**（例如题面是中文、标题是英文），仍要你自己看一眼 —— "
            "别把 `unknown` 读成 `off_topic`。",
        ),
        signature_error="把一条候选被丢掉说成这篇文献不存在。",
        deliverable="交付状态 —— 交给谁：派你这趟活的那一方（收工 `final` 的 `notify` 的 `to` 格写它的名册名 / 绝对编号 / 角色名，它是主控就写 M）"
                    "与收方 B；形态：`search_requests` 行 + `literature` 行；"
                    "可核字段：`search_requests.outcome` / `search_requests.result_lit_ids` / "
                    "`search_requests.done` / `literature.lit_id`；"
                    "算做完：本条请求的 `outcome` 已终局（不是 pending）、`result_lit_ids` 里每个号都 "
                    "能在 `literature` 里读到，且这批已派 B 收编、B 回执给出概念行与关系行的条数。",
        stance=(
            "你的眼睛最先该落在'来源'上：同一篇文献在不同库里的元数据不一致时，把差异（哪一格、两边各写了什么）写进草稿本那一行，并在同一行写清采信哪一份、凭哪个字段 —— 判重的键只保证同一篇只有一个键，采信理由只能由你留下。",
            "检索不是把关键词丢出去：每条候选落 `lit.stage_add` 时，`relevance` 那一格就是答案 —— 写清它为什么算'我要找的那一类东西'；写不出这一句的候选，不该进表。",
            "被丢掉一条候选时，把'为什么丢'写进草稿本；那是别人复核你检索质量时唯一的线索。",
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
        '能思辨': 'minor',
        '敢创新': 'denied',
        '有品味': 'minor',
    },
    local_notes={
        '眼睛': '读的来源包括元数据与落地页：同一篇文献在不同库里不一致时，先记差异再决定采信谁。',
        '手': '登记文献行、把下载落在本地、把失败写进请求行的错误字段；不抽概念（那是 B）。',
        '脑子': "把'我要找的是哪一类东西'想清楚，再决定查什么、怎么判相关、什么时候收手。",
        # 写成「陈述结构」：这条义务有结构性闸（A 的动作面没有 register_statement /
        # register_conjecture、写面只有 literature/search_requests ⇒ 想造概念会得到
        # unknown_action）。这一行本身删不掉：判据
        # test_core_faculties_..._denied_ones_are_written_as_forbidden 要求「denied 的官能
        # 必须写明理由，并落在『结构上不许』那一列」。
        # 结构性判据：tests/test_a_cannot_invent_concepts.py。
        '敢创新': '不造概念：`table.create` 写 `statements` 会被当场拒绝（结构禁止）；提猜想更不该做 —— 猜想（**待登记命题**）由产出侧写：E / F / B 在产出那一刻落 `conjectures` 一行（唯一写点是 `conjectureledger` 的 `register`），D **不写**这一张表。你发现了可检验的猜想就把它写进检索结论，交给产出侧去落行。',
    },
    read_only=False,
    summonable=True,
    edges=('B',),
    write_set=frozenset((
                     'literature',
                     'search_requests',
                     # 2026-11-22（WRITESETFIX）：`lit_candidates` 是 A 的**实际写点**，
                     # 改前漏在写集外 —— 写集是并发轴的读数（`policy.estimate_write_conflict`
                     # 按它算冲突对），漏一张表就漏算冲突。
                     # 证据（符号名，不写行号）：`agent_a/run_once.py` 那笔事务
                     # `self.store.tx("search_requests", "literature", "lit_candidates", …)`
                     # 里经 `litstage.stage_entries` / `litstage.apply_settlement` 落候选行；
                     # `litstage.py` 的七处 `tx.upsert("lit_candidates", …)` 是唯一写口
                     # （写入口只从 `agent_a/` 进：`closing.py` 只调它的读数、
                     #  `tools/table_tools.py` 只 import 它的异常类型 `LitStageError`）。
                     # 真机 `projects/lp-ball-15`
                     # 的 `data/events.jsonl` 里 A 系 actor 写了 219 条 `lit_candidates` 事件
                     # （`agent-A` 31 + `agent-A-A1` 96 + `-A2` 30 + `-A3` 18 + `-A4` 25 + `-A5` 19），
                     # 而改前 `WRITE_SETS["A"]` 只有 {literature, search_requests}。
                     # 它不是"可能写"的条件档：`run_once` 的暂存→判收→提交三步全都写这张表。
                     # 判据：`tests/test_write_sets_match_their_write_points.py`。
                     'lit_candidates',
                 )),
    class_path='agentflow.agent_a:AgentA',
    actions=ACTIONS,
    needs=('providers', 'downloader'),
    build=_build,
)

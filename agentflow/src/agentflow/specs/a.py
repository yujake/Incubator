"""角色 A 的声明（`goal-7f5116c1` M3）：动作表 + 边 + 写集 + 职责与门面。

这一份是权限面的真身：`capabilities.py` 从它派生 `CAPABILITIES` / `ALLOWED_EDGES` /
`WRITE_SETS`，`agent_a.py` 只是把它再导出一次。
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
        "A", "run_once",
        "领取一条待办检索请求并跑完（搜索 + 登记文献 + 下载）",
        _obj({}),
        "ARunResult（含 claimed / outstanding / registered ）",
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

    # ---- `search_literature`（2026-09-30 加；**本文件是 FC-27 禁改区，本次改动已登记基线待 2 名人审**）
    #
    # 为什么必须有它：上面两个动作的参数里**没有主题** —— 它们只认"队列里已经有什么"，
    # 而队列今天只有 CLI `submit` / D 的 `research.submit_gap`（要求先有研究问题）/
    # C 的 gap 分支能写。于是"角色缺文献证据 ⇒ 唤起 A"这条路上，召唤方**没有办法
    # 告诉 A 要查什么**：它只能唤一个对着空队列空转的 A。用户口径是
    # "A 的文献检索必须要通关"，指的就是这一格。
    #
    # 名字为什么不叫 `search`：两层对账按"工具名最后一段 == handler_name"配对，
    # 而 A 的工具组里有 `fs.search` 与 `table.search` ⇒ 叫 `search` 会落进
    # `ambiguous`（两个候选都算对上），而导入期第 [7b] 条要求 `ambiguous` 为空。
    # 实测：`stale` 断言先报 `['A.search']`（它没进 unmatched），换成
    # `search_literature` 之后没有任何工具同名 ⇒ 诚实地进 unmatched。
    #
    # 两根轴逐条读出（不是照抄工具层）：
    #   - 效果轴 `write_local`：实现（`AgentA.search_literature`）在一个事务里写
    #     `search_requests` 一行，随后走既有的 `run_once` 链路再写 `search_requests`
    #     + `literature` —— 与 `run_once` 是同一组表（`WRITE_SETS["A"]` 登记了这两张）。
    #   - 外部轴 `egress`：它真的发 HTTP（检索 + 下载都在这条链上），且不执行
    #     调用方给的程序 ⇒ 不是 `exec`。
    #
    # 为什么不改成"给 `run_once` 加一个 topic 参数"：那会把"领任务"与"提交任务"
    # 合成一个动作，而它们的权限面不同 —— `run_once` 是**消费队列**（谁都能调），
    # `search_literature` 是**生产队列**（受在途上限这个准入闸门约束）。合成之后，
    # 想要"只消费"的调用方也会被迫接受"可能新建请求"的副作用。
    ActionSpec(
        "A", "search_literature",
        "按主题现查一次：入队（过 I7 准入闸门）→ 领跑 → 把候选与来源交回召唤方",
        _obj(
            {
                "topic": {**_S, "minLength": 1, "maxLength": 400},
                # 缺省 `precise`（实现在 `AgentA.search_literature`）：这一个动作
                # 服务的是"给我这条命题的来源"，而真机实测 `topical` 的词袋查询
                # 在这个语义下 15 条里只有 1 条对题、`precise` 是 8 条里 7 条对题。
                # 要领域全景就显式传 `broad` / `topical`。
                "mode": {"type": "string", "enum": list(S.SEARCH_MODES)},
                "description": _S,
                # 题 3（2026-10-07 所有者授权补 `providers`）：
                # 这一格由所有者批准、主控代改（本文件是 FC-27 禁改区
                # [auth-audit]，改动处逐字写明授权来源）。它补的是一条声明面缺口：
                # 工具面 `search.literature` 早就有 `providers`（一次问多源），
                # 而动作面没有 —— 编排层（主控按动作参数表派活）因此看不见这个入口。
                #
                # 只搬形状、不搬名单：工具面那一格还带 `enum`（可用源名）与
                # `minItems` / `maxItems`，这里刻意一格都不抄。可用源的真身是
                # 检索后端注册表（`providers.build_providers` 的名单 + 调用方注入的
                # 实例），抄一份就等于造出第二个要同步的地方，而它漂了不会报错。
                # 所以这里只声明 array<string>：type=array、items.type=string，
                # 与工具面那一格同形。
                #
                # 这一对的形状一致没有任何导入期判据看着：两层类型对账
                # （`capabilities.param_type_divergences_for`）按"工具名最后一段 ==
                # handler_name"配对，而工具名最后一段是 literature、本动作是
                # `search_literature` ⇒ 它落进 `_KNOWN_UNMATCHED_ACTIONS`，
                # 那条对账看不见这一对。所以形状一致由新增的判据钉住
                # （`tests/test_agent_a_search_providers.py` 里两条：声明面形状，
                # 以及"只改声明不改实现"必须被 `param_seam_violations` 报出来）。
                #
                # "这个源名认不认识"由实现侧在入队之前逐个核（不认识就如实拒绝，
                # 并把可用名单一起给出来）—— 声明面不替实现面造第二份名单。
                "providers": _ARR_S,
            },
            required=("topic",),
        ),
        # 【FC-27 禁改区 · 本次改动所有者授权、主控代改】本文件登记在 `.noai-paths`
        # 的 `[category: auth-audit]` 里。题 20 选 A（2026-10-07 所有者裁定）：
        # 这一格此前只写"含 request_id / outcome / result_lit_ids / literature"，
        # 而实现（`agent_a/search_literature.py`）在题 11 补完"完整透传"之后已经
        # 返回 26 个键 —— 声明面漏掉的正是 `sources` / `cost` 这一类跨源读数，
        # 而主控派活读的就是这一格（`capabilities.CAPABILITIES` 由本文件派生）。
        # 本次只把键名逐字抄齐（名字与次序都取自实现末尾那个 return 字典），
        # 不改实现、不改别处、不改任何判据。
        (
            "ASearchResult dict（逐键：ok / admitted / request_id / topic / mode / done / "
            "outcome / claimed_request_ids / claimed_own / result_lit_ids / literature / "
            "query_description / providers_requested / role_providers / sources / "
            "sources_round / cost / registered / duplicated / downloaded / download_failed / "
            "attempts / last_error / queue_pending / rounds / note）；"
            "三个非成功档（`refuse(...)` / `outcome=query_not_applicable` / "
            "`outcome=rejected_by_gate`）各自返回更短的读数，键集与上面这一档不同"
        ),
        side_effect="write_local", handler_name="search_literature",
        external="egress",
    ),

    # ---- `walk_citations`（2026-10-15 加；**本文件是 FC-27 禁改区 [auth-audit]**，
    #      业主裁定逐字：「引文图是用新动作的方式落」；按业主同日口径
    #      「如果你认为有道理，就允许改，事后签字即可」登记，待 2 名人审。）
    #
    # 为什么必须有它（施工记录在 `draft/124` §10.6）：到这一轮之前，我们向 OpenAlex
    # **只取被引计数**（`cited_by_count` / `referenced_works_count`，用来排序），
    # **没取** `referenced_works`（这一篇**引了谁**）与 `cited_by_api_url`（**谁引了它**）
    # ⇒ "顺着引文往下/往上走"这件事**结构上做不了**。而业主点名的那个任务
    # （"更短证明路径"）恰恰是**引文图上的**问题：更短的路线通常在奠基论文的参考文献里，
    # 或者在后续引用里（谁后来简化了某一步）。纯关键词检索拿不到这个结构。
    # 实测（`temp/_probe_citation_walk.py`，$0）：源论文 `10.1098/rsos.181055`
    # 自己引了 **123** 篇，`cites:W2883591297` 前推 **29** 条，
    # 而且前推那 5 条**全是 `is_oa=True` 且带 `best_oa_location`** ——
    # 引文图这一侧"顺手把全文也拿到"的比例比关键词检索高得多。
    #
    # 两根轴逐条读出（不是照抄工具层）：
    #   - 效果轴 `read`：实现只**读**（取一次源记录 + 一次 works 查询），一行都不落。
    #     要不要登记由调用方走既有的 `search.dedup_check` / `search.register` ——
    #     **刻意不给它写集**：登记是判断，判断要留痕，而本动作不做那个判断
    #     （判重在本模块只有一处实现，见 `tools/search_tools.py` 里那条注释）。
    #   - 外部轴 `egress`：两个方向各发一次 OpenAlex 请求。
    ActionSpec(
        "A", "walk_citations",
        "由一篇已登记的文献出发走一步引文图：回溯=它引了谁，前推=谁引了它",
        _obj(
            {
                "lit_id": {**_S, "minLength": 1, "maxLength": 40},
                # 只声明**形状**、不抄**词表**（与同文件 `search_literature` 的
                # `providers` 那一条同一个理由）：可用取值是 `backward` / `forward`，
                # 真身在实现与工具面（`tools/search_tools.py` 的 `ToolSpec`）——
                # 在这里再抄一份就是造出第二个要同步的地方，而它漂了不会报错。
                "direction": _S,
                "limit": {**_I, "minimum": 1, "maximum": 50},
            },
            required=("lit_id",),
        ),
        (
            "dict（逐键：lit_id / doi / openalex_id / direction / count / candidates / note；"
            "`candidates[]` 每项是 title / year / doi / type_code / authors / venue / language / "
            "summary / pdf_url / landing_url / provider / is_oa / oa_source / openalex_id）；"
            "失败档走工具层的 `fail(...)`：`ok=False` ＋ 一句 `error`，`kind` 是 "
            "no_store / table_unreadable / unknown_lit_id / no_source_key / "
            "provider_cannot_walk / walk_failed 之一"
        ),
        side_effect="read", handler_name="walk_citations",
        external="egress",
    ),

    # ---- `ingest_local`（2026-10-02 加；**本文件是 FC-27 禁改区，本次改动已登记基线待 2 名人审**）
    #
    # 为什么必须有它（`draft/37` §44.4 的真机读数，不是设计洁癖）：主控只能
    # `conductor.summon` **动作**，而"把盘上这个目录里的论文登记进台账"原先只有
    # **工具**（`search.ingest_local`）—— 于是盘上有论文、台账里没有它，
    # 后面每一跳（B 登记命题 → G 建我方稿件 → H 审）都因为没有 `lit_id` 而落空。
    # 那趟真机的断点被主控自己定位到这一格上，逐字写在它的交付说明里。
    #
    # 两根轴逐条读出（不是照抄工具层）：
    #   - 效果轴 `write_local`：实现（`AgentA.ingest_local`）走
    #     `locallib.ingest_directory`，在一个事务里写 `literature`（+ 需要时写
    #     `search_requests` 的登记行）—— 与 `WRITE_SETS["A"]` 登记的两张表同一组。
    #   - 外部轴 `none`：**不联网**（与上面两个 `egress` 的动作不同）。
    #     这一格是刻意分开的：把这件本地下载的活算成"要出网"，
    #     会让只读/离线场景把它整条划掉 —— 而它恰恰是离线场景最需要的那一件。
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
        "IngestReport dict（含 counts / books[] / literature_ids / resolved / provenance）",
        side_effect="write_local", handler_name="ingest_local",
        external="none",
    ),

    # ---- `shelf_search`（2026-10-06 加，J-53 / 裁决 2 族 1；**本文件是 FC-27 禁改区，
    # 本次改动已登记基线待 2 名人审**）
    #
    # 为什么必须有它：`search.shelf` 与 `search.local` 两件工具在 A/C/H 的工具面上，
    # 而动作面里一个都没有 —— 主控只能 `conductor.summon` 动作，于是"在本地书架上找一找"
    # 没有可派的入口（与上面 `ingest_local` 同一格病：工具层通、编排层不通 ⇒
    # 盘上有全文，编排层却看不见它）。它服务的是**不联网也能推进**的那条路：
    # 全文已经在盘上的文献本身就是可引用的来源（`#1` 那一类"无意义/重复的外出"的正解之一）。
    #
    # 两根轴逐条读出（不是照抄工具层）：
    #   - 效果轴 `read`：实现（`AgentA.shelf_search`）只调 `search.shelf`（必调）与
    #     `search.local`（给了 `query` 才调）这两件**只读**工具，自己不写任何表
    #     —— 所以它是一条真只读的动作（与上面三条 `write_local` 不同）。
    #   - 外部轴 `none`：两件工具都**不联网**（与 `run_once`/`run`/`search_literature`
    #     那三条 `egress` 刻意分开）：离线场景最需要的那一件，不该被"要出网"整条划掉。
    #
    # 两层对账：工具名的最后一段是 `shelf` / `local`，与本动作的 `handler_name`
    # （`shelf_search`）对不上 ⇒ 按唯一性约定它诚实地落进 `unmatched`，
    # 已登记进 `capabilities._KNOWN_UNMATCHED_ACTIONS`（与 `search_literature` 同族）。
    # 为什么不给它凑一个同名工具：那两件工具是**通用只读检索**（A/C/H 都能调），
    # 而本动作是"先列书架清单、再按需取逐字摘录"的一次编排 —— 把两者配成一对
    # 会让两层类型对账去比两件不同的事（比 `search.local` 的 `max_books` 与本动作的参数）。
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

    为什么 `providers` 与 `downloader` 必须一起给（2026-09-29 验收 P1 实测的缺口）：
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
            "检索完请 B 整理：抽概念、建关系是他的活。",
            "候选被你判为不相关时，只能说这一条没进结果，不许说这篇文献不存在。",
            "下载失败不许当成功，也不许静默重试到超预算。",
            "命中校验（§2 R1b）：登记一行文献之前先核题名/年份/DOI —— 与派活时点名的那一篇对不上就把该行的 matched 写成 mismatch 并说清差在哪，不许静默登记成找到。",
            "定位与确认（§2 R14）：把一条命题交给下游之前，必须先在抽出来的正文里定位它 —— 回报定位结论（matched ∈ exact / partial / none）+ 页码 + 片段；partial / none 要把最接近的三段一并列出来（让人能复核）。none 不许交给 B：没定位到就不算找到。注意这里有两个 matched：文献行的那个问「是不是这一篇」（第三态叫 mismatch），这个问「这条定理在不在这篇里」（第三态叫 none），别串。",
        ),
        policy=(
            "继续搜还是收手由预算与命中率决定：预算耗尽时必须收手并在结论里写明预算读数。"
            "检索的价值不在跑了几次，而在找到能改变判断的那几篇：命中后要写清它**支撑 / 推翻**了台账里的哪一条"
            "（`stmt:` / `rel:` 号，写进结论与 `note`）；只登记元数据不说影响的，不算有价值。"
            "取回的这批如果**要被引用成断言**（报告里「这条结论凭什么」要追到出处），**派 B 整理**：概念行与关系行"
            "（`relations` 的 `kind`/`quote`）；你自己不建概念网，也别把一批文献直接扔给下一环。",
            "确认优先于登记：宁可如实回报 none 并列出最接近的三段，也不要把「看起来相关」写成「找到了」。",
            "被问「有没有人说它不成立」时做反证检索：找勘误、后续版本、独立确认；找不到就如实写 unresolved —— 不许拿「没搜到」当「不存在」。",
            "**泛化搜索**（D 在命题研究起手时派你的就是这一轮）：一次检索分三档交回 —— **推广**（哪些已入库结论是它的推广）/ **类比**"
            "（别的领域里的同构结构）/ **特例**（它退化成的已知结论），每档都要给到能查的那一行（`lit:` / `stmt:` / `rel:`）与逐字依据。"
            "只答「有没有人做过」是白跑一趟：这一档问的是**它在已知地图上的位置**；类比要写清「迁移的是什么、不迁移的是什么」"
            "（**类比是证据生成器，不是证明**）。",
        ),
        signature_error="把一条候选被丢掉说成这篇文献不存在。",
        deliverable="search_requests 里每一条请求的终局（outcome）与 result_lit_ids。",
        stance=(
            "你的眼睛最先该落在'来源'上：同一篇文献在不同库里的元数据不一致时，先把差异记下来，再决定采信哪一份 —— 这正是判重口径存在的理由。",
            "检索不是把关键词丢出去：先说清'我要找的是哪一类东西、它长什么样'，再决定查什么、怎么判相关。",
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
        '敢创新': '不造概念、不提猜想：你是把外部材料搬进来的人，不是替它们下定义的人。',
    },
    read_only=False,
    summonable=True,
    edges=('B',),
    write_set=frozenset((
                     'literature',
                     'search_requests',
                 )),
    class_path='agentflow.agent_a:AgentA',
    actions=ACTIONS,
    needs=('providers', 'downloader'),
    build=_build,
)

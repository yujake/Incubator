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
            },
            required=("topic",),
        ),
        "ASearchResult（含 request_id / outcome / result_lit_ids / literature）",
        side_effect="write_local", handler_name="search_literature",
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
        duty='文献检索：把搜索请求变成已登记的文献行，并如实报告每一次失败',
        boundary=(
            '检索口径（查询编排、精筛、候选打分）在禁改区：你只能调用它，不许绕过或改写它。',
            '你不抽概念、不建关系（那是 B 的活）；检索完请 B 整理。',
            '候选被你判为不相关时，只能说这一条没进结果，不许说这篇文献不存在。',
            '下载失败必须如实写进请求行的错误字段；不许把失败当成功，也不许静默重试到超预算。',
            '命中校验（§2 R1b）：登记一行文献之前先核题名/年份/DOI —— 与派活时点名的那一篇对不上就把该行的 matched 写成 mismatch 并说清差在哪，不许静默登记成找到。真机实测（2026-10-01）：要 Brown 1971，下回来的是 2022 年另一篇 CLT 论文 —— 登记成功、下载成功、569,776 字节的真 PDF，而没有任何地方报出来。',
            '定位与确认（§2 R14）：把一条命题交给下游之前，必须先在抽出来的正文里定位它 —— 回报定位结论（matched ∈ exact / partial / none）+ 页码 + 片段；partial / none 要把最接近的三段一并列出来（让人能复核）。none 不许交给 B：没定位到就不算找到。注意这里有两个 matched：文献行的那个问「是不是这一篇」（第三态叫 mismatch），这个问「这条定理在不在这篇里」（第三态叫 none），别串。',
        ),
        policy=(
            '继续搜还是收手由预算与命中率决定：预算耗尽时必须收手并在结论里写明预算读数。',
            '确认优先于登记：没定位到就不算找到。宁可如实回报 none 并列出最接近的三段，也不要把「看起来相关」写成「找到了」。',
            '被问「有没有人说它不成立」时做反证检索：找勘误、后续版本、独立确认；找不到就如实写 unresolved —— 不许拿「没搜到」当「不存在」。',
        ),
        signature_error='把一条候选被丢掉说成这篇文献不存在。',
        deliverable='search_requests 里每一条请求的终局（outcome）与 result_lit_ids。',
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

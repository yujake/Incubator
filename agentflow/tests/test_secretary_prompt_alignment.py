"""秘书与提示词的双向对齐（2026-10-07 所有者逐字要求："需要双向对齐"）。
## 这份判据要治的两个方向
调提示词时，秘书常常被当作"接住方"（`draft/63 §2` 的"谁接住"那一栏大量写的就是它）。但"它接住了"这句话有两个方向，任缺一边都会静默出错：
- 方向一（代码 → 提示词）：秘书真的做这件事（代码里有落点、有生产调用点），可是没有任何角色被告知 ⇒ 它的输出没人看、它的提醒没人接 ⇒ 能力等于不存在。- 方向二（提示词 → 代码）：提示词里对角色承诺了"秘书会替你 X"，
而代码里没有这件事 ⇒ 角色按承诺行事，撞墙时没人接。
## 为什么不能靠"读一眼"（`draft/63 §4-5` 的血账）
上一批减负把"你是只读角色：不许写/改任何数据"整句删了：C 被一条判据抓住，H 没有任何东西会红。⇒ "谁接住"必须被机器钉住，不能凭一句话当它接住了。
## 表怎么读
`DUTIES` 里每一项是一条职责：代码真身（`code`）· 生产调用点（`call`，逐处写 文件:行）· 可见性（`visibility`）：
- `prompt` —— 角色应当知道它（且有出口探针命中）；- `conditional` —— 只有一部分角色应当知道它；`roles` 是登记下来的那一批（注意：刻意不写"由某个代码条件推导"：实测 `duty2` 的可见集
{D,E,F,G,M} 不等于"有出边的角色"（A/B/H/V 也有边）⇒ 写一个猜的条件比登记更松。登记 + 等额 = 改了就红，人来裁）；- `internal` —— 框架内部用，角色不需要知道；必须写明 `why`，
且任何提示词的出口探针都不许命中它（否则就成了"提示词在承诺一件角色看不见的事"）。
`pin` 是"某个方法今天没有生产调用点"的登记（有产出方没调用点的东西要留读数，不许沉默）。
## 反真空
判据会报：扫了几个角色 · 抽到几句"对秘书的承诺" · 表里几项职责 ·`duty=N` 在代码里出现了几个 N。任何一个是 0 ⇒ 这一格没查成，不是没问题。
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import tempfile

import pytest

#: 四项职责 + 交接手稿那一族。`call` 里的行号只作"人读时去找"的线索 ——
#: 判据不按行号断言（锚点纪律 A：行号会漂），它只断言"这个符号在生产面被调用过 ≥1 次"。
DUTIES: dict[str, dict[str, object]] = {
    "duty1_prescreen": {
        "code": "prescreen",
        "where": "secretary.py",
        # 2026-10-19 现盘重测（原写 617/662 早已漂掉；判据只按符号断言，这三处是给人找的线索，
        # 所以要跟着盘走 —— 治表腐烂时一并更新，判据本体一个字没改）。
        "call": ("secretary.py:1426", "secretary.py:1457", "secretary.py:1753"),
        "visibility": "prompt",
        # 2026-10-19：探针补两词。职责 1 的真身是整条"格式与内容优化"：
        # `optimize_outbound` = `wash_delegation`（洗格式）+ `prescreen`（预筛）。
        # 原先那两个探针只够认领"名字必须是真的 / 会被拒"这一半，洗格式那一半
        # （`wash` / `changes` / `refused` 三格读数）没有任何条目认领 ⇒ 角色看到
        # `washed=true` 也不知道自己被改了哪几处。
        "probe": ("会被拒", "名字必须是真的", "预筛报警", "洗过的格式"),
        "why": "派活前预筛：被拒时给出并列候选，角色必须知道有这一步，否则它只会瞎猜名字。"
               "⚠️ 本条目同时认领**洗格式**那一半（职责 1 的另一段）—— 角色看到的是两段"
               "合并后的**一个**结果，所以它必须同时认得这两件事的读数",
    },
    "duty2_assess": {
        "code": "assess_delegation",
        "where": "secretary.py",
        "call": ("agent_loop.py:5354", "conductor.py:2378"),
        "visibility": "conditional",
        #  2026-10-16 收窄 {D,E,F,G,M} → {D}；2026-10-19 又放回十个，两次都不是
        # "跟着提示词变"，而是两件不同的事被记成了一件事：
        #
        # - 2026-10-16 那次收窄针对的是动作名 `assess` 经伙伴表外泄（那四个角色此前
        #   靠 `partners_lines` 逐条印"可调用动作：… assess（必填 qid）……"看到它）。
        #   收窄本身成立：`assess` 是 D 自己的动作（判证据是否就绪），别人不需要知道。
        # - 但 `assessment` 是秘书的结果键：`agent_loop.py` 的 `_outbound_hook` 对
        #   每一个会派活的角色都无条件调 `assess_delegation`，把结论塞进那一步的结果。
        #   角色不认识这个键，就只能猜"这一格是什么"。
        #
        # ⇒ 探针里那个裸 `assess` 一并删掉：它今天命中的是 `D.assess`（错的东西），
        # 而它把"动作名"与"结果键"混成一条探针，正是上一版看不见缺口的原因。
        # 2026-10-23：`L` 立项后，`roles` 由十格补到十一格 —— 旧名单记录的是
        # L 立项前的角色数。L 是普通角色（出边有 C，它会派活），`_outbound_hook`
        # 同样把 `assessment` 塞进它的那一步 ⇒ 它的提示词里也必须认得这个键。
        "roles": ("A", "B", "C", "D", "E", "F", "G", "H", "L", "M", "V"),
        "probe": ("该不该派", "建议你换", "评估这次派活"),
        "why": "委派评估：'该不该派这一件'（`DECISIONS` 那张词表）+ 同 key 是否重复。"
               "可见性是**十一角色**，理由见上面那两条 ⚠️：收窄针对动作名，"
               "而这条认领的是**结果键**（谁派活谁就收到它）。"
               "⚠️ 探针是**登记**的不是推导的：多一个/少一个都要人来裁",
    },
    "duty3_closure": {
        "code": "remind_closure",
        "where": "secretary.py",
        "call": ("conductor.py:2279",),
        # 2026-10-19：原写 `prompt`（= 十个角色都该知道）+ 探针 `收件箱`/`待办`。
        # 两个错，各自都是假命中：`收件箱` 命中的是"留言会在收件箱里看到"（留言通道），
        # `待办` 命中的是 A 的 `run_once` 领取待办。而真身只在M 的秘书上跑
        # （`conductor.py:2279`，收尾扫描），读数落 `stats()["closure_reminders"]`。
        "visibility": "conditional",
        "roles": ("M",),
        "probe": ("closure_reminders",),
        "why": "闭环提醒：M 的秘书在收尾时列出**谁提交了没人接手 / 谁接了手没终态**，"
               "落在 `conductor.stats()['closure_reminders']`。只有 M 读得到它 ⇒ "
               "登记成 conditional + roles=('M',)；有名单不处置与'查过了没问题'"
               "在报告里必须分得开",
    },
    # S1k-2（2026-10-08 深夜）：名册那一族。提示词里承诺了三件事，这里逐条认领
    # （`code` = 真身，`call` = 生产调用点）。
    "roster_add": {
        "code": "roster_add",
        "where": "secretary.py",
        "call": ("agent_loop.py:4958",),
        "visibility": "prompt",
        "probe": ("父可以自己提名", "由秘书分配", "名字一经分配"),
        "why": "造一个子代理时登记名册（并分配/核对名字）：名字被占或已销号就受控拒绝，"
               "不许静默改名 —— 角色必须知道这条，否则它会以为换个名字重发就能过",
    },
    "roster_retire": {
        "code": "retire",
        "where": "secretary.py",
        "call": ("agent_loop.py:4470",),
        "visibility": "prompt",
        "probe": ("让一个子代理退役", "父决定"),
        "why": "退役由父说、秘书做（三分支）：角色必须知道有这件工具，否则它只能干等",
    },
    # S1g-2（2026-10-09，业主：「"超越职责"的一个主要可能是无法在被分配的读写面内
    # 完成任务，这个秘书也要帮忙看，不只是看任务是否符合角色设计」）：派活那一刻的
    # 面适配读数。提示词里承诺了两句（"秘书还会替你看一遍这件活在被派人的读写面里
    # 做不做得成"与"这一步的结果里有 `surface_fit`"）⇒ 两条探针各认领一句。
    "surface_fit": {
        "code": "surface_fit",
        "where": "secretary.py",
        "call": ("secretary.py 的 surface_readings", "agent_loop.py 的 _outbound_hook"),
        "visibility": "prompt",
        "probe": ("在被派人的读写面里做不做得成", "surface_fit"),
        "why": "面适配：这一件点名要动的盘上路径，在收件方那趟的面里是不是同一个文件 —— "
               "业主点名的『职责之外』那一档的主要来源（面不够）。角色必须知道这一步存在，"
               "否则 `fits=false` 的读数没人看，它只会以为活已经派出去了",
    },
    # 2026-10-14（业主：「秘书侧……评估派发出的任务能否由子代理及子代理的出边共同完成」）：
    # 派活那一刻的能力面读数。提示词里承诺了一句（"秘书会顺手判一遍……"）+
    # 四档名（`in_self`/`via_edges`/`unreachable`/`unknown`）⇒ 这条探针认领它。
    "reach_fit": {
        "code": "reach_fit",
        "where": "secretary.py",
        "call": ("secretary.py 的 reach_fit", "secretary.py 的 surface_readings",
                 "agent_loop.py 的 _outbound_hook"),
        "visibility": "prompt",
        "probe": ("能力面", "reach_fit", "出边上的伙伴", "子代理及子代理的出边"),
        "why": "能力面闭包：这个动作被派人**连同它出边上的伙伴**做不做得成（走哪几跳）—— "
               "只看被派人自己会把「B 要把引文交给 H 判」读成面内做不成，而它其实一跳够得到；"
               "四档只报不改，`unreachable` 由父决定改派/代唤/记成职责之外",
    },
    "duty4_rework": {
        "code": "rework_inbound",
        "where": "secretary.py",
        "call": ("agent_loop.py:5400",),
        "visibility": "internal",
        "why": "收件后重解读：重解读结果由**框架直接替换进交给角色的那批 item**"
               "（`agent_loop.py:5400` 的 `reworked.append(...)`）⇒ 角色无需知情。"
               "⚠️ 这一条是**登记**：实测它在十角色提示词里 0/10 命中（探针见 `probe_internal`）",
    },
    "handoff": {
        "code": "handoff_add",
        "where": "secretary.py",
        "call": ("agent_loop.py:5572",),
        "visibility": "prompt",
        # 探针要覆盖同一种承诺的不同措辞：判据首跑就抓到我只写了"秘书执笔"，
        # 而 M 那边还有"框架会把它交给秘书写成一份交接手稿"、"交给秘书写成手稿并发出去"
        # 两种说法 ⇒ 那两句当时被判成"没人认领的承诺"（假红，但方向是对的：措辞一变就该有人看）。
        "probe": ("秘书执笔", "交给秘书", "写成手稿", "写成交接手稿"),
        "why": "交接手稿由秘书执笔编号；十个角色的提示词都写了这件事（这是唯一一处本来就双向对齐的）",
    },
    # 2026-10-14（业主裁决第 12 条前半：「作为 B 的秘书的任务，判断一个待入库的命题是否
    # 太平凡有没有资格入库」）：入库口那一道审美闸。提示词里承诺了一句
    # （"入库前你的秘书会替你把这一关……判太平凡就把这次入库当场拦下"）⇒ 这条探针认领它。
    #
    # 为什么它必须是可见的那一档（对 B 而言）：拦下来会改变本体那一步的结果
    # （`kind=statement_too_trivial`），而"怎么改才能收进去"只有本体知道
    # （写清后面哪一步会用到它）—— 所以 B 必须知道这台机器存在。
    #
    # 2026-10-19：可见性从 `prompt` 改成 `conditional ("B",)`。原写法等于声明"十个角色都该
    # 知道它"，而代码里只有 B 会撞上这道闸（`judge_statement` 对非 B 直接返回"这一问只属于 B"；
    # `register_statement` 只在 B 的动作表里，其余九角色 0 个）。`prompt` 那一档的判据只要求
    # "有人命中"，所以这个错误永远不会红 —— 登记口径错了要人来裁，这就是那次裁定。
    "statement_aesthetic": {
        "code": "judge_statement",
        "where": "secretary.py",
        "call": ("agent_loop.py 的 _statement_filing_refusal",
                 "agent_loop.py 的 _do_tool（调 registry.call 之前）"),
        "visibility": "conditional",
        "roles": ("B",),
        "probe": ("入库前你的秘书", "太平凡", "statement_too_trivial"),
        "why": "入库审美：B 调 `own.register_statement` 之前，它自己的秘书判一次「这条够不够格」"
               "（三态：合格 / 太平凡 / 判不了；词表 `STATEMENT_VERDICTS`，与派活轴的 `DECISIONS` 分开）；"
               "**只有**『判了且判太平凡』才拦，判不了 / 没查成 / 判断炸了一律 fail-open（+ 留痕）——"
               "让『没查成』决定产出入库正是这一格要避开的那种错",
    },
}

#: `internal` 那一档的"出口探针"：这些词若出现在任何角色的提示词里，
#: 就说明有人把"框架内部的事"当成对角色的承诺写进了提示词 ⇒ 红。
PROBE_INTERNAL = ("重解读", "重新理解", "rework")

#: 普查 `draft/63 §2-①` 点名的另一个接住方：错名时的并列候选。
#: 它不在秘书里（薄转发到 `tools/base.py`），但同一条"双向对齐"纪律适用：
#: 提示词教了「名字必须是真的 / 会被拒」，那"给候选"这件事就必须真的发生。
OTHER_CATCHERS: dict[str, dict[str, object]] = {
    "candidate_tool_names": {
        "where": "tools/base.py",
        "promise": ("名字必须是真的", "会被拒"),
        "call": ("tools/base.py:945 的候选计算", "secretary.py:124 的薄转发"),
        "why": "工具/动作名写错时给并列候选（`secretary.py:116` 的 docstring 逐字写着"
               "「错名的并列候选（薄转发到 tools.base.candidate_tool_names，判据只有一份）」）",
    },
    "notify_reading": {
        "where": "agent_loop.py",
        "promise": ("notify", "summary", "body", "refs"),
        "call": ("agent_loop.py:1723 的 notify_problem = self.notify_reading(payload)",),
        "why": "`draft/63 §2-⑤` 的接住方：`notify` 表的形状与必填由这一层判（它才知道角色），"
               "字段表 = `NOTIFY_FIELDS`（`agent_loop.py:1139` 逐字列了 to/summary/body/refs/why）",
    },
}

#: 登记的"有产出方、今天没有生产调用点"的秘书方法（留读数，不许沉默）。
#: 注意：这一档不是禁令，是登记制：登记了就必须写清"它今天由谁消费"。
#:
#:  2026-10-19 清过；过期的都删了，别拿它当"今天没有调用点"的证明。
#: 上一次清之前这里躺着 13 条，实测 8 条已经活过来了（各自都有真的生产调用点）：
#: `roster_add`(agent_loop.py:4958) · `retire`(agent_loop.py:4470) ·
#: `roster_view`(agent_loop.py:2327/4498/4503/5185) · `resolve_up`(agent_loop.py:5161) ·
#: `alive_path`(secretary.py:746/762/783，由 `bind_task`/`close` 写存活标记) ·
#: `secretary_alive`(secretary.py:3697-3700) · `decisions` · `decisions_path`
#: —— 它们当初的登记理由写的是"随 S1k-2 落地"，S1k-2 早就落地了，而这张表只往下查
#: 不往上查（判据只断言"死的都登记了"，不断言"登记的都还是死的"）⇒ 那 8 条腐烂了半年
#: 也没人知道。要清就得人来清，这就是这次清。
NO_CALL_POINT_TODAY = {
    "pending_inbox": "定义了、`inbox_todos` 之外没有生产调用点（2026-10-07 现算 0 处）—— "
                     "与 `draft/69 §5` 的 R5-㔔 同族：**有产出方没接**，登记为读数而不是删掉",
    "knowledge": "只读访问器（角色画像：briefs/账本/权限位）；生产面今天无调用点，"
                 "由测试与未来的「审校 / 状态报告」入口消费",
    "may_read_narrative": "只读判定（该角色能不能读叙事文本）；生产面今天无调用点，"
                          "由测试消费（权限面的读数，不是派发点）",
    "merged_decisions": "只读访问器（整角色视图：老文件 + 全部分片）；生产面今天无调用点 —— "
                        "WebUI 那一面直接 glob 目录，这一格留给「按角色审账」的入口",
    "roster_repair": "补登记入口；只在写路径被调用（I-15），"
                     "生产面今天无调用点（派活登记那一步走的是 `roster_add`，不经过它）",
}


#: `_outbound_hook` 往"这一步的结果"里放的每一格读数，按角色是否应当知道它分三档（这是第三条轴：
#: 前两张表问"职责"，这一张问读数 —— 秘书在角色正在派活那一刻塞进结果的键，角色认不认得）。
#: 两个方向都会静默出错：代码有、提示词没提 ⇒ 角色把 `alarms: []` 读成"没事"，而"没事"与"没算成"是两件
#: 不同的事（`fail_open` 说后者）—— 三态在提示词这一侧被折平而没有判据会红；提示词提了、代码里没有 ⇒
#: 角色照着找那个键，找不到就会编一个。三种处置（等额：`_outbound_reading_keys()` 必须正好等于三者并集）：
#: `READING_TELL`（角色应当知道，提示词里必须真有这个键名）；`READING_GAP`（应当知道而今天一个提示词都
#: 没提 ⇒ 登记为缺口；等额断言的另一半是"`READING_GAP` 里的键在提示词里必须 0 命中"，所以补上提示词之后
#: 必须删掉这一格 —— 登记会自己过期，不会腐烂成豁免）；`READING_INTERNAL`（框架内部用，必须写 `why`， 且提示词里不许出现）。
READING_TELL: tuple[str, ...] = (
    # 2026-10-19：前两个一直有；后五个是这一批补上的 —— `agent_prompts.py`「规则：」块里
    # 新增的那一行（"派活先过秘书：`alarms` 预筛报警、`wash`/`changes` 洗过的格式、
    # `assessment` 该不该派；`refused` 非空即被拒，`fail_open` 为真是没查成。"）
    # 逐字点名了它们。它们从 `READING_GAP` 搬过来，不是被放宽掉的缺口。
    "surface_fit", "reach_fit",
    "alarms", "wash", "changes", "assessment", "fail_open",
)

#: 角色应当知道、今天却没有一个提示词提过的读数（登记为缺口，等主控抬版本时一并补）。
#:
#: 2026-10-19 清过一次：`alarms` / `wash` / `changes` / `assessment` / `fail_open`
#: 五个已经随那一行进了十格提示词 ⇒ 搬进 `READING_TELL`。剩两条，如实留在缺口里
#: （那一行 97 字装不下，装下了也要挤掉别的）：
READING_GAP: dict[str, str] = {
    "negotiation": "秘书⇄秘书协商这一格的结论（第几轮、收敛没有）。"
                   "只在同 key 有重复候选、或结论含'重排 / 重复'时出现",
    "escalate_to_body": "协商两轮仍未收敛 ⇒ 这一条**上报本体**。"
                        "它出现就是'轮到你表态'；角色不认识这个键，就只能干等一个不会来的回音",
}

#: 框架内部用的分格：角色无需知情（提示词里出现就要红 —— 那会成为"承诺一件角色看不见的事"）。
READING_INTERNAL: dict[str, str] = {
    "problem": "`\"；\".join(alarms)` 的同一份内容再拼成一句 —— 认 `alarms` 就够，"
               "它是给日志与回执读的",
    "reach_bad_targets": "`summon_many` 那一支的汇总索引（哪几项 `unreachable`），"
                         "是 `reach_fit` 的分格",
    "reach_reason": "同一格的逐项理由串（`reach_fit` 的分格）",
    "assessment_fail_open": "`fail_open` 那一族的分格：评估那一格炸了。认总的那一格就够",
    "negotiation_fail_open": "同上：协商那一格炸了",
    # 2026-10-21（两段式：洗 → 请示 → 确认 → 才执行）：这一格是钩子与循环之间的承载键
    # （与 `_washed_payload` 同族，只是它不以 `_` 打头 —— 因为它装的是几个有名字的读数）。
    # 循环取完就 pop 掉，不进这一步的结果；角色真正读到的是循环按它摆出来的那几格
    # （`outcome="wash_proposed"` / `proposal_id` / `changes` / `diff` / `next`）——
    # 那是 `agent_loop.run` 的结果面，不在本表扫描的范围内（本表扫的是 `_outbound_hook`）。
    "wash_proposal": "秘书 → 循环的承载键（这一次执行哪一份 / 要不要先请示）。"
                     "循环 pop 掉它，再把它摆成 `outcome` / `proposal_id` / `changes` / "
                     "`diff` / `next` 这几格给角色 —— 角色认的是那几格，不是这个键",
}


def _roles_and_prompts() -> dict[str, str]:
    """渲染十一个角色的提示词（A–H,V,L 十个可召唤 + 主控 M；口径 = `tests/test_agent_surface_snapshot.py::_build/_snapshot`）。"""
    from agentflow.store import Store
    from agentflow.tools import ROLES, build_registry
    from agentflow.agent_prompts import system_prompt
    from agentflow.tools import TOOL_ROLES

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="align-two-way-"))
    ws = tmp / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    full = build_registry(store=st, workspace_root=ws, roles=tuple(ROLES), strict=True).registry
    out: dict[str, str] = {}
    for role in (*TOOL_ROLES, "M"):
        out[role] = system_prompt(role, registry=full)
    return out


def _secretary_source() -> str:
    import agentflow.secretary as SEC

    return pathlib.Path(SEC.__file__).read_text(encoding="utf-8")


def _src_text(rel: str) -> str:
    import agentflow

    return (pathlib.Path(agentflow.__file__).parent / rel).read_text(encoding="utf-8")


def _called_in_production(symbol: str) -> list[str]:
    """`symbol` 在生产面（`src/agentflow` 的 py）被调用的每一处。

    两种调用形态都要认（第一版只认第一种，于是把 `candidate_tool_names` 误报成"死的"）：属性调用 `.symbol(` —— 例如 `self.secretary.prescreen(...)`；
    2. 裸调用 `symbol(` —— 例如 `from .tools.base import candidate_tool_names` 之后的直接调用。

    刻意排除三类"看着像调用"的行：`def symbol(`（那是定义）、`from/import` 行、以及行首是注释或引号的行（本仓的 docstring 大量引用代码，不排会把"提及"当成"调用"）。
    紧跟在反引号后的名字也排除（`` `symbol(…)` `` 是文档里的引用，不是调用）。已知口径边界（如实写在判据里，免得下一个人把命中数当精确值）：多行字符串内部的行认不出来—— 例如提示词正文里那句"写这一行的是
    `self.secretary.handoff_add(...)`"会被算成一处。所以调用点的条数只作"非空"判据（`assert calls`），不作精确计数；要精确数就得走 `ast`（本判据刻意不引 `ast`：
    它要的是"生产面到底有没有人调它"这一档，而这一档用行级扫描已经够，且不依赖被扫文件的语法能否解析）。
    """
    import re as _re

    root = pathlib.Path(__import__("agentflow").__file__).parent
    attr = _re.compile(r"\." + _re.escape(symbol) + r"\s*\(")
    bare = _re.compile(r"(?<![\w.`])" + _re.escape(symbol) + r"\s*\(")
    hits: list[str] = []
    for p in sorted(root.rglob("*.py")):
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            s = ln.lstrip()
            if s.startswith(("#", '"', "'", "def ", "from ", "import ")):
                continue
            if attr.search(ln) or bare.search(ln):
                hits.append(f"{p.relative_to(root)}:{i}")
    return hits


def _secretary_claims(text: str) -> list[str]:
    """提示词里"对秘书的承诺"：把提到「秘书」的句子抽出来（句级，去重）。"""
    parts = [s.strip() for s in re.split(r"[。\n]", text) if "秘书" in s]
    return [p for p in parts if p]


# --------------------------------------------------------------------------------------
# 方向一：代码 → 提示词
# --------------------------------------------------------------------------------------

def test_every_secretary_duty_is_either_visible_to_roles_or_registered_internal() -> None:
    prompts = _roles_and_prompts()
    reading: dict[str, object] = {"roles": len(prompts), "duties": len(DUTIES)}
    problems: list[str] = []

    for key, spec in DUTIES.items():
        probe = tuple(spec.get("probe", ()))  # type: ignore[arg-type]
        vis = spec["visibility"]
        seen = tuple(r for r, t in prompts.items() if any(k in t for k in probe)) if probe else ()
        reading[f"{key}.seen_in"] = len(seen)

        if vis == "prompt":
            if not seen:
                problems.append(
                    f"{key}：{spec['why']} —— 但十角色提示词里**一个**出口探针都没命中 "
                    f"{probe} ⇒ 这是'代码 → 提示词'那一向的缺口（角色不知道它存在）")
        elif vis == "conditional":
            want = tuple(spec.get("roles", ()))  # type: ignore[arg-type]
            if tuple(sorted(seen)) != tuple(sorted(want)):
                problems.append(
                    f"{key}：登记该知道它的角色是 {sorted(want)}，而提示词里实际命中 {sorted(seen)} "
                    f"⇒ 两边**不等额**（多一个/少一个都要人来裁，不许自动跟着变）")
        elif vis == "internal":
            if not spec.get("why"):
                problems.append(f"{key}：登记为 internal 但没写 why")
            hit = tuple(r for r, t in prompts.items() if any(k in t for k in PROBE_INTERNAL))
            if hit:
                problems.append(
                    f"{key}：登记为'框架内部、角色无需知情'，可是 {list(hit)} 的提示词里出现了"
                    f"{PROBE_INTERNAL} 这类出口词 ⇒ 提示词在承诺一件角色看不见的事")

    # 2026-10-23：L 立项后是十一个角色（A–H,V,L 十个可召唤 + 主控 M）。
    # 旧断言写 10，记录的是 L 立项前的角色数 —— 这里不是放宽，是把渲染面跟上真身。
    assert reading["roles"] == 11, f"只渲染到 {reading['roles']} 个角色 ⇒ 这一格没查成"
    assert reading["duties"] >= 5, reading
    assert not problems, ("秘书职责与提示词**没有双向对齐**：\n  - " + "\n  - ".join(problems))


# --------------------------------------------------------------------------------------
# 方向二：提示词 → 代码
# --------------------------------------------------------------------------------------

def test_every_promise_about_the_secretary_has_a_code_catcher() -> None:
    prompts = _roles_and_prompts()
    claimed_by: dict[str, set[str]] = {}
    for role, text in prompts.items():
        for claim in _secretary_claims(text):
            claimed_by.setdefault(claim, set()).add(role)

    # 反真空：抽不到任何承诺 ⇒ 扫描面坏了，不是"没问题"。
    assert claimed_by, "十角色提示词里一句'秘书'相关的话都没抽到 ⇒ 抽取面坏了（不是没问题）"

    # 每条承诺必须能映射到表里一个"对角色可见"的条目。
    prompt_visible_probes = {
        k: tuple(v.get("probe", ()))  # type: ignore[arg-type]
        for k, v in DUTIES.items() if v["visibility"] in ("prompt", "conditional")
    }
    unmapped = [c for c in claimed_by
                if not any(k in c for k in PROBE_INTERNAL)
                and not any(any(p in c for p in probes) for probes in prompt_visible_probes.values())]
    assert not unmapped, (
        "这些句子在对角色承诺'秘书会做某事'，但表里没有任何一条职责认领它"
        "（= 承诺了一个没人接住的接住方）：\n  - " + "\n  - ".join(f"[{'/'.join(sorted(claimed_by[c]))}] {c[:120]}" for c in unmapped))

    # 被承诺的那些条目：代码真身必须在，且在生产面被真的调用过。
    for key, spec in DUTIES.items():
        if spec["visibility"] == "internal":
            continue
        probes = tuple(spec.get("probe", ()))  # type: ignore[arg-type]
        claimed = [c for c in claimed_by if any(p in c for p in probes)]
        if not claimed:
            continue
        assert spec["code"] in _src_text(str(spec["where"])), (
            f"{key}：提示词承诺了它（{len(claimed)} 句），而 `{spec['where']}` 里找不到符号 "
            f"`{spec['code']}` ⇒ 承诺了一个不存在的接住方")
        calls = _called_in_production(str(spec["code"]))
        assert calls, (
            f"{key}：提示词承诺了 `{spec['code']}`，但它在生产面**一次都没被调用** ⇒ "
            f"这个接住方今天是死的（登记线索：{spec['call']}）")


# --------------------------------------------------------------------------------------
# 等额：代码里出现的职责编号必须都在表里
# --------------------------------------------------------------------------------------

def test_every_duty_number_in_the_code_is_registered_here() -> None:
    src = _secretary_source()
    nums = sorted({int(m.group(1)) for m in re.finditer(r"duty=(\d)", src)})
    assert nums, "`secretary.py` 里一个 `duty=N` 都没扫到 ⇒ 扫描面坏了（不是没问题）"
    registered = {int(k[4]) for k in DUTIES if k.startswith("duty")}
    assert set(nums) == registered, (
        f"代码里出现的职责编号 {nums} 与表里登记的 {sorted(registered)} 不等额 —— "
        "新加一项职责必须在这张表里登记（它要不要让角色知道，是人来裁的）")


def test_secretary_methods_without_a_call_point_are_registered() -> None:
    """有产出方、今天没有生产调用点的秘书方法 ⇒ 必须登记（留读数，不许沉默）。"""
    import agentflow.secretary as SEC

    public = [n for n in dir(SEC.Secretary) if not n.startswith("_")]
    dead = sorted(n for n in public if callable(getattr(SEC.Secretary, n, None))
                  and not _called_in_production(n))
    unregistered = [n for n in dead if n not in NO_CALL_POINT_TODAY]
    assert not unregistered, (
        "这些秘书方法今天在生产面**没有调用点**，却没有登记（登记表 = `NO_CALL_POINT_TODAY`）："
        f"{unregistered}\n  （登记过的：{sorted(NO_CALL_POINT_TODAY)}）")


# --------------------------------------------------------------------------------------
# 同一条纪律：普查点名的其它接住方（不在秘书里的那些）也要双向
# --------------------------------------------------------------------------------------

def test_other_named_catchers_are_two_way_aligned() -> None:
    """`draft/63 §2` 的"谁接住"那一栏还点名了秘书之外的组件；同一条纪律适用。

    这里只登记真正会被提示词承诺的那些（今天一条：错名的并列候选）。
    不在秘书里不影响判定 —— 判据问的是同一件事：承诺了就得真做。
    """
    prompts = _roles_and_prompts()
    reading: dict[str, object] = {}
    problems: list[str] = []
    for sym, spec in OTHER_CATCHERS.items():
        promise = tuple(spec["promise"])  # type: ignore[arg-type]
        seen = sorted(r for r, t in prompts.items() if any(p in t for p in promise))
        reading[sym] = len(seen)
        if not seen:
            problems.append(f"{sym}：十角色提示词里没有任何人被告知 {promise} ⇒ 接住方没人知道它存在")
        if sym not in _src_text(str(spec["where"])):
            problems.append(f"{sym}：`{spec['where']}` 里找不到这个符号 ⇒ 提示词承诺了一个不存在的东西")
        calls = _called_in_production(sym)
        if not calls:
            problems.append(
                f"{sym}：提示词承诺了它（{len(seen)} 个角色），而它在生产面**一次都没被调用** ⇒ "
                f"这个接住方今天是死的（登记线索：{spec['call']}）")
    assert reading, "表是空的 ⇒ 这一格没查成"
    assert not problems, ("其它接住方与提示词**没有双向对齐**：\n  - " + "\n  - ".join(problems))


# --------------------------------------------------------------------------------------
# 负控：两个方向各自都要"能红"
# --------------------------------------------------------------------------------------

def test_the_alignment_check_can_actually_go_red_both_ways() -> None:
    """负控（不依赖真文件的内容，只用判据自己的形状）：

    - 方向二：编一句"秘书会替你把结论写成章节" ⇒ 表里没有任何条目认领它 ⇒ 必须能被认出来；
    - 方向一：把 `duty4_rework` 的可见性从 internal 改成 prompt ⇒ 它的探针在十角色里 0 命中
      ⇒ 必须被判红。
    """
    fake_claim = "框架会让秘书替你把结论写成章节。"
    prompt_visible_probes = {
        k: tuple(v.get("probe", ()))  # type: ignore[arg-type]
        for k, v in DUTIES.items() if v["visibility"] in ("prompt", "conditional")
    }
    claimed = not any(any(p in fake_claim for p in probes) for probes in prompt_visible_probes.values())
    assert claimed, "负控失败：编的这句承诺被表里某条职责认领了 ⇒ 这条负控是空转"

    prompts = _roles_and_prompts()
    seen4 = tuple(r for r, t in prompts.items() if any(k in t for k in ("重解读", "重新理解")))
    assert not seen4, (
        f"`duty4_rework` 登记为 internal（角色无需知情），可是 {list(seen4)} 的提示词里出现了它的出口词 ⇒ "
        "把它改成 prompt 就会红（这条负控证明了那一半有牙）")


# --------------------------------------------------------------------------------------
# 第三条轴：「秘书」这两个字出现在谁的提示词里，就得有一条该角色知道的职责认领它
# --------------------------------------------------------------------------------------
#
# 前两条轴问的是"每条职责有没有人对得上话"。这一条反过来问：每一句话有没有出处。
# 为什么要单独一条：一条职责可以登记成 `prompt`（= 十个角色都该知道），而实际只有
# 一个角色知道 —— 前两条轴的 `assert seen` 只要求"有人命中"，于是那一格照样绿。
# 反过来，一句谁也没登记的"秘书会替你 X"混进某一份提示词，前两条轴也照样绿
# （它不被任何 duty 的 probe 认领 ⇒ 进不了 `claimed_by`）。这一条就是补这两个洞。

def _sentences(text: str) -> list[str]:
    """句级切分（与 `_secretary_claims` 同一口径：句号与换行）。"""
    return [s.strip() for s in re.split(r"[。\n]", text) if s.strip()]


def _admits(spec: dict, role: str) -> bool:
    """这条职责的可见性允许 `role` 知道它吗（`internal` 永远不允许）。"""
    vis = spec["visibility"]
    if vis == "prompt":
        return True
    if vis == "conditional":
        return role in tuple(spec.get("roles", ()))  # type: ignore[arg-type]
    return False


def _claimants(sentence: str, role: str) -> list[str]:
    """这一句"对秘书的承诺"能被表里哪几条职责认领（且那些职责允许 `role` 知道）。"""
    return [k for k, spec in DUTIES.items()
            if _admits(spec, role)
            and any(p in sentence for p in tuple(spec.get("probe", ())))]  # type: ignore[arg-type]


def _unclaimed_secretary_mentions(prompts: dict[str, str]) -> dict[str, list[str]]:
    """每一份提示词里"提到秘书、却没有一条该角色可知道的职责认领"的句子。"""
    bad: dict[str, list[str]] = {}
    for role, text in prompts.items():
        for s in _sentences(text):
            if "秘书" not in s:
                continue
            if not _claimants(s, role):
                bad.setdefault(role, []).append(s[:160])
    return bad


def test_every_secretary_mention_is_claimed_by_a_duty_that_role_may_know() -> None:
    """每个角色的提示词里，凡出现「秘书」字样，必须命中一条 `visibility` 含该角色的职责。

    这一条守的是"每一句话都有出处"：不是"表里某条职责有人命中"（那是方向一），
    而是"这一句在那个角色那儿是登记过的"。两个反例都是真红过的形态：

    - 一句谁也没登记的承诺（"秘书会替你 X"）塞进某一份提示词 ⇒ 角色按它行事会撞墙；
    - 一句登记为 `conditional`（只该 D 知道）的承诺出现在 H 的提示词里
      ⇒ 那正是 2026-10-16「M 只派活」那次收窄要挡的泄漏（见 `duty2_assess` 的 `why`）。
    """
    prompts = _roles_and_prompts()
    unclaimed = _unclaimed_secretary_mentions(prompts)

    # 反真空：一句"秘书"都抽不到 ⇒ 抽取面坏了，不是"没问题"。
    mentions = {r: [s for s in _sentences(t) if "秘书" in s] for r, t in prompts.items()}
    total = sum(len(v) for v in mentions.values())
    assert total > 0, "十一个角色提示词里一句'秘书'都没抽到 ⇒ 抽取面坏了（不是没问题）"
    # 2026-10-23：L 立项后是十一个角色（A–H,V,L 十个可召唤 + 主控 M）；
    # 旧断言写 10，记录的是 L 立项前的角色数 —— 不是放宽，是跟上真身。
    assert len(prompts) == 11, f"只渲染到 {len(prompts)} 个角色 ⇒ 这一格没查成"

    assert not unclaimed, (
        "这些句子在提示词里对角色承诺'秘书会做某事'，而 `DUTIES` 里没有任何一条"
        "**该角色可知道**的职责认领它（= 承诺了一个没人接住的接住方，"
        "或把一个只该部分角色知道的职责泄漏了出去）：\n  - "
        + "\n  - ".join(f"[{r}] {s}" for r, rows in unclaimed.items() for s in rows))


def test_the_secretary_mention_rule_can_actually_go_red() -> None:
    """负控：上面那条判据的两个牙都要能咬（用同一套 helper，不复制判据）。"""
    prompts = _roles_and_prompts()

    # 基线：真提示词本来就该是绿的（否则负控在替一条已经红的判据作证）。
    assert not _unclaimed_secretary_mentions(prompts), "基线就不绿 ⇒ 下面的负控没有意义"

    # 牙 ①（方向二）：一句 DUTIES 之外的秘书承诺。
    fake = "框架会让秘书替你把结论写成章节。"
    assert not _claimants(fake, "A"), "负控空转：编的这句承诺被表里某条职责认领了"
    poisoned = dict(prompts)
    poisoned["A"] = prompts["A"] + "\n- " + fake + "\n"
    assert _unclaimed_secretary_mentions(poisoned).get("A"), (
        "负控失败：塞进 A 的提示词之后仍然查不出来 ⇒ 这条判据对'没登记的承诺'没有牙")

    # 牙 ②（可见性）：一句只该 M 知道的职责（`conditional`，`roles=('M',)`），塞给 H。
    #
    # 2026-10-19：这一格原先拿 `duty2_assess` 当例子（那时它 roles=('D',)）。同一天那次
    # 登记把它放回十个角色了 ⇒ 那个例子不再"只该一部分角色知道"。改用 `duty3_closure`
    # （闭环提醒只有 M 的秘书会跑，`conditional + roles=('M',)`）——
    # 负控的举例也要跟着登记走，否则它会变成一句永远成立的自我安慰。
    leak = "你的秘书会在收尾时给你一格 `closure_reminders`（谁没接手、谁没终态）。"
    assert _claimants(leak, "M"), "负控空转：这句本该被 `duty3_closure` 认领"
    assert not _claimants(leak, "H"), "负控空转：这句对 H 也被认领了 ⇒ 可见性那一半没在起作用"
    poisoned2 = dict(prompts)
    poisoned2["H"] = prompts["H"] + "\n- " + leak + "\n"
    assert _unclaimed_secretary_mentions(poisoned2).get("H"), (
        "负控失败：把一条 `conditional` 职责泄漏给 H 之后仍然查不出来 ⇒ 可见性那一半没牙")


# --------------------------------------------------------------------------------------
# 第四条轴：`_outbound_hook` 交回来的那些读数键，角色认不认得
# --------------------------------------------------------------------------------------
#
# 前三轴查的是"职责"与"承诺"。这一轴查"键"：秘书把哪些读数塞进了这一步的结果。
# 键名是角色唯一能抓住的东西 —— 它没有别的途径知道"这一步多了一格叫 assessment"。

def _function_body(src: str, name: str) -> str:
    """从 `src` 里取出方法 `name` 的正文（到下一个同缩进的 `def` 为止）。

    刻意不引 `ast`：本判据要的是"这个键有没有人放进去"这一档，
    行级/正则扫描已经够，而且不依赖被扫文件此刻能否解析（与 `_called_in_production` 同一取舍）。
    """
    head = re.search(r"^    def " + re.escape(name) + r"\(", src, re.M)
    assert head, f"`agent_loop.py` 里找不到方法 {name} ⇒ 这一格没查成（不是没问题）"
    nxt = re.search(r"^    def ", src[head.end():], re.M)
    end = head.end() + nxt.start() if nxt else len(src)
    return src[head.start():end]


def _outbound_reading_keys() -> list[str]:
    """`_outbound_hook` 往结果里放的每一格（去掉 `_` 打头的模块内部承载键）。"""
    body = _function_body(_src_text("agent_loop.py"), "_outbound_hook")
    keys = {m.group(1) for m in re.finditer(r'out\["([A-Za-z_][A-Za-z0-9_]*)"\]\s*=', body)}
    return sorted(k for k in keys if not k.startswith("_"))


def _key_named(text: str, key: str) -> bool:
    """这个键名在 `text` 里出现过吗（按标识符边界判，别把 `roster_problem` 当成 `problem`）。"""
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(key) + r"(?![A-Za-z0-9_])", text) is not None


def _secretary_sentence_names(text: str, key: str) -> bool:
    """有没有一句谈到秘书的话点了这个键名。

    为什么必须限定在"谈到秘书的那一句"：本文件问的是"角色有没有被告知秘书做这件事"。
    裸键名会撞车 —— 现算读数：`problem` 在十份提示词里都出现过一次，出现在
    「你不是主控 ⇒ 这一句会被受控拒绝（`problem` 是 `not_conductor`）」那一句里，
    讲的是 `ask_user` 的拒绝理由码，与秘书没有关系。按裸键名判，这一格会红得毫无意义
    （而"让假阳性把判据变成噪音"是本仓反复踩过的坑）。
    """
    return any("秘书" in s and _key_named(s, key) for s in _sentences(text))


def _reading_registry_problems(prompts: dict[str, str], keys: list[str]) -> list[str]:
    """登记表与实测的三方对账（TELL 必须有 · GAP/INTERNAL 必须没有 · 三者等额）。"""
    problems: list[str] = []
    tell = set(READING_TELL)
    gap = set(READING_GAP)
    internal = set(READING_INTERNAL)

    for a, b, an, bn in ((tell, gap, "READING_TELL", "READING_GAP"),
                         (tell, internal, "READING_TELL", "READING_INTERNAL"),
                         (gap, internal, "READING_GAP", "READING_INTERNAL")):
        if a & b:
            problems.append(f"{an} 与 {bn} 重叠：{sorted(a & b)} —— 一格只能有一种处置")

    scanned = set(keys)
    registered = tell | gap | internal
    if scanned - registered:
        problems.append(
            f"`_outbound_hook` 交回了这些键，而登记表里一个处置都没给：{sorted(scanned - registered)} "
            "—— 角色认不认得它、要不要知道它，必须有人裁（这是登记制，不许沉默）")
    if registered - scanned:
        problems.append(
            f"登记表里有这些键，而 `_outbound_hook` 今天根本不交回它：{sorted(registered - scanned)} "
            "—— 提示词若照着它写，就是在承诺一件不会发生的事（或这一格已经改名，登记该跟着走）")

    for key in sorted(tell):
        hit = sorted(r for r, t in prompts.items() if _secretary_sentence_names(t, key))
        if not hit:
            problems.append(
                f"{key}：登记为'角色应当知道'，可是十角色提示词里没有一句话在谈秘书的同时 "
                "点了这个键名 ⇒ 这是'代码 → 提示词'那一向的缺口")
    for key in sorted(gap):
        if not str(READING_GAP[key]).strip():
            problems.append(f"{key}：登记在 READING_GAP 里却没写清'不知道它会怎样'")
        hit = sorted(r for r, t in prompts.items() if _secretary_sentence_names(t, key))
        if hit:
            problems.append(
                f"{key}：已经有谈秘书的话在 {hit} 的提示词里点了它 ⇒ 把它从 `READING_GAP` 里删掉"
                "（登记制的等额另一半：补了提示词就必须撤掉缺口登记，否则这张表会腐烂成豁免）")
    for key in sorted(internal):
        if not str(READING_INTERNAL[key]).strip():
            problems.append(f"{key}：登记为 internal 却没写 why")
        hit = sorted(r for r, t in prompts.items() if _secretary_sentence_names(t, key))
        if hit:
            problems.append(
                f"{key}：登记为'框架内部、角色无需知情'，可是 {hit} 的提示词里有谈秘书的话点了它 "
                "⇒ 提示词在承诺一件角色看不见的事")
    return problems


def test_every_outbound_reading_is_either_told_to_roles_or_registered() -> None:
    """`_outbound_hook` 交回来的每一格读数：要么提示词里说了，要么有人签字说不用知道。

    为什么这一格必须存在：秘书在一个角色正在派活那一刻交给它的东西，全部是键名。
    键名不进提示词，角色就只有一个来源能认识它们 —— 猜。而这一族里有一格叫
    `fail_open`，它和 `alarms: []` 在纸面上长得几乎一样而含义正好相反
    （"查过了没问题" vs "没查成"）。本仓最贵的那一类错，就长在这个缝里。
    """
    prompts = _roles_and_prompts()
    keys = _outbound_reading_keys()

    # 反真空：扫不到键 ⇒ 扫描面坏了（不是"没有问题"）。
    assert len(keys) >= 10, f"只从 `_outbound_hook` 扫到 {len(keys)} 个键 ⇒ 扫描面坏了：{keys}"
    # 2026-10-23：L 立项后是十一个角色（A–H,V,L 十个可召唤 + 主控 M）；
    # 旧断言写 10，记录的是 L 立项前的角色数 —— 不是放宽，是跟上真身。
    assert len(prompts) == 11, f"只渲染到 {len(prompts)} 个角色 ⇒ 这一格没查成"

    problems = _reading_registry_problems(prompts, keys)
    assert not problems, ("`_outbound_hook` 的读数与提示词没有对齐：\n  - " + "\n  - ".join(problems))


def test_the_reading_registry_can_actually_go_red() -> None:
    """负控：这张登记表的两个牙（多登记一个键 / 缺登记一个键）都要能咬。"""
    prompts = _roles_and_prompts()
    keys = _outbound_reading_keys()
    assert not _reading_registry_problems(prompts, keys), "基线就不绿 ⇒ 下面的负控没有意义"

    # 牙 ①：代码里多出一格没人处置的读数。
    assert _reading_registry_problems(prompts, sorted(set(keys) | {"brand_new_reading"})), (
        "负控失败：`_outbound_hook` 多交回一格、登记表没写，也查不出来")

    # 牙 ②：登了一个代码里根本不交回的键（提示词若照着写就是空承诺）。
    assert _reading_registry_problems(prompts, sorted(set(keys) - {"assessment"})), (
        "负控失败：登记了 `assessment` 而代码里没有它，也查不出来")

    # 牙 ③：一个登记在 `READING_GAP` 的键偷偷进了谈秘书的那一句（缺口登记会腐烂成豁免）。
    #
    # 2026-10-19：原先拿 `alarms` 当例子，同一天它已随提示词搬进 `READING_TELL` ⇒ 这里改用
    # 仍在缺口里的 `negotiation`。负控的举例必须跟着登记表走。
    assert "negotiation" in READING_GAP, "负控空转：`negotiation` 已经不在缺口表里了，换个例子"
    leaked = dict(prompts)
    leaked["A"] = prompts["A"] + "\n- 你的秘书会在协商不收敛时给你一格 `negotiation`。\n"
    assert _reading_registry_problems(leaked, keys), (
        "负控失败：`READING_GAP` 里的键进了提示词，却没人要求撤掉缺口登记")

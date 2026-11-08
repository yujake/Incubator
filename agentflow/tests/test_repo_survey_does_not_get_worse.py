"""软判据：仓库的体量读数不许比基线更差（`tools/repo_survey.py` 的守门人）。

## 为什么是"软"判据

体量不是缺陷。一个 5000 行的文件可能是该那么大，一个 4000 行的类也可能是该那么大。
所以这条判据不判定"多少行算坏"，它只判定一件事：不许比基线更差。
基线是常量（下面 `BASELINE`），实测是脚本现跑一遍的数 —— 于是"这棵树在长大"
这件事第一次有了机器读数，而不是靠谁哪天翻一遍文件列表说一句"好像又胖了"。

## 为什么基线写死、且必须带日期

写死是刻意的：如果基线跟着实测一起动，"≤ 基线"就永远成立，这条判据会退化成
一句同义反复（本项目最忌的形态：看起来在检查，实际什么都没检查）。
所以基线写死，破了就得有人来改它 —— 而改它这一步必须有人回答"这次长大是不是有意的"。
`BASELINE_OBSERVED` 记的是这组常量观测到的时刻，没有它，下一个人无法判断
"这个数是当次值还是三年前的值"。

## 反真空：没扫到不等于没问题

扫描面被打桩成空目录时，`tools/repo_survey.py` 的 `survey()` 会返回
`scanned_ok=False` 而不是一份"0 个大文件"的漂亮读数。这里的那条负控就是为了证明
它真的会红：`test_empty_scan_surface_is_not_green` 把扫描面换成空目录，
断言判据会报"没扫到 = 没查成"。没有这条负控的话，"0 个大文件 ≤ 60"会让一棵
空树或一个写错的根路径无条件通过 —— 而"通过"与"没查到"混在一起，正是这个仓库
反复踩过的那个坑（三态纪律）。

## 量法

判据不另写一套算法，它 import `tools/repo_survey.py` 并调它的 `survey()`
（判据与被判的对象必须是同一份实现，"量法不同"是这个项目最贵的那类缺陷）。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: 被判的脚本（只读巡检；不进发布门）。
SURVEY_PATH = REPO / "tools" / "repo_survey.py"

#: 基线（常量，不随实测漂）：键名 = `_metrics()` 的键。
#:
#: 观测时刻：2026-10-26（本批 B 类的复测读数，`python tools/repo_survey.py`）。
#: 三个口径分别是：`>800` 行的 src 文件数 / 源码跨度 `>200` 行的函数个数
#: （不含 class —— 函数 77 与 def+class 合计 105+ 是两个都成立的事实，
#: 基线钉的是函数那一格，因为"函数在长"才是那段代码在失去结构的信号）/
#: 跨文件逐字重复的 docstring 段数（>= 80 字符）。
#:
#: 为什么这次抬基线（2026-10-23 的 60 / 63 / 4 → 2026-10-26 的 69 / 77 / 5）：长大是有意的，
#: 且每一格都能点名 —— `src_files_gt800_lines` 源于 2026-10-24/26 各 lane 新落的顶层模块
#: （`clock.py` 4,488 行、`depsection.py` 1,163、`errorstats.py` 947、`agenttrace.py` 588、
#: `readouts.py` 726、`propositionkey.py` 791、`statementfission.py` 300、`stepdispatch.py` 303）
#: 与既有文件的合法增行（`agent_loop.py` 8,535 → 12,063、`secretary.py` 8,842）；
#: `src_functions_gt200_lines` 是同一批新增（时钟与派单两条线各带一串长函数）；
#: `dup_docstring_segments` 4 → 5 那一条是 D-53 的业主原话在 `clock.py` 与
#: `tools/clock_tools.py` 两处逐字引用（引文必须逐字，不许改写 —— 与 L 协作面那条同形）。
#: 判据本身的语义一个字没动：它仍然是"不许比基线更差"，抬完仍然只许降、不许再涨。
BASELINE: dict[str, int] = {
    # 2026-10-28：69 → 70。理由：这一批在 `conductor.py` 里补了 pid 复用判定
    # （`_process_image_name` + `programs_reading` 的那一段），那份文件本就超过 800 行；
    # 别的文件没有新过线的。抬这一格是有意的，不是"顺手改了基线"。
    # 2026-11-01：70 → 71。理由：这一批新增了 `src/agentflow/vsigns.py`（1033 行，单职责：
    # 写签 / 认签 / 派生索引 / 回执与送达读口 / 位推导 / 门读数），是「有意新增的单职责模块」，
    # 不是既有模块被写胖过线。`READING-MAP.md` 开头那三格同批 +1
    # （257 / 225,440 / 70 → 258 / 227,822 / 71）。判据语义一个字没动：抬完仍然只许降、不许再涨。
    # 2026-11-03：71 → 72。理由：这一批新增了 `src/agentflow/vreceipts.py`（840 行，单职责：
    # 先落意图再开板项、收件人 = 送审者、收工前 `backfill`、`outbox_index` / `outbox_digest`），
    # 是「有意新增的单职责模块」，不是既有模块被写胖过线 —— 逐文件比对改前那 71 个过线文件
    # （基线提交 `ddace7ae` 的 blob vs 当次盘上）：新过线的只有它一个，没有掉回线下的，
    # 其余 8 个本就过线的文件只是继续在长（`agent_loop.py` 12,959 → 12,973、
    # `vsigns.py` 1,033 → 1,089 等）。`READING-MAP.md` 开头那三格已在本批按当次盘上追平
    # （261 / 229,901 / 72 —— 与这一格同一读数；复跑命令见该文档 `:10`，
    # 判据 `tests/test_reading_map_counts.py` 现算钉住）。
    # 判据语义一个字没动：抬完仍然只许降、不许再涨。
    # 2026-11-01：72 → 73。理由（逐提交量过"是哪一笔跨的线"，不是"顺手改了基线"）：
    # `src/agentflow/webui/state.py` 785 → 857 行，在 1328e94b（2026-11-01
    # 「判据（先红）：判档那一问的词表只剩 T0-T4（三态、旧行折算与反真空 5 条）」）
    # 这一笔跨过 800 —— 是「既有文件被写胖过线」，不是新落的单职责模块；那一笔把
    # 逐类三态、旧行折算与反真空的读数都落在 `_scan` 那一段里。此前有过"是不是
    # stale_loop 那笔写胖的"的猜测，逐提交量过：不是（d46cdbaf 那笔只动 5 行）。
    # 判据语义一个字没动：抬完仍然只许降、不许再涨。
    # 2026-11-04 再抬 73 → 74。一格，能点名（逐条按文件比对基线提交 f3408ef6 与
    # HEAD；只有这一条新过线，没有一条掉回线下）：`src/agentflow/agent_d/write_report.py`
    # 新过 800 行 —— 今晚的索引四格 / 阅读路收口落在同一个写报告的模块里。
    # 判据语义一个字没动：抬完仍然只许降、不许再涨。
    # 2026-11-04 再抬 74 → 75。一格，能点名（逐条按文件比对基线提交 2bd8efc4 与
    # HEAD；只有这一条新过线，没有一条掉回线下）：`src/agentflow/agent_f/manuscript.py`
    # 620 → 890 行 —— 业主裁定 甲（正文必须由手稿承载）那一批把「转正 / 按号改名 /
    # 搬签块 / 补命题号行」四件事落在同一个写稿模块里（新增 `promote_manuscript`、
    # `carry_sign_block`、`ensure_statement_line`、`formal_shape_problem` 与
    # `_norm_rel` / `_rel_is_inside` 两个路径守卫）。是「既有单职责模块被写胖过线」，
    # 不是新落的模块 —— 但那一批的载体读写本来就只有这一处，拆开会让"哪一份稿在盘上、
    # 叫什么名"有两个实现。判据语义一个字没动：抬完仍然只许降、不许再涨。
    # 2026-11-08（不抬基线，改拆）：这一批确实把 `propositionkey.py` 推过 800（791 →
    # 823，概念定义项那一块），但业主口径是「不许抬基线」⇒ 处置是把它拆回 800 以下：
    # 「概念的定义项」那三样（`CONCEPT_GENERIC_TERMS` / 两个抽取正则 / `defined_term`）
    # 搬到 `conceptrows.py`（概念行的唯一读写口），`propositionkey` 只回引两个 public
    # 名字。搬完 823 → 786 行，这一格仍是 75。同一笔里函数那一格也是拆（95 不动）——
    # 逐条见下面那一格上方的点名。判据语义一个字没动：只许降、不许再涨。
    "src_files_gt800_lines": 75,
    # 2026-10-30：79 → 83。四格都能点名，全是"连续 3 次才发签"那一批新落的函数
    # （`eab9f85` 之后新过 200 行的，逐条按 `(文件, 函数名)` 比对过，没有一条是
    # 既有函数被写胖，也没有一条掉回线下）：
    #   · `src/agentflow/verifications.py::record_verification` 226 行 —— 这一支新增
    #     `flip=False`（V 只落台账、翻位交给秘书）与 `secretary_judge` / `washed_relay`
    #     两格条件写入，是"签这个事实"与"翻不翻位"分开的那段；
    #   · `src/agentflow/verifications.py::sign_statement` 202 行 —— 新增
    #     `append_ledger=False`、连续次数闸与 `streak` / `need` / `streak_ok` 三格读数；
    #   · `src/agentflow/conductor.py::wake_blocked` 269 行 —— 新落的工具面
    #     （`conductor.wake_blocked`）的落点；
    #   · `src/agentflow/agent_skills.py::_v_skills` 240 行 —— V 的技能表新增
    #     「产出-只产意见-签在秘书」那一行。
    # 判据本身的语义一个字没动：它仍然是"不许比基线更差"，抬完仍然只许降、不许再涨。
    # 2026-11-03：83 → 86。三格都能点名，全是"这一批的新能力落在既有函数里"把它们推过
    # 200 行（逐条按 (文件, 函数名) 比对过基线提交 3dc2f53a 与 HEAD；没有一条掉回线下，
    # 也没有一个新落的长函数）：
    #   · `src/agentflow/agent_loop.py::_final_gate_reading` 194 → 230 行 —— 71fc01c3
    #     （153-U-04）final 闸改 fail-closed：四条路径各说真原因 + 指路，兜底串与
    #     "已清空"那句假原因删掉；
    #   · `src/agentflow/closing.py::_check_load_bearing` 184 → 251 行 —— 25a805fb
    #     （154 第 1 笔）收工门核 V 对 E 报告的真签：第三方签检查抽成 exhaustion_backing
    #     （一处实现、两个调用者：B 的入库闸 / _has_t3 的穷举支路），四种结局各给理由；
    #   · `src/agentflow/numericproof.py::latest_third_party_sign` 161 → 212 行 —— 4e93a916
    #     （153-U-06 丙+乙）读数补"该谁签 / 靠它背书几条 / 那一签的分布"。
    # 与 2026-10-27 晚抬 78 → 79 的 `_park_gate` 同形（"又一个新能力落在既有函数里"）。
    # 另外有 11 个既有函数在长、但没有一个新过线（最大的 `agent_v/core.py::verify_proof`
    # 390 → 662 行：连判到门槛 + 两态结论 + "已签过的命题不再送审"三笔都落在那一个函数里）；
    # 这一格数的是"有多少个函数超过 200 行"，所以它们不改变这一格的读数
    # —— 若要把"既有函数被写胖"本身也算成变坏，那是先改判据的口径，不是抬基线。
    # 判据本身的语义一个字没动：它仍然是"不许比基线更差"，抬完仍然只许降、不许再涨。
    # 2026-11-01：86 → 87。一格，能点名：
    #   · `src/agentflow/errorstats.py::error_action_stats_from` 146 → 478 行 —— f06f0210
    #     那一笔（错误动作读数扩面：15 类新增 / 43 总）把 7 个新类目的取数与归属都落在
    #     这一个函数里（四个辅助源 → 事件流 / 会话记录 / 校验台账 / 名册拒绝 / 秘书判词 /
    #     收工门六段、逐类三态的 `class_state`、样本与时间跨度的装配）。
    # 它是「既有函数被写胖过线」，不是新落的长函数（同一笔里新加的 `_read_aux` /
    # `_read_jsonl_dir` / `by_class` 都没过 200）；`errorstats.py` 本身早就超过 800 行，
    # 所以文件那一格不动。判据语义一个字没动：抬完仍然只许降、不许再涨。
    # 2026-11-02：87 → 89。两格，都能点名，都是"这一批的新能力落在既有函数里"把它们
    # 推过 200 行（逐条按 (文件, 函数名) 比对基线提交 960ade2f^ 与 HEAD；没有一条掉回线下，
    # 也没有一个新落的长函数）：
    #   · `src/agentflow/secretary.py::decide_sign_issuance` 152 → 216 行 —— 960ade2f
    #     （「V 一次送审 = 三轮 · 跨送审不累计」）新增可选 `within_call` / `review_call`：
    #     给了趟内轮次就只看这一趟（台账只作 reading/ledger_streak 历史读数），
    #     不给则保持原台账兼容门 —— 两套门都落在同一个签发函数里；
    #   · `src/agentflow/verifications.py::review_standing` 195 → 206 行 —— 同一笔新增
    #     `legacy_rows`：没有 `review_call` / `review_pass` 的老行读得出、但不参与新签判断。
    # 判据语义一个字没动：抬完仍然只许降、不许再涨。
    # 2026-11-03：89 → 90。一格，能点名：`src/agentflow/agent_b/register_statement.py::
    # _attach_proofs` 198 → 222 行 —— 179 批（两阶段录入）把"机械录入那一版显式标
    # `optimized=false`、重交同一份不算『同种证明』"两段落在同一个挂证明的函数里。
    # 逐条按 (文件, 函数名) 比对改前那 6 个被改的 src 文件（register_statement /
    # closing / depsection / evidencebits / papermapping / secretary）：只有这一条
    # 跨过 200，没有一条掉回线下，也没有一个新落的长函数。文件那一格不动（它本来就
    # 超过 800 行）。
    # 2026-11-04：90 → 91。一格，能点名：`src/agentflow/secretary.py::_upgrade_evidence_kind`
    # 186 → 212 行 —— f3408ef6（甲：穷举程序 + V 签 ⇒ 落签那一刻直接 proof）把
    # 「已在终态」那一支（只读判据 `_signed_exhaustion_terminal`，与回填 / 审计同一份）
    # 落在既有的升档梯子里，于是这个函数跨过 200。逐条按 (文件, 函数名) 比对基线提交
    # 192ec411 与 HEAD：只有这一条新过线，没有一条掉回线下，也没有一个新落的长函数
    # （同一批新增的 `_signed_exhaustion_terminal` 只有几十行）。文件那一格不动
    # （secretary.py 本来就超过 800 行），`dup_docstring_segments` 也不动。
    # 判据语义一个字没动：抬完仍然只许降、不许再涨。
    # 2026-11-04 再抬 91 → 94。三格，都能点名（逐条按 (文件, 函数名) 比对基线提交
    # f3408ef6 与 HEAD；没有一条掉回线下）：
    #   · `src/agentflow/agent_skills.py::_e_skills` 218 行 —— p234 的 E 手册
    #     （穷举证明-拿签与上报收养）落在这一份技能表里；
    #   · `src/agentflow/agent_skills.py::_g_skills` 243 行 —— G 的对应表格子与凭据格
    #     口径（doc.mapping_cells / 6fb014f5）落在这一份技能表里；
    #   · `src/agentflow/papermapping.py::mapping_cells` 354 行 —— 838a7d87 新落的只读
    #     读数口（对应表那一行该填的格；doc.mapping_cells 的实现）。
    # 判据语义一个字没动：抬完仍然只许降、不许再涨。
    # 2026-11-04 再抬 94 → 95。一格，能点名（逐条按 (文件, 函数名) 比对基线提交
    # 2bd8efc4 与 HEAD；只有这一条新过线，没有一条掉回线下，也没有既有函数新过线）：
    #   · `src/agentflow/agent_v/core.py::_review_unregistered_prose` 0 → 224 行 ——
    #     新落的函数（基线提交里没有它）：业主裁定 甲之后，"未在册的一份散文证明"
    #     走的就是它 —— 三转判完把签块盖回稿（`vsigns.issue` + 收方秘书
    #     `land_unregistered_sign`），并分辨 `reviews_unsigned` / 负判落 pending /
    #     路径不合约定三类终局。它是「新落的长函数」，不是把既有函数写胖。
    # 判据语义一个字没动：抬完仍然只许降、不许再涨。
    # 2026-11-08（不抬基线，改拆）：这一批把五条函数推过 200 行（其中
    # `_register_statement_impl` 与掉回线下的 `register_statement` 是同一笔拆分的两半，
    # 净额 0）。业主口径「不许抬基线，拆函数」⇒ 处置是把越过线的那四条各拆一块出来：
    #   · `agent_b/register_statement.py::_attach_proofs._transition` 296 → 159 —— 把
    #     「换正文」那一段（核签 / 换 / 认优化标记 / 判旧签不算数）搬成
    #     `_RegisterStatement._apply_canonical_proof`；
    #   · `closing.py::statements_unsigned_reading` 213 → 103 —— 把逐条判档那个循环搬成
    #     模块级 `_unsigned_rows_reading`；
    #   · `secretary.py::adjudicate_proposition` 284 → 198 —— 把 `out` 初值与「取候选」
    #     两块搬成 `_identity_out` / `_identity_candidates`；
    #   · `secretary.py::record_statement` 201 → 180 —— 把「交给事务写口 / 写不成怎么读」
    #     那一段搬成 `_land_or_refuse`。
    # 四块都是整段搬移（缩进不变、块内逐字相同），返回值 sha256 前后相同（12 组，见
    # `temp/_equiv_probe.py`）。拆完这一格仍是 95。判据语义一个字没动：只许降、不许再涨。
    "src_functions_gt200_lines": 95,
    "dup_docstring_segments": 5,
}

#: 基线观测时刻（写在这里，是为了让"这组常量有多旧"这件事一眼可见）。
#: 2026-10-27 抬第二格 77 → 78，来源点名：`src/agentflow/stopctl.py::stop_programs`
#: （206 行，G2「注销前检测 + 停机两档杀程序」那批新落的函数，HEAD 里没有）。
#: 抬它的理由与 2026-10-24/26 那批同形：这一格长的是一条真实的新能力，而不是把
#: 既有函数写胖；判据语义仍未变（只许降、不许再涨），下一次再涨要另写一条理由。
#: 2026-10-27 晚再抬 78 → 79，来源点名：`src/agentflow/agent_loop.py::_park_gate`（现 209 行）。
#: 它是"轮查到点那一支 + 挂机片长接 `clock.next_due`"这批的挂点（业主口径：轮查是规范动作），
#: 也就是又一个新能力落在既有函数里 —— 与上一条同形。判据语义仍未变：只许降、不许再涨。
#: 2026-10-30 再抬 79 → 83，四个来源见 `BASELINE` 里那一格上方的逐条点名
#: （`record_verification` / `sign_statement` / `wake_blocked` / `_v_skills`）。
#: 2026-11-03 再抬 83 → 86，三个来源见 `BASELINE` 里那一格上方的逐条点名
#: （`_final_gate_reading` / `_check_load_bearing` / `latest_third_party_sign`；
#: 三条都是"新能力落在既有函数里"，与 78 → 79 的 `_park_gate` 同形）。
#: 2026-11-01 再抬两格：文件 72 → 73（`webui/state.py` 785 → 857，跨线于 1328e94b）
#: 与函数 86 → 87（`errorstats.py::error_action_stats_from` 146 → 478，跨线于 f06f0210），
#: 两条都是"既有东西被写胖过线"，来源见 `BASELINE` 里那两格上方的逐条点名。
#: 2026-11-02 再抬函数 87 → 89，两个来源见 `BASELINE` 里那一格上方的逐条点名
#: （`secretary.py::decide_sign_issuance` 152 → 216、`verifications.py::review_standing`
#: 195 → 206，两格都跨线于 960ade2f）；文件那一格不动。
#: 2026-11-04 再抬函数 90 → 91，来源见 `BASELINE` 里那一格上方的逐条点名
#: （`secretary.py::_upgrade_evidence_kind` 186 → 212，跨线于 f3408ef6）。
#: 2026-11-04 收口再抬两格：文件 73 → 74（`agent_d/write_report.py` 新过 800）与
#: 函数 91 → 94（`agent_skills.py::_e_skills` / `_g_skills` / `papermapping.py::mapping_cells`），
#: 来源逐条见 `BASELINE` 里那两格上方的点名；判据语义仍未变（只许降、不许再涨）。
#: 2026-11-04 载体迁移再抬两格：文件 74 → 75（`agent_f/manuscript.py` 620 → 890）与
#: 函数 94 → 95（`agent_v/core.py::_review_unregistered_prose` 0 → 224），来源逐条见
#: `BASELINE` 里那两格上方的点名；判据语义仍未变（只许降、不许再涨）。
#: 2026-11-08：这一批没有抬基线（业主口径：拆函数 / 拆模块，不抬基线）。文件那一格
#: 仍是 75（`propositionkey.py` 823 → 786：概念定义项那一块搬进 `conceptrows.py`），
#: 函数那一格仍是 95（四条越过 200 的函数各拆一块出来，见 `BASELINE` 里那一格上方的
#: 逐条点名）。`BASELINE_OBSERVED` 因此仍是 2026-11-04 —— 这两个数是那一天的读数，
#: 今天再量还是它。
BASELINE_OBSERVED = "2026-11-04"


def _load_survey():
    """按文件路径加载被判的脚本（不依赖 `tools/` 是不是一个包）。"""
    spec = importlib.util.spec_from_file_location("agentflow_tools_repo_survey", SURVEY_PATH)
    assert spec and spec.loader, f"加载不了 {SURVEY_PATH} —— 判据失去对象（不是通过）"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _metrics(data: dict) -> dict[str, int]:
    """把 `survey()` 的读数抽成与 `BASELINE` 同名的三格。"""
    return {
        "src_files_gt800_lines": data["big_files"]["gt800"],
        "src_functions_gt200_lines": data["long_defs"]["function_gt200"],
        "dup_docstring_segments": data["dup_docstring_segments"],
    }


def baseline_problems(data: dict, baseline: dict[str, int] | None = None) -> list[str]:
    """读数 vs 基线 ⇒ 问题清单（空 = 成立）。返回清单而不是布尔，红时要能说清差在哪。

    第一条判据是"扫到了没有"：扫描面为空（或根写错）时，`survey()` 给的是
    `scanned_ok=False`，这里必须报"没查成"而不是让"0 ≤ 60"通过。
    """
    base = dict(BASELINE if baseline is None else baseline)
    if not data.get("scanned_ok"):
        return [
            "没扫到 = 没查成："
            + str(data.get("vacuum_reason") or "扫描面返回 scanned_ok=False（没有原因，这本身是缺陷）")
            + " —— 这一份读数不可用，它不构成'体量没变坏'的证据"
        ]
    got = _metrics(data)
    problems: list[str] = []
    for key, limit in base.items():
        now = got.get(key)
        if now is None:
            problems.append(f"读数里缺 `{key}` —— 判据失去对象（不是通过）")
        elif now > limit:
            problems.append(f"`{key}` 已越过基线：现在 {now}，基线 {limit}"
                            f"（基线观测于 {BASELINE_OBSERVED}；要抬基线请先说明为什么这次长大是有意的）")
    return problems


def test_survey_reports_numbers_and_stays_within_baseline():
    """正向：真的跑一遍巡检，三格读数都要读得出来、且都不许越过基线。

    "读得出来"不是形式主义：`scanned_ok=True` 之后三格如果全是 0，那更像扫描器没接上
    而不是这棵树空了 —— 所以这里额外断言三格都大于 0（反真空）。今天它们分别是
    73 / 89 / 5。
    """
    mod = _load_survey()
    data = mod.survey(REPO)
    assert data.get("scanned_ok"), data.get("vacuum_reason")
    assert data["scanned"]["src_files"] > 0, "src 下 0 个 .py —— 这不是'体量很干净'，是没扫到"
    got = _metrics(data)
    zero = [k for k, v in got.items() if v <= 0]
    assert not zero, f"这几格读成了 0，扫描器可能没接上（不是'没问题'）：{zero}；读数={got}"
    problems = baseline_problems(data)
    assert not problems, problems


def test_empty_scan_surface_is_not_green(tmp_path):
    """负控（反真空）：把扫描面打桩成空目录 ⇒ 判据必须红，且理由要写"没查成"。

    打桩的是扫描面（`src_rel` 指向一个空目录），不是把 `survey()` 换掉 ——
    换掉实现证明不了"判据会在真实现上红"，而这条负控要证的正是那个方向。
    """
    mod = _load_survey()
    empty = tmp_path / "not_a_source_tree"
    empty.mkdir()
    data = mod.survey(tmp_path, src_rel=empty.name, tests_rel="tests")
    assert data.get("scanned_ok") is False, "空扫描面被读成了'扫到了'（这一条必须红）"
    problems = baseline_problems(data)
    assert problems, "空扫描面下判据给了'没问题' —— 反真空失效"
    assert "没查成" in problems[0], f"红是红了，但没写清'没扫到 = 没查成'：{problems}"
    assert "0 ≤ 60" not in problems[0], "不许把空扫描面读成'0 个大文件、比基线还好'"


def test_the_script_exits_2_when_it_cannot_measure(tmp_path):
    """负控（三态）：脚本自己的退出码也要分得开 —— 0 = 量到了，2 = 没量成。"""
    mod = _load_survey()
    empty = tmp_path / "no_source_here"
    empty.mkdir()
    code = mod.main(["--root", str(tmp_path), "--src", empty.name, "--json"])
    assert code == 2, "扫描面为空时脚本必须以 2 退出（0 会把它读成'查过了、没问题'）"


def test_baseline_criterion_has_teeth():
    """负控：把某格读数抬到基线之上 ⇒ `baseline_problems` 必须报出来。

    这条防的是"比较写反了"（例如把 `>` 写成 `>=` 或把两边对调）：
    那时代码照样跑、照样绿，而它已经从判据退化成了装饰。
    """
    mod = _load_survey()
    data = mod.survey(REPO)
    assert data.get("scanned_ok"), data.get("vacuum_reason")

    def _with(src_files_gt800: int, functions_gt200: int, dups: int) -> dict:
        """把三格读数换成给定值（其余读数原样带着），用于测比较本身。"""
        return {
            **data,
            "big_files": {**data["big_files"], "gt800": src_files_gt800},
            "long_defs": {**data["long_defs"], "function_gt200": functions_gt200},
            "dup_docstring_segments": dups,
        }

    over = _with(BASELINE["src_files_gt800_lines"] + 1,
                 BASELINE["src_functions_gt200_lines"],
                 BASELINE["dup_docstring_segments"])
    assert baseline_problems(over), "越过基线却没报 —— 这条判据没有牙"
    # 另一侧：三格恰好等于基线时必须成立（基线是"不许更差"，不是"不许一样"）。
    equal = _with(BASELINE["src_files_gt800_lines"],
                  BASELINE["src_functions_gt200_lines"],
                  BASELINE["dup_docstring_segments"])
    assert not baseline_problems(equal), "读数恰好等于基线就被判红 —— 基线的语义写错了"


def test_json_flag_prints_parseable_readings():
    """正向（可复跑）：`--json` 那一档真的能被打成 JSON 并读回同样的三格。

    为什么值得一条：`--json` 是这条巡检被别处引用的唯一形态（人读版会随措辞变），
    它坏掉时没有任何别的东西会红。
    """
    p = subprocess.run(
        [sys.executable, str(SURVEY_PATH), "--root", str(REPO), "--json"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert data.get("scanned_ok"), data.get("vacuum_reason")
    assert not baseline_problems(data), baseline_problems(data)

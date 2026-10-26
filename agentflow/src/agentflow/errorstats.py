# -*- coding: utf-8 -*-
"""按角色统计「错误动作计数」的只读测试工具。

## 这个量回答什么

业主口径（逐字）：「做一个统计量作为测试工具：对每种角色，统计"错误动作计数"
（注意是按照每种角色来记），包括所有被各种判据拦下或被秘书拦下的行为，细分多类计数。」

它只读盘上已有的记录（事件流 / 会话记录），一份都不写：不建表、不改行、不追加事件、
不落报告文件。人看 `python -m agentflow stats errors --root <工作区>`，
程序看 `error_action_stats(target).as_dict()`。

## 三个口径（不写下来，这个数就没有可比性）

1. 谁是"错的那一方"（角色归属）。事件流里一条 `tasks` 行的 `role` 是"被召唤的角色"、
   `called_by` 是"发起这次召唤的角色"。越权/禁边是发起方把这条边派错了，算发起方的错；
   而"这条边被拒"这件事记在被召唤的那一行上。真机现场（`projects/r34d`，`t-000019`）：
   `role=B`、`called_by=G`，拒信逐字是 "G → B 不在策略允许的边里"。所以归属按码分流：
   - `CALLER_ATTRIBUTED_CODES`（召唤期结构判据，产出见 `policy.check`）⇒ 记 `called_by`；
   - 其余（写入期判据 / 判据层 / 角色自己的回执）⇒ 记 `role`；
   - 会话记录 `agent_step` / `llm_call` ⇒ 记记录里的 `role`；
   - 代唤请示（`agent_message` 的 `请代唤`）⇒ 记记录里的 `from`。
   为什么必须显式写：若一律把 `role` 当 actor，"G 派 B 被拒"这件事就记到 B 头上 ——
   而"一方的错不算到另一方头上"正是判据 `tests/test_error_action_stats.py` 钉的第一条。

2. 一条记录只算一次（主码规则）。同一条记录里常常命中好几个码（工具结果既有
   `参数错误：` 又有 `缺少必填参数`；一条被拒的召唤行 detail 里可能同时出现
   `forbidden_edge` 与写入期判据的原话）。取值规则只有一条：类目表里靠前的类目优先，
   同类目里字数长的码优先（同长按 `CODE_TABLE` 的顺序）。于是判据是确定的：
   一条记录只给它的角色增加 1，且只加在一个类目上。
   为什么不是纯按字数：`refusal_reason=invalid_params`（粗：这次调用不成立）与 detail 里的
   `行校验失败`（细：写库那一刻被 schema 拦住）会同时命中，纯按字数会永远让粗码赢，
   写入期判据那一类就收不到数。为什么同类目里要看字数：`judge_not_wired` 含 `not_wired`，
   取长的那个才记得准（两者本来同类目，只影响 `sources.hits` 里记下的码名）。

3. 三态。`checked=True` 才谈得上"几个"；读不到就是 `unknown`，不折成 0：
   - 工作区不存在 / `data/events.jsonl` 不存在或读不明白 ⇒ `checked=False`；
   - `sessions/` 存在但一个文件都读不明白 ⇒ `checked=False`；
   - `sessions/` 根本不存在 ⇒ 这是"这个工作区没有会话记录"的正常形态，按 0 读
     （`checked=True`，与 `statusreport._rows` 把"读不到"和"是 0 行"分开同一个理由）。
   "空工作区 ⇒ 全 0 且 checked=True"是正控：0 不是 unknown。

## 数据源（三处，都是盘上已有的记录）

- `data/events.jsonl`：`tasks` 表的事件，取每个 `task_id` 的最后一行（后写覆盖先写，
  与 `Store.rebuild` 的重放口径一致）。拒绝落在 `outcome=refused` + `refusal_reason` 上。
- `sessions/*.jsonl`：
  - `llm_call` 的 `problem`（判据层的 `judge_bad_json` / `judge_bad_args` /
    `judge_no_reply:*` / `judge_failed:*`）；
  - `agent_step` 的 `result.error` 与 `result.warn`（工具层与收工门的拒信原话）；
    多调用那一族不从这里数（理由见下面"拆分是能力"那一段）；
  - `agent_step_call` 的逐条记录（`stepdispatch` 拆分出来的每一条调用一条）：执行了的
    进过程读数 `multi_call_executed_calls`，没执行的按它自己的结局原话进三个真失败类目；
  - `agent_message` 的 `subject`（`请代唤` = 越权被拒之后的转投）。
  刻意不读 `payload`：那是模型自己写的原话，"提到一个码"不等于"撞上那个码"。
  也刻意不读 `runs/*.json`：它与 `agent_step` 是同一批步的两份落盘，两份都读会把同一步
  算两次（真机核查：`runs/B-*.json` 与 `sessions/*.jsonl` 的 `agent_step` 逐条对应）。

## 拆分是能力，不是错（D-65，业主逐字「修，且不再认为 multi_call 有问题」）

一步给多条调用是正常能力：`stepdispatch` 把它整包接住、按原顺序拆成条目、逐条执行与记账。
所以"这一步被拆开逐条执行了"这件事不是错误动作，它是"系统在按设计工作"的证据 ——
把它算进错误总数，等于把正常行为记成错误（真机 `projects/sylow3`：38 个这种步 + 84 条拆出来的
调用，一度贡献了错误总数的八成）。

因此类目分成两张表，`by_role` / `role_total` / `total` 只数错误那一张：

- `ERROR_CATEGORIES`（错误，计入 `total`）：多调用这一族只留三档真失败——
  `multi_call_discarded`（拆的时候这一条解码不出来 ⇒ 丢了，少做一条）/
  `multi_call_unexecuted`（拆出来了、这一趟没执行成）/ `multi_call_out_of_limit`
  （超上限：这一趟还剩的步数/花销不够，那几条没执行）。三档全 0 才是绿。
- `PROCESS_CATEGORIES`（过程读数，单独一栏、不计错）：`steps_split`（被拆分的步数）与
  `multi_call_executed_calls`（拆出来并真的执行了的调用条数），外加
  `direct_write_routed`（直写请求被系统转交正路并办成的条数，2026-10-26 加）。

## 路由成功也是过程读数，不是错误（2026-10-26）

直写兜底那一档（`routed_to_backstop`）此前把三件不同的事混在一个类目里：路由办成了 /
兜底方拒了 / 兜底方不可达。前一件是"系统按设计接管"，后两件才是"这一笔没落成" ——
混在一起的后果是"系统替模型办成了"照样进错误总数（与 multi_call 当初的形态一模一样）。
所以按同一手法拆开：办成的进过程读数 `direct_write_routed`，拒的 / 不可达的留在错误表
（类目名仍是 `routed_to_backstop`，含义收窄成"兜底方没接住"）。
判据 `tests/test_routed_success_is_a_process_reading.py` 钉住"成功的一条只进过程读数、
被拒的才进 total"，并带一条反真空（把路由表清空 ⇒ 同一笔读成 `direct_write`）。

两处读数各有唯一来源，都不读"步的那段文字"：`steps_split` 取 `result` 里的结构字段
`multi_call`（取 `call_index == 0` 的那一条 ⇒ 一步正好一次），逐条结局取 `agent_step_call`
记录。为什么不扫 `warn` 里那句"这一步给了 N 条调用，已按顺序逐条"：
1. 那句话只挂在回合最后一条上，而最后一条解码不出时 `agent_loop._record_undecodable_item`
   根本不挂汇总 ⇒ 按文案数会漏掉那些步；
2. 那句话与"最后一条被拒"的错误原话同处一段文字，主码规则会让错误赢 ⇒ "被拆分的步数"少记；
3. 汇总本身是拿每一条的 `line` 拼出来的（`stepdispatch.StepDispatch.summary`），
   于是"因预算未执行"这类逐条结局原话又出现在步的 `warn` 里 —— 按文案再数一遍就是同一件事数两次。

判据 `tests/test_multi_call_is_a_capability_not_an_error.py` 把上面每一条都钉住
（含"改前红"与"把拆分打桩成没拆分 ⇒ 必红"的反真空）。

## 码 → 类目这张表从哪来

`CODE_TABLE` 每行是（码, 类目, 出处）。出处逐条去代码里 grep 过，写的是定义或产出那一
行的 `file:line`。判据 `tests/test_error_action_stats.py` 会扫源码断言表里每个码真的出现
在 `src/agentflow/` 的某个文件里（扫的时候排除本文件，否则这张表会自己证明自己）。
类目本身逐类写过一行含义（`ERROR_CATEGORIES`）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import schema as S

#: 没有记下角色时用的名字。空串不许静默并进某个角色（那会把一个未知算到已知头上）。
UNKNOWN_ROLE = "（未记角色）"

#: 类目表（顺序即优先级：主码同长时按它取）。每类一行含义，逐类来自仓库里真实存在的拒绝形态。
#:
#: 这一张表就是"错误动作"的全部类目：只有这张表里的类目会进 `by_role` / `role_total` /
#: `total`。多调用那一族（拆分）不在这里 —— 拆分是正常能力，它的读数在
#: `PROCESS_CATEGORIES` 里；它真正的三档失败才是下面那三行（口径见模块 docstring
#: "拆分是能力，不是错"）。
ERROR_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("forbidden_edge",
     "越权/禁边：这条召唤边不在 ALLOWED_EDGES 里（含 Lean 关着时的隐藏角色、不可召唤的主控）"),
    ("not_in_roster",
     "名册外的对象：按角色名发给一个不在自己名册里的人（只有父与子能通话）"),
    ("unknown_tool",
     "名字不存在：工具面没有这件工具 / 该角色没有这个动作 / 角色名不存在"),
    ("routed_to_backstop",
     "直写兜底没接住：通用写口把请求转交正路，而兜底方拒了（*_refused）或不可达"
     "（*_unavailable）—— 都没落成。转交并办成的那些不在这里，它们是过程读数 "
     "`direct_write_routed`（2026-10-26 拆开：办成 ≠ 出错）"),
    ("direct_write",
     "写库野路：绕开正路直写 statements / dependencies / lit_candidates（通用写口被拒）"),
    ("readonly_role_write",
     "只读角色拿写工具：调用期角色判据拒绝这次调用（权限面，不是参数问题）"),
    ("not_wired",
     "没接线：该角色的该动作尚未接线（框架欠的东西，不是模型做错的事）"),
    ("capacity_refused",
     "配额/时限拒绝：深度、扇出、并发、预算、墙钟截止、同链重复（policy 的六条容量判据）"),
    ("schema_invalid",
     "写入期 schema 校验失败：行不满足表契约（行校验失败，写库那一刻被拒）"),
    ("param_invalid",
     "参数不合法：必填缺失 / 类型或枚举不对（工具层参数门；必填缺失是其中最常见的一档）"),
    ("duplicate_conflict",
     "重复/幂等冲突：同一件东西已经在库或已登记过（duplicate_* 一族）"),
    ("controlled_refusal",
     "受控拒绝：秘书与各动作以受控理由码拒收（refused 那一档，理由可枚举、可统计）"),
    ("judge_bad_json",
     "判据层：模型回的不是合法 JSON（坏形状，不是坏参数）"),
    ("judge_bad_args",
     "判据层：模型给的参数写坏了（与坏 JSON 分开计，纠正话术不同）"),
    ("judge_no_reply",
     "判据层：没拿到可用的回复（超时 / 输出预算被思考吃光 / judge_no_reply:<kind>）"),
    ("judge_failed",
     "判据层：判据本身失败（judge_failed:<kind>，如网络断；不是模型的错，但要看得见）"),
    ("multi_call_discarded",
     "拆分丢弃：一步给的多条调用里、这一条在拆的时候就解码不出来 ⇒ 它被丢掉，"
     "真的少做了一条（这是失败；步被拆开不是失败）"),
    ("multi_call_unexecuted",
     "拆分未执行：拆出来的这一条这一趟没执行成（本回合已收工）⇒ 真的少做了一条"
     "（这是失败；步被拆开不是失败）"),
    ("multi_call_out_of_limit",
     "拆分超上限：拆出来的条目超过了这一趟还剩的步数/花销上限（stepdispatch 的 budget "
     "那一档）⇒ 那几条没执行（这是失败；步被拆开不是失败）"),
    ("unreadable",
     "读不明白：台账/回执/上下文图读不出来或解析失败（不许读成 0 的那一档）"),
    ("closing_blocked",
     "收工门拦下：mapping_not_written / run_evidence_unbacked / quote_verified_without_span"),
    ("paper_mapping_gap",
     "论文对应表的逐行缺口（mapping_* 一族：孤立行、引文定位缺、文件缺、程序缺…）"),
    ("relay_after_refusal",
     "流程层：被禁边拒掉之后发起的代唤请示（转投，不是重试同一条边）"),
)

#: 过程读数类目：这些数说的是"系统在做什么"，不是"哪里做错了"，所以不进
#: `total` / `role_total` / `by_role`（业主 D-65：「修，且不再认为 multi_call 有问题」）。
#: 呈现时它们单独一栏、用中性/正向的说法（`render_text` 的"拆分读数"那一段）。
PROCESS_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("steps_split",
     "被拆分的步数：模型一步给了 2 条及以上调用、被接住层接住并拆开逐条执行"
     "（过程读数，不计错；判据读 `result.multi_call.call_index == 0` 的那一条）"),
    ("multi_call_executed_calls",
     "拆分执行：多调用步里拆出来的、真的执行了的调用条数（过程读数，不计错；"
     "判据读 `agent_step_call` 的逐条记录）"),
    ("direct_write_routed",
     "直写被转交正路并办成：通用写口碰到'只能经正路写'的表时，系统把这一笔交给兜底方，"
     "兜底方按它自己的判据跑完、行真的落了盘（过程读数，不计错；判据读结局码 "
     "routed_to_backstop.<兜底方>，拒的 / 不可达的在错误表里那一档）"),
)

#: 全部类目（错误 ＋ 过程读数）。`primary_code` 的优先级按这一张表的顺序取：错误类目全排在
#: 前面 —— 于是"同一段文字既像过程读数又像错误"时算错误那一档（宁严不宽）。
ALL_CATEGORIES: tuple[tuple[str, str], ...] = ERROR_CATEGORIES + PROCESS_CATEGORIES

#: 哪些类目算错误（计入 `total` / `role_total`）。分桶只认这一张表，不认调用点。
ERROR_CATEGORY_NAMES: frozenset[str] = frozenset(cat for cat, _why in ERROR_CATEGORIES)

#: 哪些类目是过程读数（不计错，单独一栏）。
PROCESS_CATEGORY_NAMES: frozenset[str] = frozenset(cat for cat, _why in PROCESS_CATEGORIES)

#: 多调用这一族的类目：它们的读数只从结构化字段与逐条记录取，不扫"步的那段文字"。
#: 为什么必须显式排除文案：`stepdispatch.StepDispatch.summary` 是拿每一条的 `line` 拼出来的，
#: 于是那句汇总里就带着逐条结局的原话（"因预算未执行"之类） —— 按汇总再数一遍就是同一件事
#: 数两次。判据 `tests/test_multi_call_is_a_capability_not_an_error.py` 的 b 把两处一起钉住。
MULTI_CALL_CATEGORIES: frozenset[str] = frozenset({
    "steps_split", "multi_call_executed_calls",
    "multi_call_discarded", "multi_call_unexecuted", "multi_call_out_of_limit",
})

#: 召唤期结构判据：这些码说的是"发起方把这次召唤派错了"，所以记 called_by 而不是被召唤的
#: 那个角色。成员口径 = `policy.check` 在派出之前就下结论的那六条 + 角色/动作存在性
#: （`policy.check_action`）与非召唤目标。`not_wired` 不在其中：那是被召唤角色自己的动作缺口。
CALLER_ATTRIBUTED_CODES: frozenset[str] = frozenset({
    "forbidden_edge", "unknown_role", "unknown_action", "not_in_roster",
    "depth_exceeded", "fanout_exceeded", "concurrency_exceeded",
    "budget_exceeded", "deadline_exceeded", "cycle_detected",
})

#: 码 → 类目 → 出处（file:line）。出处是"这个码在哪定义 / 在哪产出"，逐条 grep 出来的。
CODE_TABLE: tuple[tuple[str, str, str], ...] = (
    # ---- 结构性拒绝
    ("forbidden_edge", "forbidden_edge",
     "src/agentflow/schema.py:2497（词表）/ src/agentflow/policy.py:408,421,430,455（产出）"),
    ("not_in_roster", "not_in_roster",
     "src/agentflow/agent_loop.py:2754（roster_probe 的受控拒绝码）"),
    ("不在你的名册里", "not_in_roster",
     "src/agentflow/agent_loop.py:2755（roster_probe 的拒信原文）"),
    ("unknown_tool", "unknown_tool", "src/agentflow/tools/base.py:1132（kind）"),
    ("没有名为", "unknown_tool", "src/agentflow/tools/base.py:802（ToolError 原文）"),
    ("unknown_action", "unknown_tool",
     "src/agentflow/schema.py:2496（词表）/ src/agentflow/policy.py:306,313（产出）"),
    ("unknown_role", "unknown_tool",
     "src/agentflow/schema.py:2495（词表）/ src/agentflow/policy.py:302,433（产出）"),
    ("direct_write_refused", "direct_write", "src/agentflow/store.py:248（DIRECT_WRITE_REFUSED）"),
    # ---- 直写兜底（业主 2026-10-24：「不应该是提醒智能体要走秘书，而是自动将直写请求
    # 路由到秘书接管」）。路由不再计入 `direct_write`：那一档只留"兜底方也接不住"的野路。
    # 结局码逐条登记在 `ROUTED_CODES`（字面量），拼装只允许拼出那张表里的东西。
    # 2026-10-26 拆开（与 multi_call 同一手法）：办成的两档进过程读数 `direct_write_routed`
    # —— "系统替模型办成了"不是错误动作；只有拒的 / 不可达的留在错误表上。
    ("routed_to_backstop.secretary", "direct_write_routed",
     "src/agentflow/tools/table_tools.py:558（ROUTED_CODES；产出见 :584 `_route_code`）"),
    ("routed_to_backstop.literal", "direct_write_routed",
     "src/agentflow/tools/table_tools.py:558（ROUTED_CODES；产出见 :584 `_route_code`）"),
    ("routed_to_backstop.secretary_refused", "routed_to_backstop",
     "src/agentflow/tools/table_tools.py:558（ROUTED_CODES；兜底方拒，原话见 refused_by_backstop）"),
    ("routed_to_backstop.literal_refused", "routed_to_backstop",
     "src/agentflow/tools/table_tools.py:558（ROUTED_CODES；兜底方拒，原话见 refused_by_backstop）"),
    ("routed_to_backstop.secretary_unavailable", "routed_to_backstop",
     "src/agentflow/tools/table_tools.py:558（ROUTED_CODES；兜底方不可达 ⇒ unknown，不折成成功）"),
    ("routed_to_backstop.literal_unavailable", "routed_to_backstop",
     "src/agentflow/tools/table_tools.py:558（ROUTED_CODES；同上）"),
    ("role_denied", "readonly_role_write",
     "src/agentflow/tools/base.py:1173,1178（call 的调用期角色判据）"),
    ("not_wired", "not_wired",
     "src/agentflow/schema.py:2505（词表）/ src/agentflow/conductor.py:3185（产出）"),
    ("depth_exceeded", "capacity_refused", "src/agentflow/schema.py:2499 / src/agentflow/policy.py:463"),
    ("fanout_exceeded", "capacity_refused", "src/agentflow/schema.py:2500 / src/agentflow/policy.py:502"),
    ("concurrency_exceeded", "capacity_refused",
     "src/agentflow/schema.py:2501 / src/agentflow/policy.py:513"),
    ("budget_exceeded", "capacity_refused",
     "src/agentflow/schema.py:2502 / src/agentflow/policy.py:521,537,540"),
    ("deadline_exceeded", "capacity_refused",
     "src/agentflow/schema.py:2503 / src/agentflow/policy.py:548"),
    ("cycle_detected", "capacity_refused", "src/agentflow/schema.py:2504 / src/agentflow/policy.py:474"),
    # ---- 写入期判据
    ("行校验失败", "schema_invalid", "src/agentflow/tools/table_tools.py:116,120（ToolError 原文）"),
    ("缺少必填参数", "param_invalid", "src/agentflow/tools/base.py:395（ParamError 原文）"),
    ("参数错误：", "param_invalid", "src/agentflow/tools/base.py:1214（ToolResult.fail 原文）"),
    ("param_error", "param_invalid", "src/agentflow/tools/base.py:1187,1233（kind）"),
    # 2026-10-28（`draft/156` 的 D4）：模型按前缀直觉手填了本该由台账分配的主键
    # （`rel-000001` / `stmt-1` / `p-000001`）。归 `param_invalid`：这次调用不成立的原因是
    # "多给了一格本不该给的参数"，不是行内容不合法。单独成码是为了让"同一个坑连踩几次"
    # 在读数上数得出来 —— 折进 `param_error` 就数不出来了。
    ("hand_filled_id", "param_invalid",
     "src/agentflow/tools/table_tools.py:359（kind；判据 `_hand_typed_id_refusal`）"),
    ("missing_source", "param_invalid", "src/agentflow/agent_b/register_statement.py:821"),
    ("missing_own_source", "param_invalid", "src/agentflow/agent_b/register_statement.py:870"),
    ("missing_quote_reason", "param_invalid", "src/agentflow/agent_b/register_statement.py:830"),
    ("missing_page_range", "param_invalid", "src/agentflow/agent_b/register_statement.py:845,860"),
    ("duplicate_doi", "duplicate_conflict",
     "src/agentflow/schema.py:128,144（词表）/ src/agentflow/litstage.py:637（产出）"),
    ("duplicate_statement", "duplicate_conflict", "src/agentflow/agent_b/register_statement.py:1181"),
    ("duplicate_paper_number", "duplicate_conflict", "src/agentflow/paperledger.py:205"),
    ("duplicate_claim_id", "duplicate_conflict", "src/agentflow/claimanatomy.py:1717,1728"),
    ("duplicate_id", "duplicate_conflict", "src/agentflow/verify.py:219"),
    ("invalid_params", "controlled_refusal", "src/agentflow/schema.py:2498（词表）/ src/agentflow/refusals.py:38"),
    # ---- 空正文的两档（业主 2026-10-24 裁定 B2 的第 1 条）：写侧与判档位那一侧共用一个字面量
    # （真身在 `refusals.py`）。`bad_statement` 是它们的前身：改前"0 字"与"只有短版"混在
    # 那一个码里，于是同一种输入在写侧与判档位侧拿到两个名字。
    ("empty_statement_text", "controlled_refusal",
     "src/agentflow/refusals.py:52（真身）/ src/agentflow/agent_b/register_statement.py:829（写侧产出）"
     " / src/agentflow/secretary.py:1706（判档位那一侧的受控拒绝）"),
    ("empty_proof_text", "controlled_refusal",
     "src/agentflow/refusals.py:53（真身）/ src/agentflow/agent_b/register_statement.py:190,548（两个写入口）"),
    ("bad_statement", "controlled_refusal", "src/agentflow/agent_b/register_statement.py:704"),
    ("bad_origin", "controlled_refusal", "src/agentflow/agent_b/register_statement.py:710"),
    ("bad_evidence_kind", "controlled_refusal", "src/agentflow/agent_b/register_statement.py:762"),
    ("bad_id", "controlled_refusal", "src/agentflow/agent_b/register_statement.py:929"),
    ("bad_line_range", "controlled_refusal", "src/agentflow/agent_b/register_statement.py:759"),
    ("bad_page_range", "controlled_refusal", "src/agentflow/agent_b/register_statement.py:756"),
    ("proofs_not_attached", "controlled_refusal",
     "src/agentflow/agent_b/register_statement.py:1176,1208"),
    ("proof_needs_third_party_signature", "controlled_refusal",
     "src/agentflow/agent_b/register_statement.py:798"),
    ("canonical_not_written", "controlled_refusal", "src/agentflow/agent_b/register_statement.py:1130"),
    ("secretary_unavailable", "controlled_refusal", "src/agentflow/agent_b/register_statement.py:1052"),
    # ---- 判据层
    ("judge_bad_json", "judge_bad_json", "src/agentflow/judge.py:67,206,208（problem 码）"),
    # 2026-10-26：原生工具调用面里"点了一个没广告过的函数名"此前折成 `judge_bad_json`
    # （`llmseam.ToolFace.to_shape`），而文本协议下同一个动作记的是 `unknown_tool` ——
    # 同一件事两个类目，于是"名字不存在"这一类在两种协议下各数一半。现在它归到一个类目
    # （`unknown_tool`：名字不存在），码保留判据层自己的名字 —— 与 `judge_not_wired`
    # 归 `not_wired` 是同一手法：码说"哪一层看出来的"，类目说"这是个什么错"。
    # `judge_bad_json` 从此只留给"真的不是 JSON"。
    ("judge_unknown_tool", "unknown_tool",
     "src/agentflow/judge.py:76（词表）/ src/agentflow/llmseam.py:1079（产出：没广告过的函数名）"),
    ("judge_bad_args", "judge_bad_args", "src/agentflow/agent_loop.py:4455,8142"),
    ("judge_no_reply:", "judge_no_reply", "src/agentflow/agent_loop.py:15,805（带后缀那一族）"),
    ("judge_timeout", "judge_no_reply", "src/agentflow/agent_loop.py:808（_NO_REPLY_NAMED）"),
    ("judge_output_limit", "judge_no_reply", "src/agentflow/agent_loop.py:808,837"),
    ("judge_failed:", "judge_failed", "src/agentflow/agent_loop.py:1135（真机 judge_failed:ModelReplyNotOk）"),
    ("judge_not_wired", "not_wired", "src/agentflow/judge.py:14（没接线那一档）"),
    # 拆分口径（2026-10-24，业主 D-65「修，且不再认为 multi_call 有问题」）：
    # 一步给多条调用是正常能力，所以这一步的读数进过程读数表：
    #   `steps_split` 数被拆分的步数 —— 它从 `result` 里的结构字段取（键名就是
    #   `multi_call`，`agent_loop` 写在回合的每一条上，取 `call_index == 0` 的那一条）；
    #   注意 `multi_call` 在这里是结构字段名，不是类目名（类目名是 `steps_split`）。
    #   `multi_call_executed_calls` 数真的执行了的条目（逐条记录 `agent_step_call`）。
    # 真的做错了才进错误类目：丢了几条 / 没执行成 / 超上限（下面那五行）。
    ("multi_call", "steps_split",
     "src/agentflow/agent_loop.py:5657（`result` 里的结构字段名，一个回合一条）"),
    ("agent_step_call", "multi_call_executed_calls",
     "src/agentflow/stepdispatch.py:53（STEP_CALL_EVENT 的定义）"),
    ("未执行（解码不出", "multi_call_discarded",
     "src/agentflow/agent_loop.py:6620（_record_undecodable_item 的结局原话）"),
    ("这一条解码不出来", "multi_call_discarded",
     "src/agentflow/stepdispatch.py:223（mark_not_executed 对解码不出那一档的原话）"),
    ("因本回合已收工未执行", "multi_call_unexecuted",
     "src/agentflow/stepdispatch.py:219（mark_not_executed 的收工那一档）"),
    ("因预算未执行", "multi_call_out_of_limit",
     "src/agentflow/stepdispatch.py:218（mark_not_executed 的预算那一档）"),
    ("not_executed", "multi_call_unexecuted",
     "src/agentflow/stepdispatch.py:216（mark_not_executed 的定义；没写理由时的兜底码）"),
    ("run_evidence_unreadable", "unreadable", "src/agentflow/closing.py:1082（RUN_EVIDENCE_UNREADABLE_CODE）"),
    ("context_graph_unreadable", "unreadable", "src/agentflow/agent_b/register_statement.py:946"),
    # ---- 流程层
    ("mapping_not_written", "closing_blocked", "src/agentflow/closing.py:3738（MAPPING_NOT_WRITTEN_CODE）"),
    ("run_evidence_unbacked", "closing_blocked", "src/agentflow/closing.py:1079（RUN_EVIDENCE_UNBACKED_CODE）"),
    ("quote_verified_without_span", "closing_blocked", "src/agentflow/closing.py:5560（收工门 quote_evidence 格）"),
    ("mapping_orphan", "paper_mapping_gap", "src/agentflow/papermapping.py:303"),
    ("mapping_file_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:303"),
    ("mapping_unresolvable", "paper_mapping_gap", "src/agentflow/papermapping.py:303,839"),
    ("mapping_citation_loc_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:308,1245"),
    ("mapping_citation_file_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:308,1286"),
    ("mapping_proof_program_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:324"),
    ("mapping_package_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:324"),
    ("mapping_lean_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:335,1330"),
    ("请代唤", "relay_after_refusal", "src/agentflow/agent_loop.py:81（RELAY_SUBJECT）"),
)

#: 码 → 类目（由 `CODE_TABLE` 派生，只有这一处真身）。
CODE_TO_CATEGORY: dict[str, str] = {code: cat for code, cat, _ in CODE_TABLE}

#: 码 → 出处（file:line，人读用）。
CODE_PROVENANCE: dict[str, str] = {code: where for code, _cat, where in CODE_TABLE}

_CATEGORY_INDEX: dict[str, int] = {cat: i for i, (cat, _why) in enumerate(ALL_CATEGORIES)}
_CODE_INDEX: dict[str, int] = {code: i for i, (code, _c, _w) in enumerate(CODE_TABLE)}

#: 匹配顺序：类目表顺序优先，同类目里字数长的先试。这就是主码规则的唯一实现。
#:
#: 为什么类目顺序优先而不是纯按字数：一条被拒的行常常同时带着两层码 ——
#: `refusal_reason=invalid_params`（粗：这次调用不成立）与 detail 里的
#: `行校验失败`（细：写库那一刻被 schema 拦住）。纯按字数会让 `invalid_params`
#: （14 字）压过 `行校验失败`（5 字），于是写入期判据那一类永远收不到数。
#: 类目顺序把结构性判据排在前面（根因先看），同类目里再让长码胜出 ——
#: 于是 `judge_not_wired` 不会被 `not_wired` 抢先（两者同类目，长的那个更准）。
_MATCH_ORDER: tuple[tuple[str, str], ...] = tuple(
    (code, cat)
    for code, cat, _where in sorted(
        CODE_TABLE,
        key=lambda t: (_CATEGORY_INDEX[t[1]], -len(t[0]), _CODE_INDEX[t[0]]))
)

#: 事件流里带拒绝语义的两档 `tasks.outcome`。
_REFUSAL_OUTCOME = "refused"
_FAILED_OUTCOME = "failed"


# ---------------------------------------------------------------- 主码


def primary_code(*texts: Any) -> tuple[str, str] | None:
    """这段文字命中的主码：(码, 类目)。没有命中 ⇒ None。

    口径见模块 docstring 第 2 条：类目表靠前的类目优先，同类目里字数长的码优先
    （同长按 `CODE_TABLE` 的顺序）；顺序的唯一实现在 `_MATCH_ORDER` 里。
    `texts` 里空值与非字符串一律先折成空串，于是"字段缺失"与"字段是空串"同形 ——
    这两件事在统计上本来就该同形（都等于"这条记录没留下这句话"）。
    """
    blob = " ".join(str(t) for t in texts if t)
    if not blob:
        return None
    for code, cat in _MATCH_ORDER:
        if code in blob:
            return (code, cat)
    return None


# ---------------------------------------------------------------- 结果形状


def _error_category(category: str) -> str:
    """确认这是一个错误类目，原样返回；传的是过程读数类目就抛 `ValueError`。

    为什么抛而不是回 0：0 会把"这不是一个错误类目"读成"这一类没有"，而这两件事的处置
    完全不同（前者是口径错用，后者是读数）。同一个理由见模块 docstring 的三态那一条。
    """
    if category in PROCESS_CATEGORY_NAMES:
        raise ValueError(
            f"{category} 是过程读数（拆分），不是错误类目 —— 请用 process_category_total / "
            "process_count；它不进 total 是有意的（业主 D-65）")
    return category


@dataclass(frozen=True)
class ErrorStats:
    """按角色的错误动作计数。`by_role[role][category]` 就是业主问的那张表。

    `by_role` / `role_total` / `total` 只数错误类目（`ERROR_CATEGORIES`）；
    过程读数（拆分）在 `process` 里，单独一栏、不进任何"错误动作"总数 ——
    业主 D-65 的口径：「不再认为 multi_call 有问题」。两个桶分开是这份读数的
    结构事实，不是每个调用点自己记得"这个不计错"。

    三态三件套（`checked` / `state` / `reason`）与计数并排返回，而不是藏在异常里：
    读不到事件流时 `total` 是 0 但 `checked=False`，于是"0 次错误"与"没读到"不会
    被同一个数字表示。`sources` 是逐源的读数，人排查时先看它。
    """

    by_role: dict[str, dict[str, int]] = field(default_factory=dict)
    role_total: dict[str, int] = field(default_factory=dict)
    total: int = 0
    #: 角色 → 过程读数类目 → 条数（拆分生效的正读数；不计错，见 `PROCESS_CATEGORIES`）。
    process: dict[str, dict[str, int]] = field(default_factory=dict)
    checked: bool = False
    state: str = "unknown"
    reason: str = ""
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def count(self, role: str, category: str) -> int:
        """某角色在某错误类目上的条数。过程读数请用 `process_count`（传错类目会抛）。"""
        _error_category(category)
        return int(self.by_role.get(role, {}).get(category, 0))

    def category_total(self, category: str) -> int:
        """某错误类目的全角色合计。过程读数请用 `process_category_total`。"""
        _error_category(category)
        return sum(int(c.get(category, 0)) for c in self.by_role.values())

    def process_count(self, role: str, category: str) -> int:
        """某角色在某过程读数类目上的条数（不计错的那些读数走这一格）。"""
        return int(self.process.get(role, {}).get(category, 0))

    def process_category_total(self, category: str) -> int:
        """某过程读数类目的全角色合计。

        刻意不给"过程读数总计"：两个读数的单位不同（步 / 条），加起来没有意义 ——
        一个"38"既可能是 38 步也可能是 38 条，那种数字不该存在。
        """
        return sum(int(c.get(category, 0)) for c in self.process.values())

    def categories(self) -> dict[str, int]:
        """错误类目 → 全角色合计（按 `ERROR_CATEGORIES` 的顺序，只留非 0 的）。"""
        out: dict[str, int] = {}
        for cat, _why in ERROR_CATEGORIES:
            n = self.category_total(cat)
            if n:
                out[cat] = n
        return out

    def process_categories(self) -> dict[str, int]:
        """过程读数类目 → 全角色合计（按 `PROCESS_CATEGORIES` 的顺序，只留非 0 的）。"""
        out: dict[str, int] = {}
        for cat, _why in PROCESS_CATEGORIES:
            n = self.process_category_total(cat)
            if n:
                out[cat] = n
        return out

    def as_dict(self) -> dict[str, Any]:
        """机器可读形态（CLI 的 `--json` 直接印它）。

        `by_role` / `role_total` / `total` 只含错误类目；`process` 与 `process_by_role`
        是过程读数（拆分）。两组键刻意不合并：合并之后 `total` 又不等于"错误动作总数"了。
        """
        return {
            "by_role": {r: dict(sorted(c.items())) for r, c in sorted(self.by_role.items())},
            "role_total": dict(sorted(self.role_total.items())),
            "total": int(self.total),
            "process_by_role": {r: dict(sorted(c.items()))
                                for r, c in sorted(self.process.items())},
            "process": dict(self.process_categories()),
            "checked": bool(self.checked),
            "state": self.state,
            "reason": self.reason,
            "sources": {k: dict(v) for k, v in self.sources.items()},
        }


# ---------------------------------------------------------------- 读盘（只读）


def _resolve_target(target: Any) -> tuple[Path, Any]:
    """`target` 可以是工作区根路径，也可以是 `Store`（用它自己的 `root`）。"""
    if hasattr(target, "read_events") and hasattr(target, "root"):
        root = Path(str(getattr(target, "root") or "."))
        return (root, target)
    return (Path(str(target)), None)


def _read_events(root: Path, store: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读事件流。返回（事件列表, 读数）。读不到 ⇒ 读数里 `checked=False` 且给出原因。"""
    reading: dict[str, Any] = {"checked": False, "events": 0, "bad_lines": 0,
                              "table": "tasks", "reason": ""}
    if store is not None:
        try:
            rows = [dict(e) for e in store.read_events()]
        except Exception as e:  # noqa: BLE001 读不到与"是 0 条"必须分得开
            reading["reason"] = f"事件流读不到（{type(e).__name__}: {e}）"
            return ([], reading)
        reading.update(checked=True, events=len(rows), reason="")
        return (rows, reading)

    path = root / "data" / "events.jsonl"
    if not root.exists() or not root.is_dir():
        reading["reason"] = f"工作区不存在：{root}"
        return ([], reading)
    if not path.exists():
        reading["reason"] = f"事件流不存在：{path}"
        return ([], reading)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        reading["reason"] = f"事件流读不到（{type(e).__name__}: {e}）"
        return ([], reading)
    rows = []
    bad = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            bad += 1
    reading.update(checked=True, events=len(rows), bad_lines=bad,
                   reason="" if rows or not bad else "事件流每一行都读不明白")
    if not rows and bad:
        reading["checked"] = False
    return (rows, reading)


def _read_sessions(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读会话记录。目录不在 ⇒ 按"这个工作区没有会话记录"读（0 条，checked）。"""
    reading: dict[str, Any] = {"checked": False, "files": 0, "records": 0,
                               "bad_lines": 0, "unreadable_files": [], "reason": ""}
    if not root.exists() or not root.is_dir():
        reading["reason"] = f"工作区不存在：{root}"
        return ([], reading)
    folder = root / "sessions"
    if not folder.is_dir():
        reading.update(checked=True, reason="没有 sessions 目录（按 0 条读）")
        return ([], reading)
    paths = sorted(p for p in folder.glob("*.jsonl") if p.is_file())
    if not paths:
        reading.update(checked=True, reason="sessions 目录里没有 .jsonl")
        return ([], reading)
    records: list[dict[str, Any]] = []
    bad = 0
    broken: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            broken.append(path.name)
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if isinstance(obj, dict):
                records.append(obj)
            else:
                bad += 1
    readable = len(paths) - len(broken)
    reading.update(files=readable, records=len(records), bad_lines=bad,
                   unreadable_files=broken,
                   checked=readable > 0,
                   reason="" if readable else "sessions 目录里每个文件都读不明白")
    return (records, reading)


def _latest_task_rows(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """事件流里 `tasks` 表每个 `task_id` 的最后一行（后写覆盖先写）。"""
    latest: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        if str(event.get("table") or "") != "tasks":
            continue
        if str(event.get("op") or "") not in ("upsert", "append"):
            continue
        row = event.get("row")
        if not isinstance(row, Mapping):
            continue
        tid = str(row.get("task_id") or "")
        if not tid:
            continue
        if tid not in latest:
            order.append(tid)
        latest[tid] = dict(row)
    return [latest[tid] for tid in order]


def _role_name(value: Any) -> str:
    name = str(value or "").strip()
    return name or UNKNOWN_ROLE


def _known_role(value: Any) -> bool:
    name = str(value or "").strip()
    return bool(name) and (name in S.ROLES or name == S.CONDUCTOR_ROLE)


def _step_text(record: Mapping[str, Any]) -> str:
    """一条 `agent_step` 的拒信原话（可扫的那一段）。

    只取 `result.error` / `result.warn` / `result.problem` / `result.kind` 与记录自己的
    `problem`，不取 `payload`（理由见模块 docstring：模型"提到一个码"不等于"撞上那个码"）。
    """
    parts: list[str] = []
    problem = record.get("problem")
    if problem:
        parts.append(str(problem))
    result = record.get("result")
    if isinstance(result, Mapping):
        for key in ("error", "warn", "problem", "kind"):
            value = result.get(key)
            if value:
                parts.append(str(value))
    elif isinstance(result, str):
        parts.append(result)
    return " ".join(parts)


# ---------------------------------------------------------------- 核心函数


def _call_text(record: Mapping[str, Any]) -> str:
    """一条 `agent_step_call` 的可扫那段文字：只有它自己的结局原话（`outcome`）。

    刻意不拼工具名、不拼 `reason`、不拼条号：这段文字只回答"这一条为什么没执行"，
    拼进去的东西越多，撞上不相干的码的机会越大（"一条记录只算一次"那条纪律的前提）。
    """
    return str(record.get("outcome") or "")


def _is_split_step(record: Mapping[str, Any]) -> bool:
    """这一步是不是"被拆开的那一步"（结构判据，不读文案）。

    判据是 `agent_loop` 写进 `result` 的那个结构字段：`multi_call` = 这一条属于哪个回合、
    第几条、这一回合共几条（`stepdispatch.StepDispatch.provenance`）。取 `call_index == 0`
    的那一条 ⇒ 一个被拆分的回合正好记一次。

    为什么不按 `result.warn` 里那句"这一步给了 N 条调用，已按顺序逐条"数：三条理由逐条写在
    模块 docstring 的"拆分是能力，不是错"那一段（漏记 / 被错误原话抢先 / 与逐条结局重复）。
    判据 `tests/test_multi_call_is_a_capability_not_an_error.py` 的 d 把这一处打桩成
    "没拆分" ⇒ a 必红（证明 a 数的就是这件事，不是别的什么）。
    """
    result = record.get("result")
    if not isinstance(result, Mapping):
        return False
    batch = result.get("multi_call")
    if not isinstance(batch, Mapping):
        return False
    try:
        return int(batch.get("call_index", -1)) == 0
    except (TypeError, ValueError):
        return False


def error_action_stats(target: Any) -> ErrorStats:
    """按角色统计错误动作计数。`target` 可以是工作区根路径，也可以是 `Store`。

    纯读：不写库、不写盘、不建目录、不加锁（`Store.read_events` 本身只读文件）。
    三态见模块 docstring 第 3 条：读不到 ⇒ `checked=False` / `state="unknown"`，
    不把"没读到"折成 0。
    """
    root, store = _resolve_target(target)
    events, ev_reading = _read_events(root, store)
    records, ss_reading = _read_sessions(root)

    counts: dict[str, dict[str, int]] = {}
    process: dict[str, dict[str, int]] = {}
    hits: dict[str, dict[str, int]] = {}

    def _bump(role: str, code: str, cat: str) -> None:
        """记一条命中。落哪个桶由类目决定（`PROCESS_CATEGORY_NAMES`），不由调用点决定。

        为什么把分桶放在这里：于是"过程读数"在结构上进不了 `total` / `role_total` ——
        任何一条路径把拆分读数当错误记，它都会落进另一个桶。而不是靠每个调用点自己记得
        "这个不计错"（那种纪律一定会漏，而漏了不会有任何地方报错）。
        """
        bucket = process if cat in PROCESS_CATEGORY_NAMES else counts
        cells = bucket.setdefault(role, {})
        cells[cat] = int(cells.get(cat, 0)) + 1
        seen = hits.setdefault(role, {})
        seen[code] = int(seen.get(code, 0)) + 1

    # ---- 事件流：tasks 行的拒绝与失败
    if ev_reading.get("checked"):
        for row in _latest_task_rows(events):
            outcome = str(row.get("outcome") or "")
            if outcome not in (_REFUSAL_OUTCOME, _FAILED_OUTCOME):
                continue
            found = primary_code(row.get("refusal_reason"), row.get("error"), row.get("detail"))
            if found is None:
                # 被拒但理由码不在码表里（历史行 / 新码没登记）：不猜一个类目出来，
                # 也不静默丢掉 —— 记进 `sources.events.unclassified`，人读的呈现里会点名。
                # 这条纪律与"没读到不许折成 0"同族：没见过的东西不许编，但必须看得见。
                if outcome == _REFUSAL_OUTCOME:
                    ev_reading["unclassified"] = int(ev_reading.get("unclassified") or 0) + 1
                continue
            code, cat = found
            if code in CALLER_ATTRIBUTED_CODES and _known_role(row.get("called_by")):
                role = _role_name(row.get("called_by"))
            else:
                role = _role_name(row.get("role"))
            _bump(role, code, cat)

    # ---- 会话记录：判据层的 problem、工具层的拒信、代唤请示
    if ss_reading.get("checked"):
        for record in records:
            kind = str(record.get("kind") or "")
            role = _role_name(record.get("role"))
            if kind == "llm_call":
                found = primary_code(record.get("problem"), record.get("detail"))
                if found is not None:
                    _bump(role, *found)
                continue
            if kind == "agent_step":
                # 这一段文字只数错误类目：多调用那一族不从这里数（`MULTI_CALL_CATEGORIES`）。
                # 理由：那句汇总（"这一步给了 N 条调用，已按顺序逐条…"）与"被拆分的步数"
                # 是同一件事，且它本身是逐条结局原话的拼串 —— 扫它会把同一件事数两遍。
                found = primary_code(_step_text(record))
                if found is not None and found[1] not in MULTI_CALL_CATEGORIES:
                    _bump(role, *found)
                # 拆分这件事的读数从结构字段取：一个被拆分的回合正好记一次。
                if _is_split_step(record):
                    _bump(role, "multi_call", "steps_split")
                continue
            if kind == "agent_step_call":
                # 逐条记录：一条一个结局，三档互斥。
                # 执行了 ⇒ 过程读数 `multi_call_executed_calls`（拆分生效的正读数）；
                # 没执行 ⇒ 按它自己的结局原话进三个真失败类目之一（`_call_text`）。
                # "一条记录只算一次"在这里成立：本记录只往一个桶里记一次。
                if not bool(record.get("not_executed")):
                    _bump(role, "agent_step_call", "multi_call_executed_calls")
                    continue
                found = primary_code(_call_text(record))
                if found is None or found[1] not in MULTI_CALL_CATEGORIES:
                    # 结局原话不在码表里（老记录 / 新理由没登记）：不猜，记进兜底那一档
                    # —— 它至少说明"这一条拆出来了但没执行成"，那是真的少做了一条。
                    found = ("not_executed", "multi_call_unexecuted")
                _bump(role, *found)
                continue
            if kind == "agent_message":
                subject = str(record.get("subject") or "")
                found = primary_code(subject)
                if found is not None and CODE_TO_CATEGORY.get(found[0]) == "relay_after_refusal":
                    _bump(_role_name(record.get("from")), *found)
                continue

    role_total = {role: sum(cats.values()) for role, cats in counts.items()}
    total = sum(role_total.values())

    checked = bool(ev_reading.get("checked")) and bool(ss_reading.get("checked"))
    reasons: list[str] = []
    if not ev_reading.get("checked"):
        reasons.append(str(ev_reading.get("reason") or "事件流读不到"))
    if not ss_reading.get("checked"):
        reasons.append(str(ss_reading.get("reason") or "会话记录读不到"))
    sources = {
        "events": ev_reading,
        "sessions": ss_reading,
        "hits": {"checked": checked, "codes": {r: dict(sorted(c.items())) for r, c in sorted(hits.items())}},
    }
    return ErrorStats(
        by_role={r: dict(sorted(c.items())) for r, c in sorted(counts.items())},
        role_total=dict(sorted(role_total.items())),
        total=total,
        process={r: dict(sorted(c.items())) for r, c in sorted(process.items())},
        checked=checked,
        state="checked" if checked else "unknown",
        reason="；".join(reasons),
        sources=sources,
    )


# ---------------------------------------------------------------- 人读的呈现


def _shown_width(text: str) -> int:
    """显示宽度（CJK 占两格）。表格对齐只靠它，靠 `len` 会把中文表头错开一格。"""
    shown = 0
    for ch in text:
        shown += 2 if ord(ch) > 0x2E7F else 1
    return shown


def _pad(text: str, width: int) -> str:
    """按显示宽度补空格。"""
    return text + " " * max(0, width - _shown_width(text))


def _table_lines(head: list[str], rows: list[list[str]]) -> list[str]:
    """一张按显示宽度对齐的小表（表头 + 分隔线 + 各行）。错误表与拆分读数表共用这一份。"""
    widths = [max(_shown_width(head[i]), *(_shown_width(r[i]) for r in rows))
              for i in range(len(head))]
    widths = [max(w, 4) for w in widths]
    out = ["  ".join(_pad(head[i], widths[i]) for i in range(len(head))).rstrip(),
           "  ".join("-" * widths[i] for i in range(len(head)))]
    for row in rows:
        out.append("  ".join(_pad(row[i], widths[i]) for i in range(len(head))).rstrip())
    return out


def render_text(stats: ErrorStats) -> list[str]:
    """渲染成两张小表：错误动作（角色 × 类目）与拆分读数（过程读数，不计错）。

    CLI 与非 CLI 调用共用这一份。两张表分开是有意的：把拆分那几格混进错误表，
    读的人会把"系统拆了一步"看成"出错了" —— 而业主 D-65 的口径正好相反。
    拆分那一栏的措辞也是中性的（"被拆分的步数" / "拆出来并执行了的调用条数"），
    它旁边那句才点名三档真失败（discarded / unexecuted / out_of_limit）。
    """
    lines: list[str] = []
    events = stats.sources.get("events") or {}
    sessions = stats.sources.get("sessions") or {}
    lines.append("错误动作计数（按角色 × 类目；只读，零模型调用）")
    lines.append(f"三态    checked={stats.checked}  state={stats.state}")
    if stats.reason:
        lines.append(f"原因    {stats.reason}")
    lines.append(
        "读数    事件流 {ev} 条（{evbad} 行读不明白）/ 会话记录 {ss} 条（{files} 个文件，"
        "{ssbad} 行读不明白）".format(
            ev=events.get("events", 0), evbad=events.get("bad_lines", 0),
            ss=sessions.get("records", 0), files=sessions.get("files", 0),
            ssbad=sessions.get("bad_lines", 0)))
    if not stats.checked:
        lines.append("")
        lines.append("没有读到该读的东西 ⇒ 这里的 0 不是『没有错误动作』，是『没查成』。")
    unclassified = int(events.get("unclassified") or 0)
    if unclassified:
        lines.append(f"未归类  {unclassified} 条被拒的理由码不在码表里（未计入任何类目；"
                     "要收进来就把它登记进 CODE_TABLE）")

    cats = list(stats.categories().items())
    lines.append("")
    lines.append("错误动作（角色 × 类目；只有这张表进 total）：")
    if not cats:
        lines.append("  全 0（错误类目一条都没命中）" if stats.checked else "  无可报读数")
    else:
        head = ["角色"] + [cat for cat, _n in cats] + ["合计"]
        rows: list[list[str]] = []
        for role in sorted(stats.role_total):
            rows.append([role] + [str(stats.count(role, cat)) for cat, _n in cats]
                        + [str(stats.role_total.get(role, 0))])
        rows.append(["合计"] + [str(n) for _cat, n in cats] + [str(stats.total)])
        lines += _table_lines(head, rows)
        lines.append("")
        lines.append("类目释义：")
        meanings = dict(ERROR_CATEGORIES)
        for cat, _n in cats:
            lines.append(f"  {cat}: {meanings.get(cat, '')}")

    # ---- 过程读数（不是错误，单独一栏）
    proc = list(stats.process_categories().items())
    lines.append("")
    lines.append("过程读数（不是错误：步被拆开逐条执行是正常能力，直写被转交正路办成也是）：")
    if not proc:
        lines.append("  没有任何过程读数（被拆分的步数 0 / 拆出来的调用 0 / 转交办成 0）")
    else:
        phead = ["角色"] + [cat for cat, _n in proc]
        prows: list[list[str]] = []
        for role in sorted(stats.process):
            prows.append([role] + [str(stats.process_count(role, cat)) for cat, _n in proc])
        prows.append(["合计"] + [str(n) for _cat, n in proc])
        lines += _table_lines(phead, prows)
        lines.append("  （合计按类目给，不按角色求和：两个读数的单位不同 —— 步 / 条）")
        pmeanings = dict(PROCESS_CATEGORIES)
        for cat, _n in proc:
            lines.append(f"  {cat}: {pmeanings.get(cat, '')}")
    lines.append(
        "  真失败长在错误表上：多调用那三档（"
        f"multi_call_discarded={stats.category_total('multi_call_discarded')} / "
        f"multi_call_unexecuted={stats.category_total('multi_call_unexecuted')} / "
        f"multi_call_out_of_limit={stats.category_total('multi_call_out_of_limit')}"
        "）与兜底方没接住那一档（routed_to_backstop="
        f"{stats.category_total('routed_to_backstop')}）全 0 才是绿；"
        "『步被拆分』与『转交办成』本身都不是失败。")

    lines.append("")
    lines.append("口径：角色归属见 errorstats 模块 docstring（召唤期结构判据记 called_by）；"
                 "一条记录只算一次，主码 = 类目表靠前的类目优先、同类目里长码优先。"
                 "过程读数是 process，不进 total / role_total（业主 D-65）。")
    return lines


def stats_json(stats: ErrorStats) -> str:
    """机器可读一行（`--json` 用）。"""
    return json.dumps(stats.as_dict(), ensure_ascii=False, indent=2)

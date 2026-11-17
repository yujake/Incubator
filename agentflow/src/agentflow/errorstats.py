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
   而"这条边被拒"这件事记在被召唤的那一行上。例（`role=B`、`called_by=G`）：
   拒信逐字是 "G → B 不在策略允许的边里"。所以归属按码分流：
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
  算两次（`runs/B-*.json` 与 `sessions/*.jsonl` 的 `agent_step` 逐条对应）。

## 拆分是能力，不是错（D-65：multi_call 不是错误）

一步给多条调用是正常能力：`stepdispatch` 把它整包接住、按原顺序拆成条目、逐条执行与记账。
所以"这一步被拆开逐条执行了"这件事不是错误动作，它是"系统在按设计工作"的证据 ——
把它算进错误总数，等于把正常行为记成错误。

因此类目分成两张表，`by_role` / `role_total` / `total` 只数错误那一张：

- `ERROR_CATEGORIES`（错误，计入 `total`）：多调用这一族只留三档真失败——
  `multi_call_discarded`（拆的时候这一条解码不出来 ⇒ 丢了，少做一条）/
  `multi_call_unexecuted`（拆出来了、这一趟没执行成）/ `multi_call_out_of_limit`
  （超上限：这一趟还剩的步数/花销不够，那几条没执行）。三档全 0 才是绿。
- `PROCESS_CATEGORIES`（过程读数，单独一栏、不计错）：`steps_split`（被拆分的步数）与
  `multi_call_executed_calls`（拆出来并真的执行了的调用条数），外加
  `direct_write_routed`（直写请求被系统转交正路并办成的条数）。

## 路由成功也是过程读数，不是错误

直写兜底那一档（`routed_to_backstop`）若把三件不同的事混在一个类目里：路由办成了 /
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

## 覆盖面：新类只从字段取

盘上"出错 / 被拒 / 被挡"的结构化信号远多于按文案类目数到的量。漏的原因不是数错，
是入口只有一条：每个类目都靠"文案里出现某个码"命中，于是三种漏法同时成立：

1. 真相在字段里，文案里没有码：`ok=False`、`item_state="seen"`、`target.judge`、
   `outcome="cut_off_by_parent"` —— 这些字段一个都不带码名；
2. 有些源整个没被读：`verifications/`、`out/roster/`、`out/secretary/` 三个目录；
3. 有些码恒为 0：`tasks.outcome="refused"` 可以是 0 行 —— 真正的拒绝全
   发生在工具层（`ok=false`）与名册层（写口拒绝）。于是 `STATUS-*.json` 的
   `action_refusals.total` 也恒为 0：监控在盯一个恒为 0 的字段。

### 一、新 15 类全部是结构化类目，不进 `_MATCH_ORDER`

这是唯一一条硬口径，理由是文案判据的假阳性：

- `judge_bad_json` 这个字符串大多出现在 `result.data`（`table.describe` 打印的码表清单）、
  `reasoning`、`payload` 里，真正的坏 JSON 极少。按文案数会十倍级虚高。
- `timeout` / `重试` / `回滚` / `cancelled` 多数是提示词原文，真的超时 / 重试 / 回滚极少。
- `warn` 里的多调用汇总逐条复述"第 2 条 fs.read 被拒：. 是目录" —— 按文案数会把同一件事
  数两遍（与 D-65 那条纪律正面冲突）。

所以新 15 类只从字段取，`_MATCH_ORDER` 里一个都没有；`CODE_TABLE` 里仍逐条登记它们的
码与出处（`test_every_category_has_a_code_that_really_exists_in_the_source` 靠它，人读
出处也靠它）。结构判据在读侧独立成函数（`_tool_refusal_family` 等），每个都写明读哪一格。

### 二、三个桶，不许相加

| 桶 | 装什么 | 进不进"错误动作"总数 |
|---|---|---|
| `by_role` / `role_total` / `total` | 角色侧：这一方自己的动作做错了 / 被拦了 | 进（唯一的总数） |
| `system` / `system_total` | 系统侧：判据自己没判成、外部面掉了、收工门拦下 | 不进（单位不同：一边是"谁做错了"，一边是"系统哪里坏了"） |
| `state_readings` | 状态读数：板项没被 ack（快照，会回落） | 不进（它是"现在积着什么"，不是"发生过几次"） |
| `process` | 过程读数（拆步 / 转交办成 / 被叫停 / 自愈补登记） | 不进（已有的纪律） |

页面顶部那三个数（角色侧 X / 系统侧 Y / 状态读数 Z）刻意不相加：把"谁做错了"与"系统
哪里坏了"加起来得不到任何一个有名字的量。

### 三、六档归属（`ATTRIBUTION_BUCKETS` / `attribution_of`）

归属原本只有两档（`CALLER_ATTRIBUTED_CODES` 记 `called_by`，其余记 `role`）。新类里有四种
"错的那一方不是记录里那个人"的形态，所以扩成六档，逐档写明理由：

| 档 | 什么时候 | 记谁 |
|---|---|---|
| `actor` | 这条记录就是它自己的动作回执（默认） | 记录里的 `role` |
| `caller` | 结构判据说"这次派活派错了"：召唤期六条 + 送审时命题没登记 + 父退场切断 | `called_by`（或送审方） |
| `author` | 证明本身有毛病 ⇒ 记写出这条证明的那一方 | `statements.proof_authors` → 退回 `created_by` |
| `recipient` | 板项没被 ack ⇒ 记该 ack 的那一方 | 板项行的 `role`（收件人） |
| `roster` | 名册写口拒了一个名字 | 要这个名字的那一方（`owner` 的 `role`） |
| `system` | 判据没判成 / 外部面掉了 / 收工门拦下 | `（系统）`，进 `system` 桶 |

`author` 那一档是最要紧的一条：V 判「有毛病」而命题的 `proof_authors` 是 `["F"]` 时，
记到 V 头上就等于"复核的人替写证明的人背锅"，那正是判据
`test_error_action_stats.py` 钉的第一条（"一方的错不算到另一方头上"）的反面。

### 四、去重：三对必须点名（否则一扩面就翻倍）

主码规则管的是"同一段文字里多个码"；新类会撞的是"同一件事落在两条记录上"。下面三对
是逐条核过会撞的，已在读侧显式登记：

| 对 | 为什么撞 | 怎么去重 |
|---|---|---|
| `agent_step` ↔ `agent_step_call` | 一步给多条调用时，步与逐条记录都在盘上；`warn` 的汇总还逐条复述结局 | 步只数 `result.ok is False` 那一档；逐条记录只数 `not_executed`，两者不重叠 |
| `verifications/<号>.jsonl` ↔ V 的 `agent_step` | V 的回执把同一句判词又说了一遍 | 只从 `verifications/` 数，V 的步只在没有台账行时兜底（`verdict_missing`） |
| `out/roster/refusals/*.jsonl` ↔ 秘书的证据流水 | 写口拒一次，两处各落一条 | 只从 `refusals/` 数，秘书行只提供"谁要的这个名字" |

### 五、明确不算错误动作（不写死这一条，一扩面就一定报警疲劳）

四条主排除（记进去就会把真信号淹掉）：

| # | 事件 | 为什么不算 | 归到哪 |
|---|---|---|---|
| ① | `item_close="acked"`（正常 ack） | 占板项的绝大多数 | 不记 |
| ② | `retire`（正常销号） | 收口的正常形态 | 不记 |
| ③ | `cancelled` 当且仅当 `runs/stop-history.jsonl` 里有 `by="user"` 的记录 | 人叫停不是错误 | 单列读数 `task_stopped` |
| ④ | `roster_repair` 成功补登记 | 自愈成功 ⇒ 与 `direct_write_routed` 同一手法：办成了不算错 | 单列读数 `roster_repaired` |

四条同族排除（同一理由，只是量小）：

| 事件 | 为什么不算 | 归到哪 |
|---|---|---|
| `outcome ∈ {ok, no_result, not_applicable}` | 做了 / 查了没有 / 不适用 | 不记 |
| `vsigns.index_drift` 的 `not_applicable` | `out/vsigns/` 不在 = 这个工作区还没签（合法初态） | 不记 |
| 秘书 `decision ∈ {可派, 合格, 已优化, 建议不派, 建议重排, 已执笔, 已洗稿, 已提醒}` | 正常工作 | 不记 |
| `multi_call` 拆步 / `direct_write_routed` | 已有裁定（D-65） | 已在 `process` |

`cancelled` 那一条是本表最容易改坏的一格：它现在是"先看停机流水、再决定算不算"。谁把
这一步改成"看到 cancelled 就记一条错误"，用户自己按的停止键就会变成假错误。

### 六、本模块读七个源

| 源 | 路径 | 三态口径 |
|---|---|---|
| `events` | `data/events.jsonl` | 不存在 ⇒ `checked=False` |
| `sessions` | `sessions/*.jsonl` | 目录不存在 ⇒ 正常形态（0 条，`checked=True`） |
| `verifications` | `verifications/*.jsonl` | 同上（没有签名就是 0 条） |
| `roster` | `out/roster/*.jsonl` + `refusals/` | 同上 |
| `secretary` | `out/secretary/*.jsonl` | 同上 |
| `statements` | `data/statements.json`（只取 `proof_authors`） | 读不出来 ⇒ `author` 那一档记 `（未记作者）`，不猜 |
| `closing` | 现算 `closing.check_closing` | 没有 `out/` ⇒ `not_applicable`（收工门没有对象）；算不出来 ⇒ `unknown` |

`closing` 是唯一"现算"的源，也是唯一可能慢的：它的读数与 Acceptance 页同一处
（`closing.check_closing`），不在本模块重算一份口径。

## 码 → 类目这张表从哪来

`CODE_TABLE` 每行是（码, 类目, 出处）。出处写符号名而不写行号（行号在并行开发下会漂）。
判据 `tests/test_error_action_stats.py` 会扫源码断言表里每个码真的出现
在 `src/agentflow/` 的某个文件里（扫的时候排除本文件，否则这张表会自己证明自己）。
类目本身逐类写过一行含义（`ERROR_CATEGORIES`）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import schema as S
from . import sessions as SS
from .canonical import json_default

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
    # ---- 以下 11 类是结构化类目扩面追加的。
    #
    # 一律追加在末尾，一条都不许插到上面去：`_MATCH_ORDER` 的优先级是"类目表靠前优先"，
    # 插在中间会让老例子的主码换类目 —— 而 `test_error_action_stats.py` 把六个老例子
    # 逐条钉住了。判据 `test_the_primary_code_rule_is_pinned` 就是这条纪律的机器读数。
    #
    # 这 11 类都不进 `_MATCH_ORDER`（结构化类目，见模块 docstring 第一节）。
    ("roster_write_refused",
     "名册写口拒绝：要一个已经被用掉的名字 / reuse 与 want_name 同时给 ⇒ 这次派活没成立"
     "（记'要这个名字的那一方'，不是秘书；只有 refusal_code 时按码分，没有码时按原话点名）"),
    ("tool_refused_path",
     "工具层路径判据：文件 / 路径不存在、目标是目录、这一行没有全文路径 ⇒ 模型对着盘上"
     "不存在的东西干活（幻觉操作的最早信号；判据读 `result.ok is False` + `result.error`）"),
    ("tool_refused_reserved",
     "保留产物闸：手写框架渲染的证明 / 研究手稿 ⇒ 模型想绕过渲染正路"
     "（判据读 `result.error` 的 `框架渲染的产物` 原话，产出点 `tools/fs_tools.py`）"),
    ("tool_refused_edit_window",
     "定点替换闸：old_string 找不到 / 出现了多次 / 一次改动超过单次上限 ⇒ 没读盘就改盘"
     "（判据读 `result.error` 的 `old_string 在` / `单次定点替换上限`）"),
    ("experiment_failed",
     "实验失败：脚本跑了、给出不可复核的结论（result=refutes 却没有 counterexample）或崩了"
     "（判据读 `result.error` 的 `实验执行失败`；产出点 `tools/verify_tools.py`）"),
    ("experiment_refused",
     "实验跑之前就被拒：参数在跑脚本之前就不合格（R-01 一分钟都不该花）⇒ 白派一次活"
     "（判据读 `result.error` 的 `跑脚本之前`；与 experiment_failed 分开计：一个白跑，一个没跑）"),
    ("reply_shape_rejected",
     "回复形状被拒：一句话里同时给两件事（`一次只能说一件事`）/ 计划结构缺字段"
     "（`攻坚计划被拒绝`）⇒ 不是参数坏、也不是 JSON 坏，是这次回话的形状不成立"),
    ("child_cut_off",
     "被父退场切断：父代理退场时它还在跑，这一行由父的退场结算写成终态、结果未知"
     "（判据读 `tasks.outcome == 'cut_off_by_parent'`，记发起方 `called_by`）"),
    ("verdict_missing",
     "没审成：命题还没登记就送审（`statement_missing`），台账不留行 ⇒ 这一次复核空转"
     "（判据读 V 的 `result.data.kind`；不留行是有意的：留一行会把'没查成'冒充成'审过了'。"
     "归属记送审方 `called_by`；查不到送审方时退回动作方 —— 真机 82 的 `agent_step` 不带 "
     "`task_id`，落到的就是这一档，读数上看得见）"),
    ("verdict_understated",
     "低报缺陷：V 的回复称'未找到实质缺陷'，而秘书的判词是`有缺陷要指出` ⇒ 判据在低报"
     "（判据读 `out/secretary/*.jsonl` 的 `target.judge == 'v_reply_defect'` + `decision`）"),
    ("proof_defect_found",
     "证明有毛病：V 判`有毛病`或 `unresolved_errors > 0` ⇒ 产出不达标"
     "（判据读 `verifications/<号>.jsonl`；记命题作者 `proof_authors`，不是记 V）"),
    # 受控拒绝（`conductor_tools._out` 的最后一句把 `data` 的每一格都当 meta 再交给
    # `ok(...)`）：一次"拒绝"在工具层是 `ok=True`，拒因住在 `data.state == "refused"` /
    # `data.refusal_code` 里。只认 `ok is False` 会让真形受控拒绝 total 0。有
    # `data.refusal_code` 的按那个码登记的类目记（`target_not_silent` 等）；只有
    # `state=="refused"` 而没有码的落这一类 —— 码位留空：状态不是码，不把
    # `data.state` 的状态值登记成假码（那是"状态≠码"的折平）。
    ("tool_refused_controlled",
     "工具层受控拒绝（无码那一档）：`result.ok is True` 而 `data.state == 'refused'`、"
     "且 `data.refusal_code` 为空 ⇒ 框架按受控理由拒了这次调用，工具层却把它记成成功"
     "（判据读结构字段，不读 `data` 的自由文本；码位留空 —— 这一笔只有状态、没有受控码。"
     "有受控码的那一档按码表登记的类目记，例如 `target_not_silent`）"),
)

#: 扩面追加的 11 个角色侧类目 + `tool_refused_controlled`
#: （全部是结构化类目，判据读字段不读文案）。
#: 显式列出而不是拿 `ERROR_CATEGORIES[-11:]` 切片：切片会在有人再追加一类时静默变形，
#: 而这张表是"哪些类目不参与文案匹配"的唯一依据。
EXPANDED_ROLE_CATEGORIES: frozenset[str] = frozenset({
    "roster_write_refused", "tool_refused_path", "tool_refused_reserved",
    "tool_refused_edit_window", "experiment_failed", "experiment_refused",
    "reply_shape_rejected", "child_cut_off", "verdict_missing",
    "verdict_understated", "proof_defect_found", "tool_refused_controlled",
})

#: 系统侧类目：这些不是"哪个角色做错了"，是"系统哪里坏了"。它们不进
#: `by_role` / `role_total` / `total`，单独进 `system` 桶。为什么不混进去：把"谁做错了"
#: 与"系统哪里坏了"加起来的那个数没有名字（与 process 分桶同一个理由）。
SYSTEM_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("external_unavailable",
     "外部面掉了：检索 provider 每一路都失败（ProviderError / HTTP 429）⇒ 这一次没有查成"
     "（不是'没有结果'；两者在读数上必须分得开，否则'查无此文'会被它顶掉）"),
    ("hook_undecided",
     "hook 没判成：`fail_open=True` 或秘书 `decision=判不了` ⇒ 判据自己没给出结论"
     "（fail-open 是设计好的降级，但它必须看得见：看不见就等于'判过了、没事'）"),
    ("closing_blocker",
     "收工门拦下：`closing.check_closing` 的 blocker 逐条（如 `contradiction_disputed_source` / "
     "`acceptance_missing_for_research`）⇒ 这一趟交不出去（判据与 Acceptance 页同一处，不另算）"),
)

#: 状态读数类目：它是快照（"现在积着什么"），不是"发生过几次" —— 所以既不进
#: `total` 也不进 `system`，单独一栏，并且会随 ack 回落。
STATE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("item_not_acked",
     "板项没被 ack：`item_state ∈ {seen, queued}` 且不是停机通知 ⇒ 通知发了没人收口"
     "（`seen` = 读进提示词了、缺那个 ack；`queued` = 连读都没读到。停机相关的几类不算："
     "82 的 17 条里有 4 条是停止通知 / 用户叫停，那是叫停的下游形态）"),
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
    # ---- 扩面加的两条：它们都是"发生了、但不是错误动作"，
    # 与 `direct_write_routed`（转交办成）同一手法 —— 办成了 / 叫停了都不进错误表，
    # 但必须有一个地方能看见它，否则"没有错误"与"没有人干活"分不开。
    ("task_stopped",
     "被叫停：`tasks.outcome == cancelled` 且 `runs/stop-history.jsonl` 里有 `by=user` 的"
     "停机记录（过程读数，不计错；82 是 11 条，全部有停机记录解释。没有解释的那些才算可疑，"
     "所以 `sources.stop_history.unexplained` 单独给一个数）"),
    ("roster_repaired",
     "名册自愈补登记：收口兜底 `Secretary.roster_repair` 把漏登记的号补上（过程读数，不计错；"
     "判据读 `out/roster/*.jsonl` 的 `repaired=True`。82 是 2 条，恰好对应 2 条写口拒绝）"),
)

#: 全部类目（错误 ＋ 系统侧 ＋ 状态读数 ＋ 过程读数）。`primary_code` 的优先级按这一张表
#: 的顺序取：错误类目全排在前面 —— 于是"同一段文字既像过程读数又像错误"时算错误那一档
#: （宁严不宽）。系统侧 / 状态读数排在错误之后：它们不进 `_MATCH_ORDER`（见下一条）。
ALL_CATEGORIES: tuple[tuple[str, str], ...] = (
    ERROR_CATEGORIES + SYSTEM_CATEGORIES + STATE_CATEGORIES + PROCESS_CATEGORIES)

#: 哪些类目算"角色侧错误动作"（计入 `total` / `role_total`）。分桶只认这一张表，不认调用点。
ERROR_CATEGORY_NAMES: frozenset[str] = frozenset(cat for cat, _why in ERROR_CATEGORIES)

#: 哪些类目是系统侧（进 `system` 桶，不进角色合计）。
SYSTEM_CATEGORY_NAMES: frozenset[str] = frozenset(cat for cat, _why in SYSTEM_CATEGORIES)

#: 哪些类目是状态读数（进 `state_readings`，是快照、不进任何总数）。
STATE_CATEGORY_NAMES: frozenset[str] = frozenset(cat for cat, _why in STATE_CATEGORIES)

#: 哪些类目是过程读数（不计错，单独一栏）。
PROCESS_CATEGORY_NAMES: frozenset[str] = frozenset(cat for cat, _why in PROCESS_CATEGORIES)

#: 结构化类目：它们的判据只读字段，不进 `_MATCH_ORDER`（模块 docstring 第一节）。
#: 为什么必须显式排除：三条假阳性 ——
#: ① `warn` 里的多调用汇总逐条复述"第 2 条 fs.read 被拒：. 是目录"，按文案数会把一次
#:    被拒的调用数成两次（与 D-65 正面冲突）；
#: ② `item_state` 这个词在 `table.describe` 的输出里满天飞，按文案数会把"打印了一张表结构"
#:    数成"有一条板项没被 ack"；
#: ③ `ProviderError` / `有毛病` 这类词在 payload 与 result.data 里出现，而它们不是"撞上"。
#: 所以这 15 类一律由读侧的显式函数产出（`_tool_refusal_family` 等），一个都不靠找字。
STRUCTURAL_ONLY_CATEGORIES: frozenset[str] = frozenset(
    EXPANDED_ROLE_CATEGORIES | SYSTEM_CATEGORY_NAMES | STATE_CATEGORY_NAMES)

#: 六档归属（模块 docstring 第三节）。顺序就是 `attribution_of` 的判定顺序。
ATTRIBUTION_BUCKETS: tuple[tuple[str, str], ...] = (
    ("actor", "动作方：这条记录就是它自己的动作回执（默认档）"),
    ("caller", "发起方：结构判据说这次派活 / 这次送审派错了"),
    ("author", "命题作者：证明本身有毛病 ⇒ 记写出这条证明的那一方（不是复核者 V）"),
    ("recipient", "收件人：板项没被 ack ⇒ 记该 ack 的那一方（不是发送方）"),
    ("roster", "名册发起方：写口拒了一个名字 ⇒ 记要这个名字的那一方"),
    ("system", "系统侧：判据没判成 / 外部面掉了 / 收工门拦下 ⇒ 不进角色合计"),
)

#: 记 `called_by` 的类目（码那一档仍用 `CALLER_ATTRIBUTED_CODES`，两处并存：
#: 老类目按码分，新类目按类目分 —— 因为新类目根本不是靠码命中的）。
CALLER_ATTRIBUTED_CATEGORIES: frozenset[str] = frozenset({
    "child_cut_off", "verdict_missing",
})

#: 记命题作者（`statements.proof_authors` → `created_by`）的类目。
AUTHOR_ATTRIBUTED_CATEGORIES: frozenset[str] = frozenset({"proof_defect_found"})

#: 记名册发起方（`owner` 那一行的 `role`）的类目。
ROSTER_ATTRIBUTED_CATEGORIES: frozenset[str] = frozenset({"roster_write_refused"})

#: 系统侧那一档的"角色"名。它不是一个角色（`schema.ROLES` 里没有），所以
#: `_known_role` 对它一律回 False —— 于是它永远不会被当成 `called_by` 命中。
SYSTEM_ACTOR = "（系统）"

#: 命题作者查不到时的名字（与 `UNKNOWN_ROLE` 同一条纪律：不猜）。
UNKNOWN_AUTHOR = "（未记作者）"

#: 每一类留几条明细样本（页面"展开到每条的 source"那一栏）。刻意不是全部：
#: 这一栏回答"这一类的一条长什么样、去哪个文件哪一条看"，不是把台账搬进 JSON。
_SAMPLE_CAP = 20


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

#: 码 → 类目 → 出处。出处写的是符号名（`src/agentflow/x.py::函数或常量`），不是行号。
#:
#: 为什么不再写行号（`R-BE4`，业主批准）：行号在并行开发下几十分钟就漂，而没有任何判据
#: 会红 —— "出处"于是变成一句没人验的空话。口径改成符号名之后，判据
#: `tests/test_errorstats_provenance_symbols_exist.py` 可以逐条断言
#: "那个符号真的在那个文件里"（与 `.noai-paths` / `AGENTS.md` 的同一条纪律：
#: 理由里写符号名，行号易失）。
CODE_TABLE: tuple[tuple[str, str, str], ...] = (
    # ---- 结构性拒绝
    ("forbidden_edge", "forbidden_edge",
     "src/agentflow/schema.py::REFUSAL_REASONS（词表）/ src/agentflow/policy.py::check（产出）"),
    ("not_in_roster", "not_in_roster",
     "src/agentflow/agent_loop.py::_refusal_key（roster_probe 的受控拒绝码）"),
    ("不在你的名册里", "not_in_roster",
     "src/agentflow/agent_loop.py::roster_addresses（roster_probe 的拒信原文）"),
    ("unknown_tool", "unknown_tool", "src/agentflow/tools/base.py::ToolRegistry.get（kind）"),
    ("没有名为", "unknown_tool", "src/agentflow/tools/base.py::ToolRegistry.get（ToolError 原文）"),
    ("unknown_action", "unknown_tool",
     "src/agentflow/schema.py::REFUSAL_REASONS（词表）/ src/agentflow/policy.py::check_action（产出）"),
    ("unknown_role", "unknown_tool",
     "src/agentflow/schema.py::REFUSAL_REASONS（词表）/ src/agentflow/policy.py::check_action（产出）"),
    ("direct_write_refused", "direct_write", "src/agentflow/store.py::DIRECT_WRITE_REFUSED（常量定义点；拒信由 `direct_write_refusal()` 拼）"),
    # ---- 时钟的两条"前置条件不成立"
    #
    # 归 `not_in_roster`：`waiter_not_resolvable` 的语义就是"这一句 wait_for 在名册
    # （或程序簿记）里解析不到唯一一台账号"—— 与"不在你的名册里"是同一类东西，
    # 只是被拒的是"等"而不是"说"。单独成码是为了让"散文式 wait_for 又出现了"
    # 在读数上数得出来。
    ("waiter_not_resolvable", "not_in_roster",
     "src/agentflow/clock.py::WAITER_NOT_RESOLVABLE（WAITER_NOT_RESOLVABLE / `_new_timer` 的等谁核对；"
     "拒信由 `waiter_refusal()` 拼）"),
    # 归 `controlled_refusal`：它不是"没查成"也不是"查无此人"，是"现在没有可等的东西"
    # （业主：「这个需要存在的计时器数大于等于1」）。与 `invalid_params` 同族：这次调用
    # 不成立，重写一次就能过（先起一条表，或按交差收工）。
    ("no_timers_to_wait", "controlled_refusal",
     "src/agentflow/clock.py::no_timers_refusal（NO_TIMERS_TO_WAIT / `request_wait_any` 的前置判据；"
     "拒信由 `no_timers_refusal()` 拼）"),
    # ---- 直写兜底（口径：「不应该是提醒智能体要走秘书，而是自动将直写请求路由到
    # 秘书接管」）。路由不再计入 `direct_write`：那一档只留"兜底方也接不住"的野路。
    # 结局码逐条登记在 `ROUTED_CODES`（字面量），拼装只允许拼出那张表里的东西。
    # 与 multi_call 同一手法：办成的两档进过程读数 `direct_write_routed`
    # —— "系统替模型办成了"不是错误动作；只有拒的 / 不可达的留在错误表上。
    ("routed_to_backstop.secretary", "direct_write_routed",
     "src/agentflow/tools/table_tools.py::ROUTED_CODES（登记表；拼装见 `_route_code`）"),
    ("routed_to_backstop.literal", "direct_write_routed",
     "src/agentflow/tools/table_tools.py::ROUTED_CODES（登记表；拼装见 `_route_code`）"),
    ("routed_to_backstop.secretary_refused", "routed_to_backstop",
     "src/agentflow/tools/table_tools.py::ROUTED_CODES（ROUTED_CODES；兜底方拒，原话见 refused_by_backstop）"),
    ("routed_to_backstop.literal_refused", "routed_to_backstop",
     "src/agentflow/tools/table_tools.py::ROUTED_CODES（ROUTED_CODES；兜底方拒，原话见 refused_by_backstop）"),
    ("routed_to_backstop.secretary_unavailable", "routed_to_backstop",
     "src/agentflow/tools/table_tools.py::ROUTED_CODES（ROUTED_CODES；兜底方不可达 ⇒ unknown，不折成成功）"),
    ("routed_to_backstop.literal_unavailable", "routed_to_backstop",
     "src/agentflow/tools/table_tools.py::ROUTED_CODES（ROUTED_CODES；同上）"),
    ("role_denied", "readonly_role_write",
     "src/agentflow/tools/base.py::ToolRegistry.call（call 的调用期角色判据）"),
    ("not_wired", "not_wired",
     "src/agentflow/schema.py::REFUSAL_REASONS（词表）/ src/agentflow/conductor.py::LocalBackend（产出）"),
    ("depth_exceeded", "capacity_refused", "src/agentflow/schema.py::REFUSAL_REASONS / src/agentflow/policy.py::check"),
    ("fanout_exceeded", "capacity_refused", "src/agentflow/schema.py::REFUSAL_REASONS / src/agentflow/policy.py::check"),
    ("concurrency_exceeded", "capacity_refused",
     "src/agentflow/schema.py::REFUSAL_REASONS / src/agentflow/policy.py::check"),
    ("budget_exceeded", "capacity_refused",
     "src/agentflow/schema.py::REFUSAL_REASONS / src/agentflow/policy.py::check"),
    ("deadline_exceeded", "capacity_refused",
     "src/agentflow/schema.py::REFUSAL_REASONS / src/agentflow/policy.py::check"),
    ("cycle_detected", "capacity_refused", "src/agentflow/schema.py::REFUSAL_REASONS / src/agentflow/policy.py::check"),
    # ---- 写入期判据
    ("行校验失败", "schema_invalid", "src/agentflow/tools/table_tools.py::_build_row（ToolError 原文）"),
    ("缺少必填参数", "param_invalid", "src/agentflow/tools/base.py::validate_params（ParamError 原文）"),
    ("参数错误：", "param_invalid", "src/agentflow/tools/base.py::ToolRegistry.call（ToolResult.fail 原文）"),
    ("param_error", "param_invalid", "src/agentflow/tools/base.py::ToolRegistry.call（kind）"),
    # 模型按前缀直觉手填了本该由台账分配的主键
    # （`rel-000001` / `stmt-1` / `p-000001`）。归 `param_invalid`：这次调用不成立的原因是
    # "多给了一格本不该给的参数"，不是行内容不合法。单独成码是为了让"同一个坑连踩几次"
    # 在读数上数得出来 —— 折进 `param_error` 就数不出来了。
    ("hand_filled_id", "param_invalid",
     "src/agentflow/tools/table_tools.py::_hand_typed_id_refusal（kind；判据 `_hand_typed_id_refusal`）"),
    ("missing_source", "param_invalid", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("missing_own_source", "param_invalid", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("missing_quote_reason", "param_invalid", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("missing_page_range", "param_invalid", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("duplicate_doi", "duplicate_conflict",
     "src/agentflow/schema.py::CANDIDATE_REASON_CODES（词表）/ src/agentflow/litstage.py::admission_plan（产出）"),
    ("duplicate_statement", "duplicate_conflict", "src/agentflow/agent_b/register_statement.py::_RegisterStatement._attach_proofs"),
    ("duplicate_paper_number", "duplicate_conflict", "src/agentflow/paperledger.py::check_paper_ledger"),
    ("duplicate_claim_id", "duplicate_conflict", "src/agentflow/claimanatomy.py::validate_document_claims"),
    ("duplicate_id", "duplicate_conflict", "src/agentflow/verify.py::_check_1"),
    ("invalid_params", "controlled_refusal", "src/agentflow/schema.py::REFUSAL_REASONS（词表）/ src/agentflow/refusals.py::PRECONDITION_REASON"),
    # ---- 空正文的两档（裁定 B2 的第 1 条）：写侧与判档位那一侧共用一个字面量
    # （真身在 `refusals.py`）。`bad_statement` 是它们的前身："0 字"与"只有短版"混在
    # 那一个码里，于是同一种输入在写侧与判档位侧拿到两个名字。
    ("empty_statement_text", "controlled_refusal",
     "src/agentflow/refusals.py::EMPTY_STATEMENT_TEXT（真身）/ src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement（写侧产出）"
     " / src/agentflow/secretary.py::Secretary.judge_statement（判档位那一侧的受控拒绝）"),
    ("empty_proof_text", "controlled_refusal",
     "src/agentflow/refusals.py::EMPTY_PROOF_TEXT（真身）/ "
     "src/agentflow/agent_b/register_statement.py::_RegisterStatement._attach_proofs"
     "（两个写入口；那里引用的是常量 `_R.EMPTY_PROOF_TEXT`，不是码的字面量）"),
    ("bad_statement", "controlled_refusal", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("bad_origin", "controlled_refusal", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("bad_evidence_kind", "controlled_refusal", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("bad_id", "controlled_refusal", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("bad_line_range", "controlled_refusal", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("bad_page_range", "controlled_refusal", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("proofs_not_attached", "controlled_refusal",
     "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("proof_needs_third_party_signature", "controlled_refusal",
     "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    ("canonical_not_written", "controlled_refusal", "src/agentflow/agent_b/register_statement.py::_RegisterStatement._attach_proofs"),
    ("secretary_unavailable", "controlled_refusal", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    # ---- 判据层
    ("judge_bad_json", "judge_bad_json", "src/agentflow/judge.py::JUDGE_PROBLEMS（problem 码）"),
    # 原生工具调用面里"点了一个没广告过的函数名"折成 `judge_bad_json`
    # （`llmseam.ToolFace.to_shape`），而文本协议下同一个动作记的是 `unknown_tool` ——
    # 同一件事两个类目，于是"名字不存在"这一类在两种协议下各数一半。现在它归到一个类目
    # （`unknown_tool`：名字不存在），码保留判据层自己的名字 —— 与 `judge_not_wired`
    # 归 `not_wired` 是同一手法：码说"哪一层看出来的"，类目说"这是个什么错"。
    # `judge_bad_json` 从此只留给"真的不是 JSON"。
    ("judge_unknown_tool", "unknown_tool",
     "src/agentflow/judge.py::JUDGE_PROBLEMS（词表）/ src/agentflow/llmseam.py::ToolFace.to_shape（产出：没广告过的函数名）"),
    ("judge_bad_args", "judge_bad_args", "src/agentflow/agent_loop.py::_invalid_correction"),
    ("judge_no_reply:", "judge_no_reply", "src/agentflow/agent_loop.py::_is_no_reply（带后缀那一族）"),
    ("judge_timeout", "judge_no_reply", "src/agentflow/agent_loop.py::_NO_REPLY_NAMED（_NO_REPLY_NAMED）"),
    ("judge_output_limit", "judge_no_reply", "src/agentflow/agent_loop.py::_NO_REPLY_NAMED"),
    ("judge_failed:", "judge_failed", "src/agentflow/agent_loop.py::LoopRun（真机 judge_failed:ModelReplyNotOk）"),
    ("judge_not_wired", "not_wired", "src/agentflow/judge.py::JUDGE_PROBLEMS（没接线那一档）"),
    # 拆分口径（D-65：multi_call 不是错误）：
    # 一步给多条调用是正常能力，所以这一步的读数进过程读数表：
    #   `steps_split` 数被拆分的步数 —— 它从 `result` 里的结构字段取（键名就是
    #   `multi_call`，`agent_loop` 写在回合的每一条上，取 `call_index == 0` 的那一条）；
    #   注意 `multi_call` 在这里是结构字段名，不是类目名（类目名是 `steps_split`）。
    #   `multi_call_executed_calls` 数真的执行了的条目（逐条记录 `agent_step_call`）。
    # 真的做错了才进错误类目：丢了几条 / 没执行成 / 超上限（下面那五行）。
    ("multi_call", "steps_split",
     "src/agentflow/agent_loop.py::AgentLoop.run（`result` 里的结构字段名，一个回合一条）"),
    ("agent_step_call", "multi_call_executed_calls",
     "src/agentflow/stepdispatch.py::STEP_CALL_EVENT（STEP_CALL_EVENT 的定义）"),
    ("未执行（解码不出", "multi_call_discarded",
     "src/agentflow/agent_loop.py::AgentLoop._record_undecodable_item（_record_undecodable_item 的结局原话）"),
    ("这一条解码不出来", "multi_call_discarded",
     "src/agentflow/stepdispatch.py::StepDispatch.mark_not_executed（mark_not_executed 对解码不出那一档的原话）"),
    ("因本回合已收工未执行", "multi_call_unexecuted",
     "src/agentflow/stepdispatch.py::StepDispatch.mark_not_executed（mark_not_executed 的收工那一档）"),
    ("因预算未执行", "multi_call_out_of_limit",
     "src/agentflow/stepdispatch.py::StepDispatch.mark_not_executed（mark_not_executed 的预算那一档）"),
    ("not_executed", "multi_call_unexecuted",
     "src/agentflow/stepdispatch.py::StepDispatch.mark_not_executed（mark_not_executed 的定义；没写理由时的兜底码）"),
    ("run_evidence_unreadable", "unreadable", "src/agentflow/closing.py::RUN_EVIDENCE_UNREADABLE_CODE（RUN_EVIDENCE_UNREADABLE_CODE）"),
    ("context_graph_unreadable", "unreadable", "src/agentflow/agent_b/register_statement.py::_RegisterStatement.register_statement"),
    # ---- 流程层
    ("mapping_not_written", "closing_blocked", "src/agentflow/closing.py::_check_mapping（MAPPING_NOT_WRITTEN_CODE）"),
    ("run_evidence_unbacked", "closing_blocked", "src/agentflow/closing.py::RUN_EVIDENCE_UNBACKED_CODE（RUN_EVIDENCE_UNBACKED_CODE）"),
    ("quote_verified_without_span", "closing_blocked", "src/agentflow/closing.py::check_closing（收工门 quote_evidence 格）"),
    ("mapping_orphan", "paper_mapping_gap", "src/agentflow/papermapping.py::MAPPING_KINDS"),
    ("mapping_file_missing", "paper_mapping_gap", "src/agentflow/papermapping.py::MAPPING_KINDS"),
    ("mapping_unresolvable", "paper_mapping_gap", "src/agentflow/papermapping.py::MAPPING_KINDS"),
    ("mapping_citation_loc_missing", "paper_mapping_gap", "src/agentflow/papermapping.py::CITATION_KINDS"),
    ("mapping_citation_file_missing", "paper_mapping_gap", "src/agentflow/papermapping.py::CITATION_KINDS"),
    ("mapping_proof_program_missing", "paper_mapping_gap", "src/agentflow/papermapping.py::_numeric_problems"),
    ("mapping_package_missing", "paper_mapping_gap", "src/agentflow/papermapping.py::PAPER_KINDS"),
    ("mapping_lean_missing", "paper_mapping_gap", "src/agentflow/papermapping.py::LEAN_KINDS"),
    ("请代唤", "relay_after_refusal", "src/agentflow/agent_loop.py::RELAY_SUBJECT（RELAY_SUBJECT）"),
    # ---- 扩面的 15 类（出处一律写符号名，不写行号）。
    #
    # 这些码不进 `_MATCH_ORDER`（`STRUCTURAL_ONLY_CATEGORIES`）：它们的码登记在这里是
    # 为了两件事 —— ① 判据 `test_every_category_has_a_code_that_really_exists_in_the_source`
    # 能逐条断言"这个码真的在源码里"；② 人读出处时知道去哪一格看。判定本身读字段，
    # 不找字（理由见模块 docstring 第一节的三条假阳性）。
    ("name_taken", "roster_write_refused",
     "src/agentflow/secretary.py::refusals_path（写口拒绝流水；`name_taken` 由 roster_add 产出）"),
    ("文件不存在：", "tool_refused_path",
     "src/agentflow/tools/fs_tools.py::fs_read（ToolError 原文）"),
    ("路径不存在：", "tool_refused_path",
     "src/agentflow/tools/fs_tools.py::fs_list（ToolError 原文）"),
    ("是目录（要列出内容请用", "tool_refused_path",
     "src/agentflow/tools/fs_tools.py::fs_read（ToolError 原文）"),
    ("没有全文路径", "tool_refused_path",
     "src/agentflow/tools/ocr_tools.py::_target_path（前置条件拒信原文）"),
    ("框架渲染的产物", "tool_refused_reserved",
     "src/agentflow/tools/fs_tools.py::fs_write（保留产物闸的原话）"),
    ("单次定点替换上限", "tool_refused_edit_window",
     "src/agentflow/tools/fs_tools.py::fs_edit（MAX_EDIT_BYTES 那一档的拒信原文）"),
    ("old_string 在", "tool_refused_edit_window",
     "src/agentflow/tools/fs_tools.py::fs_edit（找不到 / 出现多次两档的拒信原文）"),
    ("实验执行失败", "experiment_failed",
     "src/agentflow/tools/verify_tools.py::register._run_experiment_tool"
     "（ExperimentError 的包装原话）"),
    ("跑脚本之前", "experiment_refused",
     "src/agentflow/agent_e/run_experiment.py::_RunExperiment.run_experiment"
     "（R-01 的跑前判据原话）"),
    ("一次只能说一件事", "reply_shape_rejected",
     "src/agentflow/agent_loop.py::_decode_shape（一回合给两件事的拒信原话）"),
    ("攻坚计划被拒绝", "reply_shape_rejected",
     "src/agentflow/tools/attack_tools.py::_guard（计划结构缺字段的拒信原文）"),
    ("cut_off_by_parent", "child_cut_off",
     "src/agentflow/schema.py::TASK_OUTCOMES（父退场结算写下的终态）"),
    ("statement_missing", "verdict_missing",
     "src/agentflow/agent_v/core.py::AgentV.verify_proof"
     "（`kind=statement_missing`：没审、不留台账行）"),
    ("有缺陷要指出", "verdict_understated",
     "src/agentflow/secretary.py::Secretary.note_decision"
     "（`target.judge=v_reply_defect` 的判词档）"),
    ("有毛病", "proof_defect_found",
     "src/agentflow/verifications.py::VERDICTS（两态判词之一；行上 `unresolved_errors` 同族）"),
    ("ProviderError", "external_unavailable",
     "src/agentflow/providers.py::ProviderError（检索 provider 每一路都失败时抛的那一个）"),
    ("fail_open", "hook_undecided",
     "src/agentflow/secretary.py::Secretary.note_decision"
     "（`fail_open` 那一格的唯一写点；hook 没判成 / 收录前判档炸了都经它留痕）"),
    ("判不了", "hook_undecided",
     "src/agentflow/secretary.py::Secretary.note_decision（`decision=判不了` 那一档）"),
    ("contradiction_disputed_source", "closing_blocker",
     "src/agentflow/closing.py::_check_contradictions（blocker 的 code）"),
    ("acceptance_missing_for_research", "closing_blocker",
     "src/agentflow/closing.py::_check_acceptance（blocker 的 code）"),
    # 状态读数：`item_state` 是结构字段名（与 `multi_call` 那一行的用法同形 ——
    # 码这一格记的是"判据读的那一格的字段名"，不是一段会被扫到的文案）。
    ("item_state", "item_not_acked",
     "src/agentflow/schema.py::Task.item_state（`seen` = 读了没 ack；`queued` = 连读都没读到）"),
    # 过程读数那两格：`cancelled` 是 `TASK_OUTCOMES` 里的终态，算不算错由停机流水决定；
    # `repaired` 是自愈补登记行的标记（与 `direct_write_routed` 同一手法：办成了不算错）。
    ("cancelled", "task_stopped",
     "src/agentflow/schema.py::TASK_OUTCOMES（被叫停的终态；算不算错看 runs/stop-history.jsonl）"),
    ("repaired", "roster_repaired",
     "src/agentflow/secretary.py::Secretary.roster_repair（补登记行的标记）"),
    # ---- 12 个「模型面拒因码」（受控拒绝的码）。
    #
    # 它们都是"框架按受控理由拒了模型这一次操作"的码：有的写在工具结果的
    # `data.refusal_code` 里（`target_not_silent`），有的写在写入口的结论里
    # （`proof_review_without_evidence`），有的写在词表里（`formal_moved_to_l`）。
    # 统一归 `tool_refused_controlled`：与"参数形状坏"（`param_invalid`）分开 ——
    # 那两件事混在一个类目里，参数错误那一族的读数就会说谎。
    #
    # 码名一个都不新造：这里只登记已经在源码里产出的那些字面量（判据走 AST 核
    # 字面量与符号，注释里提过不算）。出处仍写符号名，不写行号。
    ("target_not_silent", "tool_refused_controlled",
     "src/agentflow/conductor.py::RETIRE_REFUSAL_TARGET_NOT_SILENT"
     "（`retire_refusal` 的码；工具层把它写进 `data.refusal_code`）"),
    ("not_yours", "tool_refused_controlled",
     "src/agentflow/conductor.py::Conductor.ack_items"
     "（别人的板项 ⇒ 逐条 `code=\"not_yours\"`；`conductor.ack` 的工具结果里）"),
    ("not_mine", "tool_refused_controlled",
     "src/agentflow/agent_loop.py::AgentLoop._do_interrupt（打断别人那一档的受控码）"),
    ("not_conductor", "tool_refused_controlled",
     "src/agentflow/userio.py::ASK_NOT_CONDUCTOR（非主控提未决问题 ⇒ 挡回）"),
    ("not_caller", "tool_refused_controlled",
     "src/agentflow/conductor.py::Conductor.escalate（没有召唤者的顶层调用）"),
    ("public_is_not_a_conversation", "tool_refused_controlled",
     "src/agentflow/agent_loop.py::AgentLoop._public_face_refusal"
     "（公告栏点名某个代理 ⇒ 那不是一次对话）"),
    ("formal_moved_to_l", "tool_refused_controlled",
     "src/agentflow/agent_e/_support.py::FORMAL_REASONS"
     "（历史理由码；E 不再产出它，但词表里留着，历史台账仍带着）"),
    ("formal_not_in_e", "tool_refused_controlled",
     "src/agentflow/agent_e/_support.py::E_NO_FORMAL_REASON"
     "（E 的动作面拒绝 `method=\"formal\"` 的唯一字面量）"),
    ("missing_relevance", "tool_refused_controlled",
     "src/agentflow/litstage.py::admission_plan"
     "（这一条没写「为什么与本次检索相关」⇒ 逐条拒收）"),
    ("dependency_section_missing", "tool_refused_controlled",
     "src/agentflow/depsection.py::REFUSED_SECTION_MISSING"
     "（手稿没有 `## 依赖` 段而正文引用了在册命题 ⇒ 整笔拒收）"),
    ("dependency_section_unreadable", "tool_refused_controlled",
     "src/agentflow/depsection.py::REFUSED_SECTION（依赖段解析失败 ⇒ 整笔拒收）"),
    ("proof_review_without_evidence", "tool_refused_controlled",
     "src/agentflow/verifications.py::CODE_WRITE"
     "（写入期闸：声称 `proof_review` 却没有证据 ⇒ 当场拒收）"),
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
#:
#: `STRUCTURAL_ONLY_CATEGORIES` 那一批不进来（模块 docstring 第一节）。
#: 它们由读侧的显式函数产出，一个都不靠找字 —— 所以这里过滤掉之后，`primary_code`
#: 的行为与不加这些类目时逐字相同（老的六个例子仍然逐条成立）。
_MATCH_ORDER: tuple[tuple[str, str], ...] = tuple(
    (code, cat)
    for code, cat, _where in sorted(
        (row for row in CODE_TABLE if row[1] not in STRUCTURAL_ONLY_CATEGORIES),
        key=lambda t: (_CATEGORY_INDEX[t[1]], -len(t[0]), _CODE_INDEX[t[0]]))
)

#: 事件流里带拒绝语义的两档 `tasks.outcome`。
_REFUSAL_OUTCOME = "refused"
_FAILED_OUTCOME = "failed"

#: 父退场结算写下的终态（`schema.TASK_OUTCOMES` 之一）：孩子还在跑、父先退了。
_CUT_OFF_OUTCOME = "cut_off_by_parent"

#: 被叫停的终态。它算不算错先看停机流水（模块 docstring 第五节）。
_CANCELLED_OUTCOME = "cancelled"

#: 板项（`kind` 非空）的那两个词（`schema`：`message` 一条消息 / `notice` 一条通知）。
_BOARD_KINDS: frozenset[str] = frozenset({"notice", "message"})

#: 停机相关的板项：它们没被 ack 是"叫停的下游形态"，不算"通知发了没人收口"。
#: 判据是 detail 的开头（两句都是框架自己写的固定前缀，不是模型的话）。
_STOP_ITEM_PREFIXES: tuple[str, ...] = ("停止通知", "用户叫停（开关文件")


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


def attribution_of(code: str, category: str) -> str:
    """这一条该记谁：返回 `ATTRIBUTION_BUCKETS` 里的一个档名。

    判定顺序就是本函数的分支顺序，理由逐条：

    1. `system` 先判：系统侧类目（`SYSTEM_CATEGORIES`）的 "角色" 永远是 `SYSTEM_ACTOR`，
       这一点不受别的规则影响 —— 若放到后面，一个凑巧在 `CALLER_ATTRIBUTED_CODES` 里的码
       会把它拖进角色表；
    2. 状态读数（`STATE_CATEGORIES`）记收件人：板项行的 `role` 就是收件人
       （`parent_task_id` 那一方），记录里已经没有"动作方"这一档了；
    3. 名册类记发起方：`owner` 那一行的 `role`；
    4. 证明缺陷记作者：`proof_authors` → `created_by`；
    5. 新类里那两个"送审派错了 / 父先退了"记 `called_by`；
    6. 老类目按码分（`CALLER_ATTRIBUTED_CODES`），其余是 `actor`。

    为什么不让调用点自己决定档位：档位是类目的属性（"证明有毛病"永远该记作者，
    与它在哪张表里被读出来无关）。放调用点上，第二个读同一件事的人一定会写错。
    """
    if category in SYSTEM_CATEGORY_NAMES:
        return "system"
    if category in STATE_CATEGORY_NAMES:
        return "recipient"
    if category in ROSTER_ATTRIBUTED_CATEGORIES:
        return "roster"
    if category in AUTHOR_ATTRIBUTED_CATEGORIES:
        return "author"
    if category in CALLER_ATTRIBUTED_CATEGORIES:
        return "caller"
    if code in CALLER_ATTRIBUTED_CODES:
        return "caller"
    return "actor"


# ---------------------------------------------------------------- 结果形状


def _error_category(category: str) -> str:
    """确认这是一个角色侧错误类目，原样返回；传过程读数 / 系统侧 / 状态读数就抛。

    为什么抛而不是回 0：0 会把"这不是一个角色侧类目"读成"这一类没有"，而这两件事的处置
    完全不同（前者是口径错用，后者是读数）。同一个理由见模块 docstring 的三态那一条。
    系统侧与状态读数各有自己的取数函数（`system_category_total` / `state_category_total`），
    因为它们不进 `total`（模块 docstring 第二节）。
    """
    if category in PROCESS_CATEGORY_NAMES:
        raise ValueError(
            f"{category} 是过程读数（拆分），不是错误类目 —— 请用 process_category_total / "
            "process_count；它不进 total 是有意的（业主 D-65）")
    if category in SYSTEM_CATEGORY_NAMES:
        raise ValueError(
            f"{category} 是系统侧类目（不进角色合计）—— 请用 system_category_total / "
            "system_count；它不进 total 是有意的：把'谁做错了'与'系统哪里坏了'相加得不到"
            "任何一个有名字的量（模块 docstring 第二节）")
    if category in STATE_CATEGORY_NAMES:
        raise ValueError(
            f"{category} 是状态读数（快照，会回落）—— 请用 state_category_total；"
            "它既不进 total 也不进 system（模块 docstring 第二节）")
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
    #: 系统侧：类目 → 条数（不进 `by_role` / `total`，见模块 docstring 第二节）。
    system: dict[str, int] = field(default_factory=dict)
    system_total: int = 0
    #: 状态读数：角色 → 类目 → 条数（快照；不进任何总数）。
    state_readings: dict[str, dict[str, int]] = field(default_factory=dict)
    state_readings_total: int = 0
    #: 类目 → 三态（`checked` / `state` / `reason` / `rows`）。新 15 类每一类都有自己的三态：
    #: 一个源读不到时只有那一类变 `unknown`，不许把整页拖成 0，也不许把 0 当成读数。
    class_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: 类目 → 前 `_SAMPLE_CAP` 条明细（`{role, code, source, ref, ts, detail}`）。
    #: 页面"展开到每条的 source"靠它；计数与它无关（样本只为看一条长什么样）。
    samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: 类目 → `{first, last, this_run, earlier, no_ts}`（时间那一栏：首条 / 末条 /
    #: 这一趟几条 / 更早几条 / 没记时间的几条）。
    spans: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: "这一趟"的边界（最后一处 `agent_run_start` 的 ts）。空串 = 边界读不到。
    run_boundary: str = ""
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

    def system_count(self, category: str) -> int:
        """某系统侧类目的条数（不进角色合计）。"""
        if category not in SYSTEM_CATEGORY_NAMES:
            raise ValueError(f"{category} 不是系统侧类目 —— 系统侧见 SYSTEM_CATEGORIES")
        return int(self.system.get(category, 0))

    def state_category_total(self, category: str) -> int:
        """某状态读数类目的全角色合计（快照，不进任何总数）。"""
        if category not in STATE_CATEGORY_NAMES:
            raise ValueError(f"{category} 不是状态读数类目 —— 见 STATE_CATEGORIES")
        return sum(int(c.get(category, 0)) for c in self.state_readings.values())

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

    def system_categories(self) -> dict[str, int]:
        """系统侧类目 → 条数（按 `SYSTEM_CATEGORIES` 的顺序，只留非 0 的）。"""
        return {cat: int(self.system.get(cat, 0)) for cat, _why in SYSTEM_CATEGORIES
                if int(self.system.get(cat, 0))}

    def state_categories(self) -> dict[str, int]:
        """状态读数类目 → 条数（按 `STATE_CATEGORIES` 的顺序，只留非 0 的）。"""
        out: dict[str, int] = {}
        for cat, _why in STATE_CATEGORIES:
            n = self.state_category_total(cat)
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

    def by_class(self) -> list[dict[str, Any]]:
        """按类的一行一条（页面"按类"那一段与 CLI 都用这一份）。

        一条 = `{category, bucket, count, meaning, state, checked, reason, by_role}`。
        `bucket ∈ {error, system, state, process}` —— 页面上分栏、排序时也只在自己那一栏
        里排：把三种单位混在一个降序表里，第一条永远是单位最大的那个，读的人会以为它最严重。

        为什么计数为 0 的类目也出现（而 `categories()` 只留非 0）：这一页的价值是
        "一眼看出哪里在漏"，而"这一类这一趟 0 条"与"这一类根本没接上"必须分得开 ——
        前者是绿，后者是 `unknown`（`state` 那一格）。
        """
        meaning = dict(ALL_CATEGORIES)
        order = ("error", "system", "state", "process")
        rows: list[dict[str, Any]] = []
        for bucket, cats in (("error", ERROR_CATEGORIES), ("system", SYSTEM_CATEGORIES),
                             ("state", STATE_CATEGORIES), ("process", PROCESS_CATEGORIES)):
            for cat, _why in cats:
                if bucket == "system":
                    n = int(self.system.get(cat, 0))
                    per_role = {SYSTEM_ACTOR: n} if n else {}
                else:
                    cells = (self.by_role if bucket == "error"
                             else self.state_readings if bucket == "state"
                             else self.process)
                    per_role = {r: int(c.get(cat, 0)) for r, c in sorted(cells.items())
                                if int(c.get(cat, 0))}
                    n = sum(per_role.values())
                tri = dict(self.class_state.get(cat) or {})
                span = dict(self.spans.get(cat) or {})
                rows.append({"category": cat, "bucket": bucket, "count": int(n),
                             "meaning": meaning.get(cat, ""), "by_role": per_role,
                             "checked": bool(tri.get("checked", self.checked)),
                             "state": str(tri.get("state") or ("checked" if self.checked
                                                               else "unknown")),
                             "reason": str(tri.get("reason") or ""),
                             "first_ts": str(span.get("first") or ""),
                             "last_ts": str(span.get("last") or ""),
                             "this_run": int(span.get("this_run") or 0),
                             "earlier": int(span.get("earlier") or 0),
                             "no_ts": int(span.get("no_ts") or 0),
                             "samples": [dict(s) for s in (self.samples.get(cat) or ())]})
        rows.sort(key=lambda r: (order.index(str(r["bucket"])), -int(r["count"]),
                                 str(r["category"])))
        return rows

    def as_dict(self) -> dict[str, Any]:
        """机器可读形态（CLI 的 `--json` 直接印它）。

        `by_role` / `role_total` / `total` 只含角色侧错误类目；`process` / `process_by_role`
        是过程读数（拆分）；`system` 是系统侧；`state_readings` 是状态读数（快照）。
        四组键刻意不合并：合并之后 `total` 又不等于"错误动作总数"了，而"角色侧 48 /
        系统侧 8 / 状态读数 13"这三个数本来就不该相加（模块 docstring 第二节）。
        """
        return {
            "by_role": {r: dict(sorted(c.items())) for r, c in sorted(self.by_role.items())},
            "role_total": dict(sorted(self.role_total.items())),
            "total": int(self.total),
            "system": dict(sorted(self.system.items())),
            "system_total": int(self.system_total),
            "state_readings": {r: dict(sorted(c.items()))
                               for r, c in sorted(self.state_readings.items())},
            "state_readings_total": int(self.state_readings_total),
            "process_by_role": {r: dict(sorted(c.items()))
                                for r, c in sorted(self.process.items())},
            "process": dict(self.process_categories()),
            "classes": self.by_class(),
            "class_state": {k: dict(v) for k, v in sorted(self.class_state.items())},
            "samples": {k: [dict(s) for s in v] for k, v in sorted(self.samples.items())},
            "spans": {k: dict(v) for k, v in sorted(self.spans.items())},
            "run_boundary": self.run_boundary,
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
    """读会话记录 —— 转发 `sessions.read_all_sessions`（真身在那里）。

    这一支曾经是本文件里的第二份实现（自己 glob + splitlines + json.loads），与
    `sessions.read_session` 对"读不明白"各有一套判定 —— 同一份坏目录，一处说"坏行 3 条"、
    另一处说"文件读不出来"。现在只有 `sessions` 一处实现；本函数保留名字与返回形状，因为 `sources["sessions"]` 的那几个键
    是既有输出面的一部分（`readouts.errors_readout` 的 `data.sources` 逐字带着它们）。
    """
    return SS.read_all_sessions(root)


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
        #: 事件自己的 `ts`（行上没有这一格）：样本的"什么时候"靠它。只加在副本上，
        #: 不进台账行、不写回任何地方。
        latest[tid].setdefault("_ts", str(event.get("ts") or ""))
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

    受控拒绝补一档：`result.data` 里 `refusal_code` / `reason` 两格也进
    可扫段 —— 前提是这一条是受控拒绝形状（`ok=True` + `data.state=="refused"`，或
    `data.refusal_code` 非空）。理由：这两格是受控码 / 受控理由，不是模型自由文本
    （与 `table.describe` 把 schema 词表铺进 `data` 那一档严格分开：形状不对时 `data`
    一个字都不读）。
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
        data = result.get("data")
        if isinstance(data, Mapping) and _controlled_refusal_shape(result):
            for key in ("refusal_code", "reason"):
                value = data.get(key)
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


# ---------------------------------------------------------------- 辅助源（只读）
#
# 扩面新加的四个目录 + 两个只取一格的源。每个都是独立的读函数：
# `test_stats_all_reads_disk_once` 数的是 `_read_events` / `_read_sessions` 那两个口，
# 所以这里不会把那条判据带动；而 `readouts` 每条读数只调一次 `_read_aux`。


def _read_jsonl_dir(root: Path, sub: str, pattern: str = "*.jsonl",
                    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读 `<root>/<sub>/<pattern>` 下的 jsonl（坏行单独计数，不静默跳过）。

    目录不存在 ⇒ `checked=True` + 0 条（"这个工作区没有这一类记录"是正常形态，
    与 `sessions` 那一支同一条口径）；目录在而每一行都读不明白 ⇒ `checked=False`。
    """
    reading: dict[str, Any] = {"checked": True, "dir": sub, "files": 0, "records": 0,
                               "bad_lines": 0, "reason": ""}
    folder = root / sub
    if not folder.is_dir():
        return ([], reading)
    rows: list[dict[str, Any]] = []
    bad = 0
    files = 0
    for path in sorted(folder.glob(pattern)):
        if not path.is_file():
            continue
        files += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            bad += 1
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
                obj["_file"] = path.name
                rows.append(obj)
            else:
                bad += 1
    reading.update(files=files, records=len(rows), bad_lines=bad)
    if not rows and bad:
        reading["checked"] = False
        reading["reason"] = f"{sub} 里每一行都读不明白（{bad} 行）"
    return (rows, reading)


def _read_json_table(root: Path, rel: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读一张表文件（`data/<表>.json`）的行。形状是 `{"schema_version":…, "rows":[…]}`。

    只给"取一格"的用途（`statements` 的 `proof_authors`）：读不出来 ⇒ `checked=False`，
    调用方把归属记成 `（未记作者）`，不猜一个角色。
    """
    reading: dict[str, Any] = {"checked": True, "path": rel, "records": 0,
                               "bad_lines": 0, "reason": ""}
    path = root / rel
    if not path.is_file():
        return ([], reading)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        reading.update(checked=False, reason=f"{rel} 读不出来（{type(e).__name__}: {e}）")
        return ([], reading)
    rows = doc.get("rows") if isinstance(doc, Mapping) else None
    if isinstance(rows, Mapping):
        rows = list(rows.values())
    if not isinstance(rows, list):
        reading.update(checked=False, reason=f"{rel} 里没有 rows 列表")
        return ([], reading)
    good = [dict(r) for r in rows if isinstance(r, Mapping)]
    reading.update(records=len(good), bad_lines=len(rows) - len(good))
    return (good, reading)


def _read_stop_history(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读 `runs/stop-history.jsonl`（停机流水）。没有这个文件 ⇒ 0 条，不是"读不到"。"""
    reading: dict[str, Any] = {"checked": True, "path": "runs/stop-history.jsonl",
                               "records": 0, "bad_lines": 0, "by_user": 0,
                               "unexplained": 0, "reason": ""}
    path = root / "runs" / "stop-history.jsonl"
    if not path.is_file():
        return ([], reading)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        reading.update(checked=False, reason=f"停机流水读不出来（{type(e).__name__}: {e}）")
        return ([], reading)
    rows: list[dict[str, Any]] = []
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
    by_user = sum(1 for r in rows if str(r.get("by") or "") == "user")
    reading.update(records=len(rows), bad_lines=bad, by_user=by_user)
    return (rows, reading)


def _read_closing(root: Path) -> dict[str, Any]:
    """现算收工门（`closing.check_closing`）—— 与 Acceptance 页同一处，不另算一份。

    三态：没有 `out/` ⇒ `not_applicable`（这个工作区还没有可交的东西，收工门没有对象）；
    算不出来 ⇒ `unknown`（不是"没有 blocker"）。这一支是本模块唯一"现算"的源，也是唯一
    可能慢的；所以它只读一次、只给 `closing_blocker` 一类用。
    """
    reading: dict[str, Any] = {"checked": False, "state": "unknown", "reason": "",
                               "blockers": [], "status": {}, "machine_pass": False,
                               "can_close": None, "can_close_reason": "", "source": "closing.check_closing"}
    if not (root / "out").is_dir():
        reading.update(checked=True, state="not_applicable",
                       reason="这个工作区没有 out/ ⇒ 收工门没有对象（不是'通过了'）")
        return reading
    try:
        from . import closing as CL
        from .store import Store

        # 必须绝对路径：`check_closing` 按 store 的 root 解析 `data/` 与 `statements`，
        # 给一个相对路径会让它读不到表，多出一条 blocker
        # `statements_unsigned_without_v_or_abandon`。读数会因此
        # 静默变成"另一个工作区"的结论，所以这里显式 resolve。
        store = Store(Path(root).resolve())
        rep = CL.check_closing(store, project_dir=".", report_path="out/review/REPORT.md")
    except Exception as e:  # noqa: BLE001 读不出来与"没有 blocker"必须分得开
        reading.update(reason=f"收工门算不出来（{type(e).__name__}: {e}）")
        return reading
    blockers = []
    for one in (getattr(rep, "blockers", None) or ()):
        code = str(getattr(one, "code", "") or "")
        check = str(getattr(one, "check", "") or "")
        level = str(getattr(one, "level", "") or "")
        blockers.append({"code": code, "check": check, "level": level})
    reading.update(checked=True, state="checked", reason="", blockers=blockers,
                   status={str(k): str(v) for k, v in (getattr(rep, "status", None) or {}).items()},
                   machine_pass=bool(getattr(rep, "machine_pass", False)),
                   can_close=getattr(rep, "can_close", None),
                   can_close_reason=str(getattr(rep, "can_close_reason", "") or ""))
    return reading


def _read_aux(root: Path) -> dict[str, Any]:
    """一次读完扩面要用的全部辅助源，供 `error_action_stats_from` 用。

    为什么单列一个函数（而不塞进 `readouts.scan`）：这四个源只有错误动作读数要，
    塞进共用扫描会让 `flow` / `cost` / `gates` 白读它们；而"每条读数自己读一遍"
    又会把同目录读多次。单列一次是这两头之间的那个点（父裁第 ② 条）。

    返回的每个源都是 `{"rows" 或 "reading"}` 形状；`reading` 逐源带 `checked` / `reason`，
    于是"这一类没查成"能落到具体那一类上，不把整页拖成 0。
    """
    verifications, ver_reading = _read_jsonl_dir(root, "verifications")
    refusals, ref_reading = _read_jsonl_dir(root, "out/roster/refusals")
    secretary, sec_reading = _read_jsonl_dir(root, "out/secretary")
    roster_rows, roster_reading = _read_jsonl_dir(root, "out/roster")
    statements, st_reading = _read_json_table(root, "data/statements.json")
    stop_rows, stop_reading = _read_stop_history(root)
    closing_reading = _read_closing(root)

    # 名册折叠：`*-index.jsonl` 是 append-only 流水（bind / retire），不是状态 ——
    # 直接数会把"B1 重开 10 次"读成"10 个重名"。折叠口径与 `secretary.child_counts` 一致。
    #
    # 只折 `-index.jsonl`：主册（`<owner>.jsonl`）与索引记的是同一批名字（`add` 与 `bind`
    # 一一对应），两份一起折会让每个名字都变成"同名多开"的假数。
    live: dict[str, dict[str, list[str]]] = {}
    repaired: list[dict[str, Any]] = []
    for row in roster_rows:
        if not str(row.get("_file") or "").endswith("-index.jsonl"):
            if row.get("repaired"):
                repaired.append(row)
            continue
        name = str(row.get("name") or "")
        owner = str(row.get("owner") or "")
        if not name or not owner:
            continue
        slot = live.setdefault(owner, {})
        if str(row.get("kind") or "") == "retire":
            slot.pop(name, None)
        else:
            slot.setdefault(name, []).append(str(row.get("task_id") or ""))
    collisions = {f"{owner}:{name}": len(ids)
                  for owner, names in live.items() for name, ids in names.items() if len(ids) > 1}
    # 会话文件名（只 glob 名字，不读内容）：样本的 `source` 要指到具体哪个文件，
    # 而 `sessions.read_all_sessions` 刻意不回文件名（它是"记录"不是"文件"）。
    sess_folder = root / "sessions"
    session_names = (sorted(p.name for p in sess_folder.glob("*.jsonl") if p.is_file())
                     if sess_folder.is_dir() else [])
    roster_reading = dict(roster_reading)
    roster_reading.update(
        children_unretired=sum(len(names) for names in live.values()),
        name_collisions=len(collisions),
        collisions=dict(sorted(collisions.items())),
        repaired=len(repaired),
    )

    return {
        "verifications": {"rows": verifications, "reading": ver_reading},
        # 名册这一格只带它自己的行；拒绝流水单列成 `roster_refusals`（下一行）。
        # 拒绝流水的 `refusals` 不许再塞进名册那一格一次 ⇒ 同一个量
        # 两个裸键名（三义那条判据点名要治的形态）。读侧只走 `roster_refusals`。
        "roster": {"rows": roster_rows, "repaired": repaired, "reading": roster_reading},
        "roster_refusals": {"rows": refusals, "reading": ref_reading},
        "secretary": {"rows": secretary, "reading": sec_reading},
        "statements": {"rows": statements, "reading": st_reading},
        "stop_history": {"rows": stop_rows, "reading": stop_reading},
        "session_files": {"rows": [], "reading": {"checked": True, "names": session_names,
                                                  "reason": ""}},
        "closing": {"rows": [], "reading": closing_reading},
    }


def _no_aux(reason: str) -> dict[str, Any]:
    """没传辅助源时的替身：每个源都 `checked=False`，理由是同一句。

    为什么是 `unknown` 而不是空：这四个源里藏着 7 个类目。把它们折成 0 会让
    "这一类这一趟没有"与"这一类根本没查"长得一模一样（三态纪律）。
    """
    reading = {"checked": False, "reason": reason}
    return {name: {"rows": [], "reading": dict(reading)}
            for name in ("verifications", "roster", "roster_refusals", "secretary",
                         "statements", "stop_history", "closing")}


#: 工具层拒因的族表（`(类目, 认得它的原话)`）。顺序即优先级：同一段文字同时命中两族时
#: 上面那族赢（例如"实验参数在跑脚本之前就不合格"只归 `experiment_refused`）。
#: 每一族的原话都在源码里逐条 grep 过（见 `CODE_TABLE` 的出处列）。
_TOOL_REFUSAL_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("experiment_refused", ("跑脚本之前",)),
    ("experiment_failed", ("实验执行失败",)),
    ("tool_refused_reserved", ("框架渲染的产物",)),
    ("tool_refused_edit_window", ("单次定点替换上限", "old_string 在")),
    ("reply_shape_rejected", ("一次只能说一件事", "攻坚计划被拒绝")),
    ("tool_refused_path", ("文件不存在：", "路径不存在：", "是目录（要列出内容请用",
                           "没有全文路径")),
    ("external_unavailable", ("ProviderError",)),
)


def _reply_shape_family(result: Mapping[str, Any]) -> tuple[str, str] | None:
    """一步 `shape="invalid"` 里"这次回话的形状不成立"的那一档：`(码, 类目)` 或 None。

    读 `result.problem` / `result.error` / `result.detail` 三格 —— 形状被拒的原话在
    `problem` 里（`agent_loop` 把它当成"这一步是什么形状"的理由），与 `ok=False` 那一族
    走的是不同字段，所以不能共用 `_tool_refusal_family`。
    """
    text = " ".join(str(result.get(k) or "") for k in ("problem", "error", "detail"))
    for needle in ("一次只能说一件事", "攻坚计划被拒绝"):
        if needle in text:
            return (needle, "reply_shape_rejected")
    return None


def _tool_refusal_family(result: Mapping[str, Any]) -> tuple[str, str] | None:
    """一条 `ok=False` 的工具结果属于哪一族：`(码, 类目)`；认不出 ⇒ None。

    只读 `result.error` 与 `result.detail`，不读 `warn`：`warn` 里的多调用汇总逐条
    复述"第 2 条 fs.read 被拒：. 是目录"，读它会把一次被拒的调用数成两次（D-65 那条纪律
    的反面）。也不读 `result.data`：那里是工具输出，`table.describe` 打印的 schema 里
    满地都是 `item_state` 这种词。
    """
    text = " ".join(str(result.get(k) or "") for k in ("error", "detail"))
    if not text.strip():
        return None
    for category, needles in _TOOL_REFUSAL_FAMILIES:
        for needle in needles:
            if needle in text:
                return (needle, category)
    return None


def _controlled_refusal_shape(result: Mapping[str, Any]) -> bool:
    """这一条结果是不是"工具层受控拒绝"（结构判据，不读文案）。

    形状（`conductor_tools._out` 那一族）：`result.ok is True`，而拒因写在
    `data.state == "refused"` 或 `data.refusal_code`（非空）里 —— 工具把"拒了"当成
    "成功"返回，于是 `ok is False` 那条老路一条都数不到。
    """
    if result.get("ok") is not True:
        return False
    data = result.get("data")
    if not isinstance(data, Mapping):
        return False
    return (str(data.get("state") or "") == "refused"
            or bool(str(data.get("refusal_code") or "")))


def _controlled_refusal_family(result: Mapping[str, Any]) -> tuple[str, str] | None:
    """一条受控拒绝属于哪一类：`(码, 类目)`；认不出 ⇒ None。

    - `data.refusal_code` 非空 ⇒ 按那个码记；码表里登记了就用它登记的类目，
      码表里没有 ⇒ None（调用方记 `unclassified["tool"]`，不猜一个类目出来）；
    - 只有 `data.state == "refused"`、没有码 ⇒ 记 `tool_refused_controlled`，
      码位留空（`""`）：这一笔只有状态、没有受控码 —— 状态不是码，不把
      `data.state` 的取值登记成假码（"状态≠码"的折平）。
    """
    if not _controlled_refusal_shape(result):
        return None
    data = result["data"]
    code = str(data.get("refusal_code") or "")
    if not code:
        return ("", "tool_refused_controlled")
    category = CODE_TO_CATEGORY.get(code)
    return (code, category) if category is not None else None


def _role_of(value: Any) -> str:
    """从 `created_by` / `proof_authors` 这种"带前缀的角色名"里取角色。

    `secretary-B` → `B`；`B` → `B`；认不出 ⇒ 原样（由调用方决定记 `（未记作者）` 还是记它）。
    """
    name = str(value or "").strip()
    if not name:
        return ""
    if name in S.ROLES or name == S.CONDUCTOR_ROLE:
        return name
    tail = name.rsplit("-", 1)[-1].strip()
    if tail in S.ROLES or tail == S.CONDUCTOR_ROLE:
        return tail
    return name


def _author_of(row: Mapping[str, Any], authors: Mapping[str, str]) -> str:
    """一条 `verifications` 行的命题作者：`statements.proof_authors` → `created_by`。

    为什么不去看 `verifier`：那是 V。把"证明有毛病"记到 V 头上，等于让复核的人替写证明的
    人背锅 —— 而"一方的错不算到另一方头上"是这个模块钉的第一条。
    """
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    if sid and sid in authors:
        return authors[sid]
    return UNKNOWN_AUTHOR


def error_action_stats(target: Any) -> ErrorStats:
    """按角色统计错误动作计数。`target` 可以是工作区根路径，也可以是 `Store`。

    纯读：不写库、不写盘、不建目录、不加锁（`Store.read_events` 本身只读文件；
    `closing.check_closing` 也只读，跑完工作区的 mtime 一个都没动）。
    三态见模块 docstring 第 3 条：读不到 ⇒ `checked=False` / `state="unknown"`，
    不把"没读到"折成 0。
    """
    root, store = _resolve_target(target)
    events, ev_reading = _read_events(root, store)
    records, ss_reading = _read_sessions(root)
    aux = _read_aux(root) if root.is_dir() else _no_aux(f"工作区不存在：{root}")
    return error_action_stats_from(events, ev_reading, records, ss_reading, aux=aux)


def error_action_stats_from(events: Iterable[Mapping[str, Any]] | None,
                            ev_reading: Mapping[str, Any] | None,
                            records: Iterable[Mapping[str, Any]] | None,
                            ss_reading: Mapping[str, Any] | None,
                            *,
                            aux: Mapping[str, Any] | None = None) -> ErrorStats:
    """同一份计数，但输入是已经读好的记录（不再读事件流与会话记录）。

    为什么要这一支：`stats all` 那四条读数各读一遍盘（`events.jsonl` 与
    `sessions/*.jsonl` 各被读、解析四遍）。`readouts` 把它自己那份扫描交给这里，计数口径仍然只有这一处 ——
    在这里复制一份分类逻辑就是第二套口径，而那正是 `readouts` 这一层存在的理由。

    `aux`（扩面）：新读的四个目录 + 两个只取一格的源，由
    `_read_aux(root)` 一次读好传进来。不传 ⇒ 那 7 个类目一律 `unknown`，不是 0
    （它们藏在辅助源里，"没查"与"没有"必须分得开）。`readouts.errors_readout` 传它；
    判据 `tests/test_stats_all_reads_disk_once.py` 拿同一夹具对拍两条路的 `as_dict()`。

    三态：三个 `*_reading` 原样带出去（`checked` / `reason` / `unreadable_files`），
    本函数不重判"读没读到"。两个 reading 会先复制成本地 dict，于是 `unclassified`
    那一格的累加不会写回调用方手里的那份扫描读数。
    """
    events = list(events or ())
    records = list(records or ())
    ev_reading: dict[str, Any] = dict(ev_reading or {})
    ss_reading: dict[str, Any] = dict(ss_reading or {})
    aux_in: Mapping[str, Any] = aux if isinstance(aux, Mapping) else _no_aux(
        "这条路径没传辅助源（只读了事件流与会话记录）⇒ 这一类的 7 个读数没查成")

    def _aux_rows(name: str) -> list[dict[str, Any]]:
        got = aux_in.get(name)
        rows = got.get("rows") if isinstance(got, Mapping) else None
        return [dict(r) for r in (rows or ()) if isinstance(r, Mapping)]

    def _aux_reading(name: str) -> dict[str, Any]:
        got = aux_in.get(name)
        reading = got.get("reading") if isinstance(got, Mapping) else None
        return dict(reading or {"checked": False, "reason": "这个源没读到"})

    counts: dict[str, dict[str, int]] = {}
    process: dict[str, dict[str, int]] = {}
    state: dict[str, dict[str, int]] = {}
    system: dict[str, int] = {}
    hits: dict[str, dict[str, int]] = {}
    #: 每一类的前 `_SAMPLE_CAP` 条明细：页面上"展开到每条的 source"靠它。
    #: 只留前 N 条是刻意的：这一栏是"点开看一条长什么样"，不是把台账搬进 JSON。
    samples: dict[str, list[dict[str, Any]]] = {}
    #: 结构判据认不出的那些：不猜一个类目，但必须看得见（与 `events.unclassified` 同族）。
    unclassified: dict[str, int] = {"tool": 0, "verdict": 0, "roster": 0, "secretary": 0}

    #: 当前这条记录的出处（`source` / `ref` / `ts` / `detail`）。每个循环在取到一条记录时
    #: 就地更新它，`_bump` 用它在"头 N 条"时留样本 —— 于是"每条样本的 source"只在一处拼，
    #: 不必在十几个 `_bump` 调用点各写一遍（那种写法一定会漏掉几处，而漏了没人看得出）。
    ctx: dict[str, str] = {"source": "", "ref": "", "ts": "", "detail": ""}
    #: 类目 → `{first, last, this_run, earlier, no_ts}`：时间那一栏的读数。
    #: "这一趟"的边界不是拍出来的一个数：`run_boundary` = 最后一处 `agent_run_start` 的 ts
    #: （这一趟从哪一刻起）。边界拿不到（没有 `agent_run_start`）⇒ 全部记 `earlier` 并把
    #: `run_boundary` 留空，页面上那一栏就显示"边界读不到"，不假装分了趟。
    spans: dict[str, dict[str, Any]] = {}
    run_boundary = ""
    for record in records:
        if str(record.get("kind") or "") != "agent_run_start":
            continue
        one = str(record.get("ts") or "")
        if one and one > run_boundary:
            run_boundary = one

    def _span(cat: str, when: str) -> None:
        slot = spans.setdefault(cat, {"first": "", "last": "", "this_run": 0,
                                      "earlier": 0, "no_ts": 0})
        if not when:
            slot["no_ts"] = int(slot["no_ts"]) + 1
            return
        if not slot["first"] or when < slot["first"]:
            slot["first"] = when
        if not slot["last"] or when > slot["last"]:
            slot["last"] = when
        key = "this_run" if run_boundary and when >= run_boundary else "earlier"
        slot[key] = int(slot[key]) + 1

    def _mark(role: str, code: str) -> None:
        seen = hits.setdefault(role, {})
        seen[code] = int(seen.get(code, 0)) + 1

    def _bump(role: str, code: str, cat: str, **where: str) -> None:
        """记一条命中。落哪个桶由类目决定，不由调用点决定。

        为什么把分桶放在这里：于是"过程读数 / 系统侧 / 状态读数"在结构上进不了
        `total` / `role_total` —— 任何一条路径把它们当错误记，它都会落进另一个桶。
        而不是靠每个调用点自己记得"这个不计错"（那种纪律一定会漏，而漏了不会有任何地方报错）。

        `source` / `ref` / `ts` / `detail` 是"这一条从哪来"的四个格子（页面展开用）：
        `source` 是文件（或现算入口），`ref` 是文件里的记录身份（`task_id` / `verification_id` /
        `seq`），`detail` 是那一句原话的截断。计数不受它们影响 —— 只在头 N 条时留样本。
        不传就用当前 `ctx`（每个循环在取到一条记录时就地更新它）。
        """
        where = {k: str(v) for k, v in where.items()}
        get = lambda name: where.get(name) or ctx.get(name, "")  # noqa: E731
        if cat in SYSTEM_CATEGORY_NAMES:
            system[cat] = int(system.get(cat, 0)) + 1
            _mark(SYSTEM_ACTOR, code)
            bucket_role = SYSTEM_ACTOR
        elif cat in STATE_CATEGORY_NAMES:
            cells = state.setdefault(role, {})
            cells[cat] = int(cells.get(cat, 0)) + 1
            _mark(role, code)
            bucket_role = role
        else:
            bucket = process if cat in PROCESS_CATEGORY_NAMES else counts
            cells = bucket.setdefault(role, {})
            cells[cat] = int(cells.get(cat, 0)) + 1
            _mark(role, code)
            bucket_role = role
        source, ref = get("source"), get("ref")
        _span(cat, get("ts"))
        if (source or ref) and len(samples.setdefault(cat, [])) < _SAMPLE_CAP:
            samples[cat].append({"role": bucket_role, "code": str(code),
                                 "source": source, "ref": ref,
                                 "ts": get("ts"), "detail": get("detail")[:160]})

    def _bump_system(code: str, cat: str) -> None:
        _bump(SYSTEM_ACTOR, code, cat)


    task_rows = _latest_task_rows(events)
    task_role: dict[str, str] = {}
    task_caller: dict[str, str] = {}
    for row in task_rows:
        tid = str(row.get("task_id") or "")
        if tid:
            task_role[tid] = str(row.get("role") or "")
            task_caller[tid] = str(row.get("called_by") or "")

    def _caller_or_actor(record: Mapping[str, Any], role: str) -> str:
        """送审 / 父退场那一档：能查到 `called_by` 就记它，查不到退回动作方。"""
        tid = str(record.get("task_id") or "")
        caller = task_caller.get(tid) or ""
        if _known_role(caller):
            return _role_name(caller)
        return role

    session_names = list(_aux_reading("session_files").get("names") or ())
    roster_reading = _aux_reading("roster")
    statements_reading = _aux_reading("statements")
    stop_reading = _aux_reading("stop_history")

    def _where(record: Mapping[str, Any]) -> tuple[str, str, str]:
        """一条会话记录的 `(source, ref, ts)`：页面展开时"去哪看这一条"。

        `source` 指到具体文件：记录自带 `sid` 就用它；否则这个工作区只有一个会话文件时
        用那个文件名；多个文件又没有 `sid` ⇒ 只给目录（不猜是哪一个 —— 猜错比指不到更坏）。
        `ref` 是记录身份（`kind#index`），配 `ts` 足以 `grep` 定位。
        """
        sid = str(record.get("sid") or "")
        name = f"{sid}.jsonl" if sid else (session_names[0] if len(session_names) == 1 else "")
        kind = str(record.get("kind") or "")
        idx = record.get("index")
        ref = f"{kind}#{idx}" if idx is not None else kind
        return (f"sessions/{name}" if name else "sessions/", ref,
                str(record.get("ts") or ""))

    stop_rows = _aux_rows("stop_history")
    stopped_by_user = any(str(r.get("by") or "") == "user" for r in stop_rows)

    # ---- 事件流：tasks 行的被拒 / 没做成 / 板项 / 被叫停
    if ev_reading.get("checked"):
        board_items = 0
        board_open = 0
        for row in task_rows:
            ctx.update(source="data/events.jsonl", ref=str(row.get("task_id") or ""),
                       ts=str(row.get("_ts") or ""),
                       detail=str(row.get("detail") or ""))
            outcome = str(row.get("outcome") or "")
            if outcome in (_REFUSAL_OUTCOME, _FAILED_OUTCOME):
                found = primary_code(row.get("refusal_reason"), row.get("error"),
                                     row.get("detail"))
                if found is None:
                    # 被拒但理由码不在码表里（历史行 / 新码没登记）：不猜一个类目出来，
                    # 也不静默丢掉 —— 记进 `sources.events.unclassified`，人读的呈现里会点名。
                    # 这条纪律与"没读到不许折成 0"同族：没见过的东西不许编，但必须看得见。
                    if outcome == _REFUSAL_OUTCOME:
                        ev_reading["unclassified"] = int(
                            ev_reading.get("unclassified") or 0) + 1
                else:
                    code, cat = found
                    if code in CALLER_ATTRIBUTED_CODES and _known_role(row.get("called_by")):
                        role = _role_name(row.get("called_by"))
                    else:
                        role = _role_name(row.get("role"))
                    _bump(role, code, cat)
            elif outcome == _CUT_OFF_OUTCOME:
                # 父退场切割：孩子还在跑、父先退了 ⇒ 这一行由父的退场结算写成终态。
                # 记发起方（`called_by`）：活是它派出去的，它先走了。
                _bump(_caller_or_actor(row, _role_name(row.get("role"))),
                      "cut_off_by_parent", "child_cut_off")
            elif outcome == _CANCELLED_OUTCOME:
                # 叫停算不算错，先看停机流水（模块 docstring 第五节那条最容易改坏的格子）。
                if stopped_by_user:
                    _bump(_role_name(row.get("role")), "cancelled", "task_stopped")
                else:
                    # 没有 by=user 的停机记录解释它 ⇒ 不记错误（可能是父的 dispose），
                    # 但要看得见：记进 `sources.events.cancelled_unexplained`。
                    ev_reading["cancelled_unexplained"] = int(
                        ev_reading.get("cancelled_unexplained") or 0) + 1
            # ---- 板项（状态读数）：`item_state != done` 且不是停机通知
            if str(row.get("kind") or "") not in _BOARD_KINDS:
                continue
            board_items += 1
            if str(row.get("item_state") or "") == "done":
                continue
            board_open += 1
            detail = str(row.get("detail") or "").lstrip()
            if detail.startswith(_STOP_ITEM_PREFIXES):
                # 停机相关的那 4 条：它们是叫停的下游形态，不是"通知发了没人收口"。
                ev_reading["stop_items_open"] = int(ev_reading.get("stop_items_open") or 0) + 1
                continue
            _bump(_role_name(row.get("role")), "item_state", "item_not_acked")
        # 板项是快照：`tasks` 读不到时那个 0 也得说成"没查成"，所以单独一格的读数
        ev_reading["board_items"] = board_items
        ev_reading["board_open"] = board_open

    # ---- 会话记录：判据层的 problem、工具层的拒信、代唤请示
    if ss_reading.get("checked"):
        # 同一次失败在会话里落两条记录：`llm_call`（带网关原话）与它的 `agent_step`
        # （`shape="invalid"`，正文只有一句码名）。两处都数会把一次断网关数成两次 ——
        # 去重键取"同 ts + 同角色 + 同类目"：那是这两条记录共享的全部身份，
        # 并且只在这一格生效（不同失败照旧各算各的，见判据的反真空那一条）。
        counted_from_llm: set[tuple[str, str, str]] = set()
        for record in records:
            if str(record.get("kind") or "") != "llm_call":
                continue
            found = primary_code(record.get("problem"), record.get("detail"))
            if found is not None:
                counted_from_llm.add((str(record.get("ts") or ""),
                                      _role_name(record.get("role")), found[1]))
        for record in records:
            kind = str(record.get("kind") or "")
            role = _role_name(record.get("role"))
            src, ref, when = _where(record)
            ctx.update(source=src, ref=ref, ts=when,
                       detail=str((record.get("result") or {}).get("error")
                                  if isinstance(record.get("result"), Mapping) else "")
                       or str(record.get("problem") or "") or str(record.get("subject") or ""))
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
                    key = (str(record.get("ts") or ""), role, found[1])
                    if key in counted_from_llm:
                        # 同一次失败：`llm_call` 已经记过（它带着网关的原话）⇒ 不再计
                        counted_from_llm.discard(key)
                    else:
                        _bump(role, *found)
                # ---- 结构判据：只在主码没认出任何类目时才走（于是老的六类逐条不变）
                if found is None:
                    result = record.get("result")
                    if isinstance(result, Mapping):
                        data = result.get("data")
                        if (isinstance(data, Mapping)
                                and str(data.get("kind") or "") == "statement_missing"):
                            # 没审成：命题还没登记就送审 ⇒ 记送审方（它是这次送审的发起方）
                            _bump(_caller_or_actor(record, role), "statement_missing",
                                  "verdict_missing")
                        elif _controlled_refusal_shape(result):
                            # 受控拒绝：工具把"拒了"写在 `data` 里，`ok` 位却
                            # 仍是 True（`conductor_tools._out` 的最后一句）。有受控码就按
                            # 码表登记的类目记；只有 `state=="refused"` 的落
                            # `tool_refused_controlled`（码位留空）；码认不出 ⇒ 不猜，记兜底。
                            family = _controlled_refusal_family(result)
                            if family is None:
                                unclassified["tool"] += 1
                            else:
                                _bump(role, *family)
                        elif result.get("ok") is False:
                            if str(result.get("outcome") or "") == _CANCELLED_OUTCOME:
                                # 与 `tasks` 行那个 `cancelled` 是同一件事（召唤被叫停）：
                                # 只从台账数一次，这里不重计（去重对 ① 的另一半）。
                                pass
                            else:
                                family = _tool_refusal_family(result)
                                if family is None:
                                    # ok=False 但哪一族都不认：不猜（兜底留在 sources 里）
                                    unclassified["tool"] += 1
                                else:
                                    _bump(role, *family)
                        elif str(record.get("shape") or "") == "invalid":
                            # 形状被拒（"一次只能说一件事"）：原话在 `result.problem` 里，
                            # 与 ok=False 那一族不同字段，所以单独一支。
                            shape_family = _reply_shape_family(result)
                            if shape_family is None:
                                unclassified["verdict"] += 1
                            else:
                                _bump(role, *shape_family)
                # 拆分这件事的读数从结构字段取：一个被拆分的回合正好记一次。
                if _is_split_step(record):
                    _bump(role, "multi_call", "steps_split")
                continue
            if kind == "agent_step_call":
                # 逐条记录：一条一个结局，三档互斥。
                # 执行了 ⇒ 过程读数 `multi_call_executed_calls`（拆分生效的正读数）；
                # 没执行 ⇒ 按它自己的结局原话进三个真失败类目之一（`_call_text`）。
                # "一条记录只算一次"在这里成立：本记录只往一个桶里记一次。
                # 与 `agent_step` 不重叠：步只数 `ok=False` 那一步的结局，这里只数
                # `not_executed`（那一条在步上没有对应记录）。
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

    # ---- 校验台账：V 判「有毛病」/ 有未解决 error ⇒ 记命题作者
    ver_reading = _aux_reading("verifications")
    if ver_reading.get("checked"):
        st_rows = _aux_rows("statements")
        authors: dict[str, str] = {}
        for row in st_rows:
            sid = str(row.get("stmt_id") or "")
            if not sid:
                continue
            who = row.get("proof_authors")
            first = ""
            if isinstance(who, (list, tuple)) and who:
                first = str(who[0] or "")
            elif isinstance(who, str):
                first = who
            name = _role_of(first) or _role_of(row.get("created_by"))
            if name:
                authors[sid] = name
        for row in _aux_rows("verifications"):
            sid = str(row.get("stmt_id") or row.get("statement_id") or "")
            ctx.update(source=f"verifications/{sid}.jsonl" if sid else "verifications/",
                       ref=str(row.get("verification_id") or ""),
                       ts=str(row.get("at") or ""),
                       detail=str(row.get("why") or row.get("defect_step") or ""))
            verdict = str(row.get("verdict") or "")
            unresolved = int(row.get("unresolved_errors") or 0)
            if verdict != "有毛病" and unresolved <= 0:
                continue
            _bump(_author_of(row, authors), "有毛病", "proof_defect_found")

    # ---- 名册写口拒绝：记"要这个名字的那一方"
    ref_reading = _aux_reading("roster_refusals")
    if ref_reading.get("checked"):
        for row in _aux_rows("roster_refusals"):
            owner = str(row.get("owner") or "")
            ctx.update(source=f"out/roster/refusals/{row.get('_file') or ''}",
                       ref=f"{owner}#{row.get('seq')}", ts=str(row.get("at") or ""),
                       detail=str(row.get("problem") or ""))
            role = _role_of(task_role.get(owner) or "")
            if not role:
                unclassified["roster"] += 1
                role = UNKNOWN_ROLE
            code = str(row.get("refusal_code") or "")
            if not code:
                # 没有码的那一条（`reuse`/`want_name` 同时给）：码这一格记原话的前 24 字，
                # 它只影响 `sources.hits`，不影响类目。
                code = str(row.get("problem") or "")[:24] or "name_taken"
            _bump(role, code, "roster_write_refused")
        for row in _aux_rows("roster"):
            if row.get("repaired") and not str(row.get("_file") or "").endswith("-index.jsonl"):
                owner = str(row.get("owner") or "")
                ctx.update(source=f"out/roster/{row.get('_file') or ''}",
                           ref=str(row.get("name") or ""), ts=str(row.get("at") or ""),
                           detail=str(row.get("brief") or ""))
                _bump(_role_of(task_role.get(owner) or "") or UNKNOWN_ROLE,
                      "repaired", "roster_repaired")

    # ---- 秘书判词：V 低报缺陷（记 V）与 hook 没判成（系统侧）
    sec_reading = _aux_reading("secretary")
    if sec_reading.get("checked"):
        for row in _aux_rows("secretary"):
            target = row.get("target")
            judge_axis = str(target.get("judge") or "") if isinstance(target, Mapping) else ""
            decision = str(row.get("decision") or "")
            ctx.update(source=f"out/secretary/{row.get('_file') or ''}",
                       ref=f"seq={row.get('seq')}", ts=str(row.get("at") or ""),
                       detail=str(row.get("reason") or ""))
            if judge_axis == "v_reply_defect" and decision == "有缺陷要指出":
                _bump(_role_name(row.get("role")), "有缺陷要指出", "verdict_understated")
                continue
            if row.get("fail_open") or decision == "判不了":
                _bump_system("fail_open" if row.get("fail_open") else "判不了",
                             "hook_undecided")

    # ---- 收工门（现算）：blocker 逐条
    cls_reading = _aux_reading("closing")
    for one in (cls_reading.get("blockers") or ()):
        code = str((one or {}).get("code") or "") if isinstance(one, Mapping) else ""
        ctx.update(source="closing.check_closing",
                   ref=str((one or {}).get("check") or "") if isinstance(one, Mapping) else "",
                   ts=str(cls_reading.get("at") or ""),
                   detail=str((one or {}).get("level") or "") if isinstance(one, Mapping) else "")
        if not code:
            unclassified["verdict"] += 1
            code = "closing_blocker"
        _bump_system(code, "closing_blocker")

    role_total = {role: sum(cats.values()) for role, cats in counts.items()}
    total = sum(role_total.values())
    state_total = sum(sum(cats.values()) for cats in state.values())
    system_total = sum(system.values())

    checked = bool(ev_reading.get("checked")) and bool(ss_reading.get("checked"))
    reasons: list[str] = []
    if not ev_reading.get("checked"):
        reasons.append(str(ev_reading.get("reason") or "事件流读不到"))
    if not ss_reading.get("checked"):
        reasons.append(str(ss_reading.get("reason") or "会话记录读不到"))

    # ---- 逐类三态：一个源读不到只让那一类变 unknown，不把整页拖成 0
    base_state = "checked" if checked else "unknown"
    base_reason = "；".join(reasons)
    class_state: dict[str, dict[str, Any]] = {
        cat: {"checked": checked, "state": base_state, "reason": base_reason}
        for cat, _why in ALL_CATEGORIES}

    def _apply(categories: frozenset[str] | set[str] | tuple[str, ...],
               reading: Mapping[str, Any]) -> None:
        got = bool(reading.get("checked"))
        tri = str(reading.get("state") or ("checked" if got else "unknown"))
        why = str(reading.get("reason") or "")
        for cat in categories:
            class_state[cat] = {"checked": got, "state": tri, "reason": why}

    _apply({"proof_defect_found"}, ver_reading)
    _apply({"roster_write_refused"}, ref_reading)
    _apply({"verdict_understated", "hook_undecided"}, sec_reading)
    _apply({"closing_blocker"}, cls_reading)
    _apply({"task_stopped"}, stop_reading)
    _apply({"roster_repaired"}, roster_reading)
    # `statements` 读不出来只影响归属（退回 `（未记作者）`），不影响计数 —— 所以
    # `proof_defect_found` 的三态仍由 `verifications` 决定，这一格在 `sources.statements` 里
    # 单独看得见（不把"作者没记"折成"这一类没查成"）。

    sources: dict[str, dict[str, Any]] = {
        "events": ev_reading,
        "sessions": ss_reading,
        "verifications": ver_reading,
        "roster": roster_reading,
        "roster_refusals": ref_reading,
        "secretary": sec_reading,
        "statements": statements_reading,
        "stop_history": stop_reading,
        "closing": cls_reading,
        "unclassified": unclassified,
        "hits": {"checked": checked,
                 "codes": {r: dict(sorted(c.items())) for r, c in sorted(hits.items())}},
    }
    return ErrorStats(
        by_role={r: dict(sorted(c.items())) for r, c in sorted(counts.items())},
        role_total=dict(sorted(role_total.items())),
        total=total,
        process={r: dict(sorted(c.items())) for r, c in sorted(process.items())},
        system=dict(sorted(system.items())),
        system_total=system_total,
        state_readings={r: dict(sorted(c.items())) for r, c in sorted(state.items())},
        state_readings_total=state_total,
        class_state=class_state,
        samples={k: [dict(s) for s in v] for k, v in sorted(samples.items())},
        spans={k: dict(v) for k, v in sorted(spans.items())},
        run_boundary=run_boundary,
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
    """渲染成四张表：三个总数、角色侧错误、系统侧、状态读数、过程读数。

    CLI 与非 CLI 调用共用这一份。几张表分开是有意的：把拆分那几格混进错误表，
    读的人会把"系统拆了一步"看成"出错了" —— 而业主 D-65 的口径正好相反；
    "系统侧"与"状态读数"混进角色表则会把三种单位加成一个没有名字的数
    （模块 docstring 第二节）。
    """
    lines: list[str] = []
    events = stats.sources.get("events") or {}
    sessions = stats.sources.get("sessions") or {}
    lines.append("错误动作计数（角色侧 / 系统侧 / 状态读数分栏；只读，零模型调用）")
    lines.append(f"三态    checked={stats.checked}  state={stats.state}"
                 f"  逐类 读到 {_count_classes(stats, 'checked')} / "
                 f"没查成 {_count_classes(stats, 'unknown')} / "
                 f"不适用 {_count_classes(stats, 'not_applicable')}")
    if stats.reason:
        lines.append(f"原因    {stats.reason}")
    lines.append(
        "读数    事件流 {ev} 条（{evbad} 行读不明白）/ 会话记录 {ss} 条（{files} 个文件，"
        "{ssbad} 行读不明白）".format(
            ev=events.get("events", 0), evbad=events.get("bad_lines", 0),
            ss=sessions.get("records", 0), files=sessions.get("files", 0),
            ssbad=sessions.get("bad_lines", 0)))
    lines.append(
        "三个数  角色侧 {t} / 系统侧 {s} / 状态读数 {z}"
        "   ← 刻意不相加：三种单位（谁做错了 / 系统哪里坏了 / 现在积着什么）".format(
            t=stats.total, s=stats.system_total, z=stats.state_readings_total))
    if not stats.checked:
        lines.append("")
        lines.append("没有读到该读的东西 ⇒ 这里的 0 不是『没有错误动作』，是『没查成』。")
    unclassified = int(events.get("unclassified") or 0)
    if unclassified:
        lines.append(f"未归类  {unclassified} 条被拒的理由码不在码表里（未计入任何类目；"
                     "要收进来就把它登记进 CODE_TABLE）")
    loose = {k: int(v or 0) for k, v in (stats.sources.get("unclassified") or {}).items()
             if int(v or 0)}
    if loose:
        lines.append(f"未归类（结构判据）  {loose} —— 认不出族的那几条没有猜类目，"
                     "只在 sources.unclassified 里留着")

    cats = list(stats.categories().items())
    lines.append("")
    lines.append("角色侧错误动作（角色 × 类目；只有这张表进 total）：")
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

    # ---- 系统侧（不进角色合计）
    sys_cats = list(stats.system_categories().items())
    lines.append("")
    lines.append("系统侧异常（不是哪个角色做错了；不进 total）：")
    if not sys_cats:
        tri = _count_classes(stats, "unknown")
        lines.append("  0 条" + ("（但有类目没查成 —— 见下面逐类三态）" if tri else ""))
    else:
        smean = dict(SYSTEM_CATEGORIES)
        for cat, n in sorted(sys_cats, key=lambda kv: -kv[1]):
            lines.append(f"  {cat}: {n} —— {smean.get(cat, '')}")

    # ---- 状态读数（快照）
    st_cats = list(stats.state_categories().items())
    lines.append("")
    lines.append("状态读数（快照，会随 ack 回落；既不进 total 也不进系统侧）：")
    if not st_cats:
        lines.append("  0 条")
    else:
        stmean = dict(STATE_CATEGORIES)
        for cat, n in st_cats:
            per = {r: c.get(cat, 0) for r, c in sorted(stats.state_readings.items())
                   if c.get(cat)}
            lines.append(f"  {cat}: {n}（按角色 {per}）—— {stmean.get(cat, '')}")

    # ---- 过程读数（不是错误，单独一栏）
    proc = list(stats.process_categories().items())
    lines.append("")
    lines.append("过程读数（不是错误：步被拆开逐条执行是正常能力，直写被转交正路办成也是，"
                 "人叫停与自愈补登记也是）：")
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
    stop = stats.sources.get("stop_history") or {}
    if stop.get("records"):
        lines.append(f"  被叫停的解释：停机流水 {stop.get('records')} 条，其中 by=user "
                     f"{stop.get('by_user')} 条；没有解释的 cancelled "
                     f"{int((stats.sources.get('events') or {}).get('cancelled_unexplained') or 0)} 条")
    lines.append(
        "  真失败长在错误表上：多调用那三档（"
        f"multi_call_discarded={stats.category_total('multi_call_discarded')} / "
        f"multi_call_unexecuted={stats.category_total('multi_call_unexecuted')} / "
        f"multi_call_out_of_limit={stats.category_total('multi_call_out_of_limit')}"
        "）与兜底方没接住那一档（routed_to_backstop="
        f"{stats.category_total('routed_to_backstop')}）全 0 才是绿；"
        "『步被拆分』与『转交办成』本身都不是失败。")

    lines.append("")
    lines.append("口径：角色归属见 errorstats 模块 docstring（六档 `ATTRIBUTION_BUCKETS`："
                 "召唤期结构判据记 called_by、证明有毛病记命题作者、板项没 ack 记收件人、"
                 "名册写口拒绝记要名字的那一方、系统侧不进角色表）；"
                 "一条记录只算一次，主码 = 类目表靠前的类目优先、同类目里长码优先。"
                 "新 15 类全部是结构化类目（不进主码、不扫文案）。"
                 "过程读数 / 系统侧 / 状态读数都不进 total（业主 D-65 与 2026-11-01 扩面口径）。")
    return lines


def _count_classes(stats: ErrorStats, state: str) -> int:
    """逐类三态里某一档有几个类目（页面顶部那一行"15 类里 X 类读到 / Y 类没查成 / Z 类不适用"）。"""
    return sum(1 for one in (stats.class_state or {}).values()
               if str(one.get("state") or "") == state)


def stats_json(stats: ErrorStats) -> str:
    """机器可读一行（`--json` 用）。

    `default=json_default`：`as_dict()` 今天全是纯 JSON 值，但它是 `--json` 那条出口的
    唯一形态 —— 这一格一旦有非原生值（`sources` 里塞进一个 `Path` 就会），没有它是
    `TypeError` 而不是读数。纯 JSON 载荷不走 `default`，既有输出逐字不变。
    """
    return json.dumps(stats.as_dict(), ensure_ascii=False, indent=2, default=json_default)

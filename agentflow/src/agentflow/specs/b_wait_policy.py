# -*- coding: utf-8 -*-
"""B 的 policy 里「计时 / 等待」那一段的模块级常量。

为什么单独一个文件：`specs/b.py` 受「`src/` 下 > 800 行的文件数」那条体量软基线管着
（业主口径：不许抬体量软基线）。2026-11-23 的 SPECS-POLICY 给这一段的时钟口径补了
`clock.wait_any` 的两句（零计时器受控拒绝 `no_timers_to_wait`、补目的是
`timer_purpose` 那一格），`specs/b.py` 因此从顶格的 800 行涨到 802 行 —— 基线不许抬、
顶过 800 就拆，所以整段搬到本文件，`specs/b.py` 在原来的位置上用
`*_CLOCK_WAIT_POLICY` 摊回去（渲染出来的提示词一个字没变）。

与 `b_ingest_policy.py` / `b_sign_policy.py` 同一个理由：三个文件都是为把 `b.py`
留在 800 行线内而拆出来的 policy 正文；它承载的是 B 的声明正文，模型按它行动
⇒ 改它等于改口径。

逐字纪律：本文件里那一串字符串与搬出前 `specs/b.py` 的同一段逐字相同（拆前拆后的
`SPEC.brief.policy` 指纹相等，取证见 `agentflow/temp/bsplitspec/`）；谁要改这一段，
改这里是唯一落点 —— `specs/b.py` 只摊回，不重抄。
"""
from __future__ import annotations

#: 计时 / 等待那一段的 policy 正文（时钟九件、`wait_any` 的意图账与零表拒绝、
#: 补目的走 `timer_purpose`）。`specs/b.py` 用 `*_CLOCK_WAIT_POLICY` 摊回原位置。
CLOCK_WAIT_POLICY: tuple[str, ...] = (
# 计时口径进每个角色的政策（不只是 M）：计时类任务申请的形式 = 等待时间
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
)

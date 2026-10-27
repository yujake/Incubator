# -*- coding: utf-8 -*-
"""停止理由的单一真身：退出码、界面徽标、是否进退出码表（Q23，2026-10-26）。

## 为什么要有这一处

`stop_reason` 有两个读者：命令行的退出码（`cli.EXIT_CODE_BY_STOP`）与界面的
徽标（`webui.server._STOP_BADGES`）。改前两张表各写一份，新增一档只改了一边：
`final_refused` 进了退出码表（5）却没进徽标表，界面于是显示一个空徽标。
反方向也有一格：`max_steps` 留在徽标表里，退出码表没有它 —— 两表都 22 格，
旧判据的长度比较 `len(徽标) >= len(退出码)` 因此把两处错误抵消成绿。

现在一件事只在同一行里说：`reason -> (退出码, 徽标 class, 徽标文案, live)`。
`cli` 只投影 `live=True` 的那些（进退出码表的档必须有码），`webui` 投影全部
（旧会话记录里的 `max_steps` 仍然要解释得出来）。于是"新增一档只登记一边"
不再可能：新增一行就得同时给出这三件事。

## live 是什么

`live=True`：这一档在退出码表里有一格。绝大多数是运行期还在产生的档；
`no_notify` 是例外 —— 它已不再产生，但退出码 1 是早就归过类的登记
（`tests/test_run_agent_exit_code_table.py` 的 `_TABLE_ONLY_TODAY` 写着理由），
本单不动它，免得把"表可以比代码宽一点"那条既有契约一起改掉。

`live=False`：只有徽标、没有退出码。`max_steps` 是这一档：裁定 12-K 之后
循环不再产生它（步数只上报、不收工），但旧会话记录里真有。不给它借一个现成的
码，因为那会把"旧读数"和某种运行期收场混成同一个退出码。运行期真读到未登记的
档时，`cli.EXIT_CODE_WHEN_UNKNOWN` 仍然是 1（未登记），这条既有语义没有变。

## 为什么放在这里，而不是 cli.py 或 schema.py

`cli` 是命令行入口，`webui` 是读侧；让其中一边拥有这张表，另一边就要反向依赖它。
本模块是纯数据，两边都依赖它，谁也不欠谁。`schema.py` 是磁盘格式契约（禁改区），
停止理由是运行期读数，不该混进去。
"""

from __future__ import annotations

#: 全仓统一的三条口径（`R-BE1` 的 ③-6，2026-10-27 业主批准）。每个域都遵守；
#: 各域多出来的码（`3`/`4`/`5`）只是把这三条之外的"下一步谁动"说细，不许改变这三条。
EXIT_CODE_UNIFIED: dict[int, str] = {
    0: "查过、结论是好（做完了 / 达标 / clean）",
    1: "查过、结论是坏或出事了（被拦住 / 行为异常 / 有人叫停且判据认为该报失败）",
    2: "没查成（三态里的 unknown：不是好，也不是坏）",
}

#: 域 × 码 → 一句话含义（`R-BE1` 的 ③-6，2026-10-27 业主批准）。
#:
#: 为什么要这张表：同一个 `1` 在四条命令里含义不同（loop 是"行为异常"、pipeline 是
#: "预算熔断"、gate 是"被 M 拦住"、门禁是"requires_human"），而此前这件事只散在四处
#: docstring 的散文里 —— 没有一处能对拍，于是"同码不同义"既看不出来也测不出来。
#:
#: 两条纪律：
#: 1. `3` / `4` / `5` 只许出现在 `loop` 域。它们回答的是"下一步谁动"（等用户 /
#:    加钱或等人 / 它自己判定收工），并进 `1` 会把"等用户"读成"出事"。
#: 2. 每个域都必须给出 `0` / `1` / `2` 三格，且三格的话互不相同（:data:`EXIT_CODE_UNIFIED`
#:    是它们共同的上位口径）。判据 `tests/test_exit_codes_have_one_meaning_per_domain.py`
#:    从本表取期望值，产出方（`cli` / `runflow` / `closing` / `cmd_stats`）的码集必须
#:    落在自己那一档里。
#:
#: 同码不同义的那几处是刻意的，写在理由里而不是抹平：
#: - `pipeline.budget_exhausted ⇒ 1`：管线域没有"下一轮可续"这个概念（`agentflow run`
#:   一次跑完就结束），预算熔断在脚本里就该被当失败；而 loop 域 `budget ⇒ 4` 回答的是
#:   "加钱或等人就能续"。把两者统一会毁掉其中一个语义。
#: - `loop.stop_file / force_stop / interrupted_by_parent ⇒ 4`：停意是外面叫的，
#:   与"循环自己判定该收工"（5）分属两条处置路径。
EXIT_CODE_DOMAINS: dict[str, dict[int, str]] = {
    # 单趟循环与多轮驱动（`agentflow run-agent` / `--rounds N`）。表体在 `STOP_REASONS`。
    "loop": {
        0: "正常完成（给了 final）",
        1: "行为异常（只留给真出事；未登记的停止理由也落这里，好让它当场可见）",
        2: "研究启动失败（一步模型都没调就交回去了）",
        3: "等待用户（人答完 --resume 接着跑）",
        4: "正常且中途停止：用户 / 父 / 钱叫停（含 budget）",
        5: "正常且自行停止但没有 final（原地打转 / escalated / final_refused）",
    },
    # `agentflow run`：检索→抽取→跑题的管线，一次跑完就结束。表体在
    # `runflow._exit_code_for`。
    "pipeline": {
        0: "本次运行确实产出了东西（哪怕最后一轮超时）",
        1: "行为异常：预算熔断（budget_exhausted）或未归类的结局 —— 管线域没有下一轮可续",
        2: "没查成：没 key / 检索没查成 / 网关违约等 NOT_CHECKED 结局",
    },
    # `agentflow closing`：收工门。表体在 `closing.tri_state_exit_code`。
    "gate": {
        0: "M 判达成（can_close）",
        1: "被拦住（M 判了没达成）",
        2: "没人判过（没有 m_verdict ⇒ 没查成）",
    },
    # `agentflow stats`：只读读数（不是判据，所以没有 1）。表体在 `cli.cmd_stats`。
    "readout": {
        0: "查过了（含全 0）",
        2: "没查成（任一来源 unknown）",
    },
    # 发布/审计门禁（`scripts/noai_gate.py` 与 `tools/release_all.py` 的步骤表）。
    "gate_runner": {
        0: "clean（查过了、没问题）",
        1: "查过了、结论是坏的（requires_human / 某一步没过）",
        2: "没查成（清单读不到 / 不在 git 仓库 / 没给改动集）",
    },
}

#: reason -> (退出码, 徽标 class, 徽标文案, live)。
#:
#: 退出码的六档口径（业主 2026-10-19）：0 正常完成 · 1 行为异常 · 2 研究启动失败 ·
#: 3 等待用户 · 4 正常且中途停止（用户 / 父 / 钱叫停） · 5 正常且自行停止但没有 final。
#: 全仓的上位口径与"同码不同义"的登记见 :data:`EXIT_CODE_UNIFIED` / :data:`EXIT_CODE_DOMAINS`。
#: `live=False` 的条目退出码写 `None`：它们只有徽标，不该进退出码表。
#:
#: 徽标 class 只用改前表里那四种（`badge-pass` / `badge-unknown` / `badge-pending` /
#: `badge-fail`），页面的 CSS 里都有定义。
STOP_REASONS: dict[str, tuple[int | None, str, str, bool]] = {
    # ---- 0 正常完成（给了 final）
    "final": (0, "badge-pass", "跑完", True),
    # ---- 3 等待用户（人答完 --resume 接着跑）
    "waiting_for_user": (3, "badge-pending", "停在等用户", True),
    # ---- 2 研究启动失败（连跑都没开始）：一步模型都没调就交回去了
    "checkpoint_mismatch": (2, "badge-fail", "检查点指纹不符", True),
    "no_checkpoint": (2, "badge-fail", "检查点读不到", True),
    "already_finished": (2, "badge-unknown", "上一趟已收工", True),
    "resume_no_transcript": (2, "badge-fail", "续跑重建不出记录", True),
    # ---- 4 系统行为正常且中途停止：有人（用户 / 父 / 钱）把它叫停
    "budget": (4, "badge-unknown", "预算用尽", True),
    "stop_file": (4, "badge-unknown", "用户叫停（开关文件）", True),
    "force_stop": (4, "badge-unknown", "用户强停", True),
    "ask_cancelled": (4, "badge-unknown", "问用户的等待被取消", True),
    # `interrupted_by_parent`：父对一个孩子当前轮次下的 `stopctl.request_interrupt`
    # 默认理由码（`stopctl.INTERRUPT_REASON`）。归 4 而不是 5：停意是外面叫的
    # （父是受权的叫停者，与"用户叫停"同一族），不是循环自己判定该收工。
    "interrupted_by_parent": (4, "badge-unknown", "被父叫停", True),
    # ---- 5 系统行为正常且自行停止，但没有 final
    "no_progress_limit": (5, "badge-unknown", "原地打转", True),
    "escalated": (5, "badge-pending", "已上报召唤者", True),
    # `final_refused`（D-68，业主 2026-10-26）：收工门判整棵树没销干净 ⇒
    # `run.final` 留空、循环自己 break。归 5 而不是 1：门按设计挡住了，没有东西坏掉；
    # 下一步是"先销号，再 --resume 重发 final"，不是去查模型故障。
    "final_refused": (5, "badge-unknown", "收工被拒（树未销净）", True),
    # `max_steps`（裁定 12-K 之前的历史读数）：循环今天不再产生它，但旧会话记录里
    # 真有。只有徽标、没有退出码；旧会话在退出码那一侧按未登记兜底成 1。
    "max_steps": (None, "badge-unknown", "步数用尽（旧读数）", False),
    # ---- 1 行为异常（只留给"真出事"）
    "not_wired": (1, "badge-fail", "没接线", True),
    "model_auth_failed": (1, "badge-fail", "模型没认这把 key", True),
    "model_timeout": (1, "badge-fail", "模型没返回（超时）", True),
    "model_unreachable": (1, "badge-fail", "没连上模型（网络/DNS）", True),
    "model_output_limit": (1, "badge-fail", "思考吃光输出预算", True),
    "bad_json_limit": (1, "badge-fail", "坏 JSON 连击", True),
    "bad_args_limit": (1, "badge-fail", "坏参数连击", True),
    # `no_notify`：L-05e 之后循环不再产生它，但退出码 1 是既有登记（旧会话记录
    # 仍按"协议不遵"解释），所以它留在退出码表里，与本单的 max_steps 不同。
    "no_notify": (1, "badge-fail", "收工没按格式留痕（旧读数）", True),
}

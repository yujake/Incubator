"""system 提示词的前缀稳定性：静态/动态分离、逐字节判据、缓存读数汇总。

## 这一层为什么存在（根因，逐个给代码位置）

上游的前缀缓存（DeepSeek 的 `prompt_cache_hit_tokens`）命中条件是**前缀逐字节相同**。
框架里 system 提示词是每一段对话的前缀，而它**每一步都重算**：

- `agent_loop.py:2940` 开局渲染一次（`AP.system_prompt(self.role, registry=..., **facts)`）；
- `agent_loop.py:3152` 每个步边界再过一次 `_system_at_step`（`:2808` 同一个渲染函数）。

（行号是 2026-10-19 的读数，会漂；名字不会。）

`_system_at_step` 的前身（改前那个每步重算 system 的实现）动机是对的（2026-10-15 的裁定 J=乙）：
`budget_left` 与 `notebook` 是模型据以决策的两个数，开局那一版是旧的。但它选的落点是
**system**，代价是「只要花销变了（几乎每一步都变），`TASK_BUDGET` 这一段的字节就变了
⇒ 整条前缀作废」。实测（`2026-10-19` 本机，非零价、M 岗）：

    第 0 步 system 54,902 字 / 第 1 步 system 54,902 字，identical=False
    从第 35,035 个字符起不同：`剩余预算：5.000000 美元（…已用 0.000000…）`
                          vs   `剩余预算：4.998800 美元（…已用 0.001200…）`

于是「命中缓存」这件事在结构上不可能发生 —— 不是概率低，是**永不**。

## 改法：静态/动态分离（本模块只给机制与判据，**不**做渲染缓存）

- 会变的事实（:data:`STEP_VOLATILE_FACTS` 登记表）**不再进 system**：
  :func:`split_facts` 把它们从 system 的事实里摘掉，换成一个**逐字节稳定**的静态替身
  （:data:`SYSTEM_PLACEHOLDERS`），并交给调用方塞进 **user 消息**
  （`agent_loop._prompt` 的尾部已经有「剩余花销预算」，本次补上「草稿本」）。

  ## 2026-10-21：登记的判据从「每步会变」扩成「**跨 run 会变**」

  前缀缓存命中的是"同一份前缀的第二次"。原来的登记表只收"每步会变"的两格
  （`budget_left` / `notebook`），于是**同一趟的第 2..N 步**能命中；而"另一趟活"
  的第一步永远命中不了 —— 因为 `AGENT_IDENTITY`（段序 0，整条提示词的最前面）
  逐字写着 `task_id` / `depth` / `children` / `parent_task_id` / `summoned_by`，
  而 `TASK_FRAME`（段序 4200）写着 `task` 正文 / `inbox` / `board` / `user_replies`。
  实测（`2026-10-21`，本机，M 岗）：两份"不同的活"的 system 从第 **95** 个字符起
  就不同（改前读数，见 `tests/fixtures/prompt_cache_warm.json` 的
  `cross_run_prefix_chars`）⇒ 换一趟活的第一次调用 `hit=0`。

  所以登记表收的是**所有跨 run 会变的事实**：它们在 user 消息里现读（开场那一条
  `agent_loop._opening_transcript` 逐格写着原值），system 里只留一段静态指路语。
  信息一个字没删 —— 判据（`tests/test_cross_run_prefix_is_reused.py`）既断言
  "system 里没有它"，也断言"user 消息里还有它"。
- system 里允许每步变化的段必须有登记（:data:`DYNAMIC_SECTION_WHITELIST`，初始为空）：
  :func:`unregistered_dynamic_sections` 扫"两份装配里变了的段名"，与登记表对比。
  没有登记却变了 ⇒ 判据红。这条守的是"以后有人往 system 里再塞一个每步会变的东西"
  —— 那正是今天这个 bug 的形态，而它不会自己报错。
- 逐字节判据在 :func:`step_stability`：同一角色、同一 task、同一 registry 下，
  连续两步的 system 必须**逐字节相同**；不同则报出"从第几个字符起不同 + 前后各 80 字"
  （:func:`first_difference`）。负控：往 system 里塞一个时间戳/步号 ⇒ 必红。

## 三态纪律（与 `llmseam` / `modelcost` 同一条）

缓存读数有第三态：上游**没给**这一格 ⇒ `None`（unknown）。折成 `0` 会让
「这家上游不报这一格」与「这次真的零命中」在读数上长得一模一样 ——
前者要改读数口径，后者要改提示词，处置方向相反。本模块所有汇总都把 unknown 单独计数，
命中率只按"给了读数的那几次调用"算，并在 `why` 里写明分母是哪一批。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping, Sequence

from . import modelcost as MC
from . import promptkit as PK

__all__ = [
    "DYNAMIC_SECTION_WHITELIST",
    "STEP_VOLATILE_FACTS",
    "SYSTEM_PLACEHOLDERS",
    "split_facts",
    "first_difference",
    "volatile_facts_digest",
    "facts_migration_problem",
    "step_stability",
    "stability_problem",
    "dynamic_sections",
    "unregistered_dynamic_sections",
    "prompt_cache_record",
    "summarize_prompt_cache",
    "cache_sentence",
    "missing_prompt_cache_steps",
    "cache_summary_problem",
    "checkpoint_prompt_cache_problem",
]

#: 一份缓存汇总（:func:`summarize_prompt_cache` 的产出）必须有的 11 个键。
#:
#: 为什么把键集也当判据：写这一格的落点有两个（`agent_run_end` 与
#: `agent_loop.save_run_checkpoint`），它们的形状**都**来自 :func:`summarize_prompt_cache`。
#: 有人另拼一份 dict 时（2026-10-19 的 `runs/agent-*.json` 就是那种形态：只有 `spend`），
#: 少的不止是 `hit`/`miss` —— 是整格。键集判据让"少一格"当场可见。
CACHE_SUMMARY_KEYS: tuple[str, ...] = (
    "calls", "no_request_calls", "hit", "miss", "unknown_calls", "tokens_in",
    "hit_rate", "mismatched_calls", "saved_usd", "saved_unknown_calls", "why",
)

#: 允许出现在 system 提示词里、**且允许每步变化**的段名（登记表）。
#:
#: 初始为空：静态/动态分离之后，system 里不该有任何一格随步变化。
#: 新增一个"必须在 system 里、又必须每步变"的内容 ⇒ 在这里登记它的**段名**，
#: 否则 `tests/test_prompt_stability.py` 的段判据会红（那正是我们要的：让新增的
#: 动态内容必须经过一次显式决定，而不是悄悄把前缀缓存废掉）。
DYNAMIC_SECTION_WHITELIST: frozenset[str] = frozenset()

#: 会变、因而**不许**进 system 的事实键（登记表：键 → 根因所在处）。
#:
#: 「会变」这一句话有**两根轴**，两轴都收（2026-10-21 起，判据见模块开头那一段）：
#:
#: | 轴 | 判据 | 收进来的键 |
#: |---|---|---|
#: | 每步会变 | 谁在步边界上被现算 | `budget_left` / `notebook`（`_prompt` 每步现读） |
#: | 跨 run 会变 | 谁在 `run()` 开头被**重新**算一次 | task 正文 / `task_id` / `depth` / `parent_task_id` / `summoned_by` / `children` / `board` / `inbox` / `user_replies` / `workspace_root` |
#: | 跨 run 会变（配置轴） | 谁随**这一趟的配置**变 | `availability`（伙伴配置）/ `parent_limits`（`Policy`：墙钟 / 预算 / 四类上限） |
#:
#: 为什么第三轴也收（2026-10-21 第二批）：前两轴收的是"换一趟**活**"，这一轴收的是
#: "换一份**配置**"。而"配置"与"活"在上游缓存眼里没有区别 —— 都是另一份前缀。
#: 实测（本机，M 岗）：`availability` 两份不同的读数让 system 从第 32,568 / 51,935
#: 字符（62.7%）处断开，`parent_limits` 让它从第 ~88% 处再断一次 ⇒ 换一次伙伴配置
#: 就砍掉 37% 的前缀。它们现在的落点与前十格同一个（开场那条 user 消息）。
#:
#: 为什么第二轴也收：一趟之内逐字不变的东西，**换一趟就换一份**，而上游前缀缓存要的
#: 是"另一趟也能用同一段前缀"。只挪第一轴，换一趟活的第一次调用永远 `hit=0`
#: （改前实测：两份不同的活的 system 从第 95 个字符起不同）。
#:
#: 落点逐条（行号是 2026-10-21 的读数，会漂；**名字**不会）：
#:
#: - 模板那一侧全部在 `agent_prompts.role_prompt_registry` 里：`AGENT_IDENTITY`
#:   （段序 0）:`agent_prompts.py:8666`（`{{summoned_by}}` / `{{task_id}}`）、
#:   `:8670`（`{{depth}}`）、`:8674`（`{{parent_task_id}}`）、`:8686`（`{{children}}`）；
#:   `TASK_FRAME`（段序 4200）:`agent_prompts.py:8894`（`{{task}}`）、`:8898`（`{{inbox}}`）、
#:   `:8902`（`{{board}}`）、`:8906`（`{{user_replies}}`）、`:8910`（`{{notebook}}`）、
#:   `:8914`（`{{budget_left}}`）；`WORKSPACE_FACTS`（段序 10000）:`agent_prompts.py:9206`
#:   （`{{workspace_root}}`）。
#: - 值那一侧在 `agent_loop.run` 的 `facts = dict(...)`（`agent_loop.py:3610`）算一次，
#:   凡"这一次运行的事实"都在这张表里被重新算 ⇒ 它们都是"另一段前缀"。
#: - 现在的载体：每步会变的两格仍在 `_prompt` 尾部现读（`agent_loop.py:3106-3112`）；
#:   其余十二格在开场那一条 user 消息里（`agent_loop._opening_transcript`，
#:   `agent_loop.py:886`）—— 那是**消息**，不是前缀：换一趟活换的是消息，前缀照旧。
#:
#: ⚠️ 加一格之前先问：**换一趟活它会不会变？** 会 ⇒ 登记在这里（并在 user 消息里
#: 真写出来，否则就是"信息被删"）；不会 ⇒ 留在 system，它是可复用的前缀。
#: 刻意**没有**登记的几格（跨 run 会变但判据是"同一台机器"）：
#: `toolchain_facts` / `toolchain_formal`（段序 9000/9010：换机器才变）。
#: 它们若哪天变成"每趟都不一样"，判据（两条渲染逐字节比对 + 段白名单）会先红 ——
#: 那时再决定挪不挪。
#:
#: ⚠️ 2026-10-21 第二批把 `availability` / `parent_limits` **加进了**这张表（它们此前在
#: 上面那句"刻意没有登记"里）：判据从"同一台机器/同一份配置"改成了"**换一份配置**"，
#: 因为业主的口径是"换一次伙伴配置不该砍掉 37% 的前缀"。这两格的真值同样念在开场那条
#: user 消息里（`agent_loop._opening_transcript` 的「现在的接线态」/「派活上限」两栏）。
STEP_VOLATILE_FACTS: Mapping[str, str] = {
    "budget_left": (
        "`agent_loop._budget_text()`（`agent_loop.py:2752`）：读 `seam.spent_usd()` 现算"
        "余额 —— 每花一笔就变，所以它每一步都不同（真机读数：0.000000 → 0.001200）。"
    ),
    "notebook": (
        "`agent_loop.notebook_digest()`（`agent_loop.py:1421`）：`note` 是追加写盘的，"
        "这一步刚写进去的笔记下一步就该读得到 ⇒ 每一步都可能不同。"
    ),
    "task": (
        "`AGENT_LOOP.run` 的入参 `task`（`agent_loop.py:3610` 的 `facts` 里那一格）⇒ "
        "换一趟活就换一份正文；它在 system 里（`AGENT_IDENTITY`/`TASK_FRAME`）时，"
        "两份不同的活的公共前缀从第一个字符起就是 0。"
    ),
    "task_id": (
        "`AgentLoop.run(my_task_id=…)`（`agent_loop.py:3610`）：台账号每趟都新发一个 ⇒ "
        "改前它在 `AGENT_IDENTITY` 里，实测第 95 个字符就分家。"
    ),
    "depth": (
        "`AgentLoop.run(depth=…)`（`agent_loop.py:3610`）：同一个角色可能被顶层唤起"
        "（1）也可能被父代理唤起（2..N）⇒ 跨趟会变。"
    ),
    "parent_task_id": (
        "`AgentLoop._resolve_parent`（`agent_loop.py:3544`）：父的台账号每趟不同；"
        "顶层发起时是空串（渲染成一句缺省）。"
    ),
    "summoned_by": (
        "`AgentLoop.run(summoned_by=…)`（`agent_loop.py:3610`）：同一角色这次被用户唤起、"
        "下次被 M 唤起 ⇒ 跨趟会变。"
    ),
    "children": (
        "`AgentLoop._children_text()`（`agent_loop.py:3602`）：名册摘要按「这一趟开始那一刻」"
        "现读 ⇒ 换一趟活、派过不同的子代理，这一格就不同。"
    ),
    "board": (
        "`agent_loop.board_digest`（`agent_loop.py:3564`）：板项是活账 —— 换一趟活时"
        "挂在我名下的项不同（消掉的、新派的都在动）。"
    ),
    "inbox": (
        "`agent_loop.inbox_digest`（`agent_loop.py:3559`）：收件箱每趟都不同（新留言会到、"
        "旧的会被窗口挤掉），且在 system 里时它把「这一趟听到什么」编进了前缀。"
    ),
    "user_replies": (
        "`userio.read_replies`（`agent_loop.py:3566` 经 `AP.user_replies_digest`）："
        "用户答过的问题是盘上的活账 ⇒ 换一趟活一般就多/少了回答。"
    ),
    "workspace_root": (
        "`AgentLoop.run` 的 `workspace_root`（`agent_loop.py:3614`）：换个项目/工作区就换一个"
        "根目录 ⇒ 它此前在 `WORKSPACE_FACTS`（段序 10000，system 的倒数第二段）里，"
        "是 cross-run 前缀的最后一处断点。"
    ),
    "availability": (
        "`host.wiring_status(store)`（`host.py:633` → `agent_loop` 的 `facts['availability']`）："
        "读的是**这一份伙伴配置**（谁配了 provider / key）⇒ 换一份配置就是另一份读数。"
        "它此前在 `PARTNER_AVAILABILITY`（段序 4520）里，本机实测：两份不同的接线态让"
        "M 的 system 从第 32,568 / 51,935 字符（62.7%）处断开 —— 换配置就砍掉 37% 的前缀。"
    ),
    "parent_limits": (
        "`AP.parent_limits_text(policy, role, depth=…)`（段序 5210 那一段的数字部分）："
        "`cli.py` 每趟用 `Policy(wall_clock_sec=…, usd_budget=…)` 现造那个 Policy ⇒ "
        "墙钟 / 预算 / 四类上限换一次 run 就可能换一份数字，而这一段在 M 的 system 里"
        "位于第 ~88% 处（第二个断点）。"
    ),
}

#: 每一格进 system 时用的**静态替身**（同一个角色 / 任务 / registry 下逐字节相同）。
#:
#: 为什么是"指路"而不是"冻结一个旧值"：冻结旧值会让 system 说一句**假话**
#: （"还剩 5.0 美元"而实际 4.9），而模型会照它决策；指路则是真话 ——
#: 那个值在 user 消息里现读，模型照样看得见，只是**不在前缀里**。
#:
#: 两条纪律（加一格时必须同时满足，判据会逐条读）：
#:
#: 1. **逐字节稳定**：同一个角色任何两趟渲染出来的这一段必须一字不差
#:    （不写数字、不写台账号、不写时间）；
#: 2. **指得出真值在哪**：每一个替身都要写清"原值在哪条消息的哪一栏"，
#:    否则模型会以为这一格没有值（那是"信息被删"，不是"换了位置"）。
SYSTEM_PLACEHOLDERS: Mapping[str, str] = {
    "budget_left": (
        "见每步消息末尾的「剩余花销预算」（那个数每一步现读 —— 花销一直在涨；"
        "这一格刻意不写数字：system 是每一步的前缀，写进一个会变的数会让前缀缓存永不命中）"
    ),
    "notebook": (
        "见每步消息末尾的「草稿本」（每一步现读 —— 它是追加写的；"
        "这一格刻意不抄内容：同上，前缀逐字节稳定才命中得了缓存）"
    ),
    "task": (
        "见本次对话第一条消息的「你的任务」（这一格刻意不写正文：system 是**整趟运行**的"
        "前缀，写进任务原文，换一趟活的第一条调用就一个 token 都命中不了）"
    ),
    "task_id": (
        "见本次对话第一条消息的「台账号」（每趟运行由框架现发号；这一格刻意不写号："
        "写进来就等于把整条前缀绑死在这一趟上）"
    ),
    "depth": (
        "见本次对话第一条消息的「召唤链深度」（同一个角色可能被顶层唤起、也可能被父代理唤起；"
        "这一格刻意不写数字）"
    ),
    "parent_task_id": (
        "见本次对话第一条消息的「父代理台账号」（父是谁是这一趟的事实；这一格刻意不写号）"
    ),
    "summoned_by": (
        "见本次对话第一条消息的「由谁发起」（这次可能被用户唤起、下次被 M 唤起；"
        "这一格刻意不写名字）"
    ),
    "children": (
        "见本次对话第一条消息的「名册摘要」（那是这一趟开始那一刻的快照，见下面的用法；"
        "这一格刻意不抄名单：它是这一趟的事实，抄进 system 就废掉了跨趟的前缀复用）"
    ),
    "board": (
        "见本次对话第一条消息的「挂在你名下的工作项」（板是活账；"
        "这一格刻意不抄条目）"
    ),
    "inbox": (
        "见本次对话第一条消息的「你的收件箱」（留言每趟不同；这一格刻意不抄内容）"
    ),
    "user_replies": (
        "见本次对话第一条消息的「用户回答过的问题」（那是盘上的活账；这一格刻意不抄内容）"
    ),
    "workspace_root": (
        "见本次对话第一条消息的「工作区根目录」（换项目就换一个根；这一格刻意不写路径 —— "
        "路径一换，它后面那几段就再也不是同一段前缀）"
    ),
    "availability": (
        "见本次对话第一条消息的「现在的接线态」（它随**伙伴配置**变：谁配了 provider / key；"
        "这一格刻意不写状态 —— 写进来就等于把这一段前缀绑死在这一份配置上）"
    ),
    "parent_limits": (
        "见本次对话第一条消息的「派活上限」（四类上限与墙钟都是这一趟 run 的 Policy 现算的；"
        "这一格刻意不写数字 —— 换个 run 的配置就换一段前缀）"
    ),
}


# ---------------------------------------------------------------- 静态/动态分离
def split_facts(facts: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """把事实拆成 `(进 system 的, 进 user 消息的)`。

    进 system 的那一份里，:data:`STEP_VOLATILE_FACTS` 登记的每一格被换成
    :data:`SYSTEM_PLACEHOLDERS` 里那一段**静态**文本 —— 于是同一个角色 / 同一 registry 下，
    无论是"连续两步"还是"另外一趟活"，system 都**逐字节相同**
    （:func:`step_stability` 钉前一条，`tests/test_cross_run_prefix_is_reused.py` 钉后一条）。

    进 user 的那一份逐字保留原值（调用方负责把它念进 user 消息里：
    每步会变的两格在 `agent_loop._prompt` 尾部，其余十二格在开场的
    `agent_loop._opening_transcript`）。
    用 `dict(...)` 复制而不是原地改：调用方手上的那份 `facts` 还要给别处用
    （`prompt_audit` 之类），改它会制造"两个读者看到两份事实"。
    """
    system_facts = dict(facts)
    step_facts: dict[str, Any] = {}
    for key in STEP_VOLATILE_FACTS:
        if key not in facts:
            continue
        step_facts[key] = facts[key]
        system_facts[key] = SYSTEM_PLACEHOLDERS.get(key, "")
    return system_facts, step_facts


# ---------------------------------------------------------------- 逐字节判据
# ---------------------------------------------------------------- 事实登记表的版本痕迹
def volatile_facts_digest(mapping: Mapping[str, str] | None = None) -> tuple[int, str]:
    """`STEP_VOLATILE_FACTS` 的**键集**指纹：`(键数, sha256)`。

    ## 这一格为什么必须存在（事务三：堵审计射程的边界）

    `tests/test_agent_prompts.py` 的 `_FROZEN_PROMPT_DIGESTS` 按**缺省事实**渲染模板
    ⇒ 它钉的是"段文本"，钉不住"哪几格事实被挪出了 system"。上一批把登记表从 2 格扩到
    12 格（`2026-10-21`）时，十格摘要一个都没变 ⇒ 那条判据没红、也没抬版本，而
    **提示词里模型看到的落点整个换了一遍**（从 system 挪进 user 消息）。
    审计射程到此为止 —— 这条函数就是补上的那一格读数。

    ## 为什么是"键集"而不是"值"

    值那部分（每一格为什么收进来）是会持续改写的散文（长注释、行号、真机读数）；
    键集才是**模型实际读到的结构**：少一格 = 那一格的事实被挪回了 system 或整段被删。
    于是指纹只对键集算，散文随便改都不会让判据红。

    `mapping` 只为让判据能喂替身进来做负控（缺省取模块级登记表）。
    """
    keys = tuple(sorted((STEP_VOLATILE_FACTS if mapping is None else mapping)))
    return len(keys), hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def facts_migration_problem(version: str, *, frozen: Sequence[Mapping[str, Any]],
                            mapping: Mapping[str, str] | None = None) -> str:
    """facts 迁移有没有**版本痕迹**？返回问题串（空 = 合格）。

    ## 口径（三态 + 一条纪律）

    纪律：**动 `STEP_VOLATILE_FACTS` 就必须动 `PROMPT_VERSION`**。理由与
    `_FROZEN_PROMPT_DIGESTS` 那条同源 —— 事后要回答"这句话是哪个版本的提示词说的"，
    而"哪几格事实在 user 消息里"是提示词的一部分（模型读到的落点变了）。

    判据（`frozen` 是一份**按顺序记的账本**，每一格是 `{version, count, keys_sha256}`）：

    - live 键集必须等于账本**最后一格** ⇒ 否则红（"facts 迁了而账本没记"）；
    - 最后一格的 `version` 必须等于 `PROMPT_VERSION` ⇒ 否则红（"迁了但没抬版本"）。

    账本里留着历史各格（不止最后一格）：被跨过的那几格正是"哪一次迁移没抬版本"的
    读数 —— 它们不参与判绿，但读的人看得见。
    """
    live = dict(mapping) if mapping is not None else dict(STEP_VOLATILE_FACTS)
    count, digest = volatile_facts_digest(live)
    if not frozen:
        return "账本是空的 ⇒ 没有任何一格键集被冻过，这条判据什么也没守"
    last = dict(frozen[-1])
    if int(last.get("count", -1)) != count or str(last.get("keys_sha256", "")) != digest:
        return (f"facts 迁移了而账本最后一格没记：live {count} 格 / {digest[:12]}… vs "
                f"账本 {last.get('count')} 格 / {str(last.get('keys_sha256'))[:12]}… ⇒ "
                f"改动 `STEP_VOLATILE_FACTS` 必须在账本里留一格，并把 `PROMPT_VERSION` 抬一格")
    if str(last.get("version", "")) != str(version):
        return (f"facts 迁移了而 PROMPT_VERSION 还是 {version!r}（账本最后一格说这次是 "
                f"{last.get('version')!r}）⇒ 事后分不清哪几格事实属于哪一版提示词")
    return ""


def first_difference(prev: str, cur: str, *, context: int = 80) -> dict[str, Any] | None:
    """两段文本第一处不同的读数；逐字节相同 ⇒ `None`。

    返回的 `index` 是**0 基**字符下标（同时给出 1 基的 `position`），
    两边各带"从 index-context 到 index+context"的原文 —— 报"第 35035 个字符起不同"
    而**不给那一段原文**的话，读的人还得自己去拉两份 54KB 的提示词重放一遍。
    """
    n = min(len(prev), len(cur))
    index = n
    for i in range(n):
        if prev[i] != cur[i]:
            index = i
            break
    if index == n and len(prev) == len(cur):
        return None
    lo = max(0, index - context)
    return {
        "index": index,
        "position": index + 1,
        "prev_chars": len(prev),
        "cur_chars": len(cur),
        "prev_char": prev[index] if index < len(prev) else "",
        "cur_char": cur[index] if index < len(cur) else "",
        "prev_context": prev[lo:index + context],
        "cur_context": cur[lo:index + context],
        "common_prefix_chars": index,
    }


def step_stability(prev: str, cur: str) -> dict[str, Any]:
    """连续两步 system 的稳定性读数（判据用它，运行时也用它落档）。

    `stable=True` 是**唯一**允许的结局：`reason` 空串；否则 `reason` 是一句人话
    （含"从第几个字符起不同"），`first_diff` 带上前后各 80 字。
    """
    diff = first_difference(prev, cur)
    return {
        "stable": diff is None,
        "prev_chars": len(prev),
        "cur_chars": len(cur),
        "first_diff": diff,
        "reason": "" if diff is None else stability_problem(prev, cur, diff=diff),
    }


def stability_problem(prev: str, cur: str, *,
                      diff: Mapping[str, Any] | None = None) -> str:
    """一句可读的"为什么这两步的 system 不是同一段前缀"（空串 = 稳定）。"""
    d = dict(diff) if diff is not None else first_difference(prev, cur)
    if not d:
        return ""
    return (f"system 从第 {d['position']} 个字符起不同（0 基 {d['index']}；"
            f"长度 {d['prev_chars']} vs {d['cur_chars']}）⇒ 前缀缓存必然不命中。\n"
            f"  这一步之前：…{d['prev_context']!r}…\n"
            f"  这一步之后：…{d['cur_context']!r}…")


# ---------------------------------------------------------------- 段级判据（白名单）
_VAR = re.compile(r"\{\{([^{}]+)\}\}")


def _section_inputs(assembly: PK.Assembly, section: PK.Section,
                    ) -> tuple[str, dict[str, str]]:
    """一段的"输入面"：模板文本 + 它引用的变量在这次装配里的值。

    为什么比这两样而不是比渲染结果：渲染就是 `插值(模板, 变量)`（`promptkit.py:271-281`），
    于是「渲染结果不同」⟺「模板不同 **或** 某个被引用变量的值不同」。比输入面能
    **点名**是哪一段变了；比渲染结果只能知道"整份提示词变了"。
    （唯一的例外是"模板是可调用对象、它读了外部状态"：那种段由逐字节判据兜底。）
    """
    template = section.text if isinstance(section.text, str) else section.text(assembly.scope)
    used = sorted(set(_VAR.findall(template)))
    return template, {name: assembly.variables.get(name, "") for name in used}


def dynamic_sections(prev: PK.Assembly, cur: PK.Assembly) -> list[str]:
    """两份装配之间**变了的段名**（按规范化顺序）。空列表 = 没有段随这次差异而变。"""
    by_name_prev = {s.name: s for s in prev.sections}
    by_name_cur = {s.name: s for s in cur.sections}
    out: list[str] = []
    for name in prev.names:
        b = by_name_cur.get(name)
        if b is None:
            out.append(name)          # 这一段被删了 —— 当然算"这一段变了"
            continue
        if _section_inputs(prev, by_name_prev[name]) != _section_inputs(cur, b):
            out.append(name)
    for name in cur.names:
        if name not in by_name_prev:
            out.append(name)          # 这一段是新加的
    return out


def unregistered_dynamic_sections(prev: PK.Assembly, cur: PK.Assembly,
                                 *, whitelist: Iterable[str] | None = None,
                                 ) -> list[str]:
    """变了的段里**没有登记**的那些（判据红的就是这个列表非空）。

    `whitelist` 缺省取 :data:`DYNAMIC_SECTION_WHITELIST`（模块级登记表）；显式给一份
    只为让判据自己能被负控（"登记了 ⇒ 绿"那一跳）。
    """
    allowed = set(DYNAMIC_SECTION_WHITELIST if whitelist is None else whitelist)
    return [name for name in dynamic_sections(prev, cur) if name not in allowed]


# ---------------------------------------------------------------- 缓存读数
def prompt_cache_record(call: Any) -> dict[str, Any]:
    """一次模型调用的缓存读数（进这一步的 `step` 记录）。

    字段名**照抄上游**（`prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`）：
    于是"这一步上游报的命中数是多少"可以直接拿上游字段名去 grep 会话记录，
    不必先知道我们中间改过什么名字。

    三态照抄：`hit` / `miss` 为 `None` = 上游没给这一格（unknown），**不许折成 0**。
    另外还有"第零态"：`called=False` = 这一次**根本没发请求**（没接线 / 预算已尽，
    见 `llmseam.SeamCall.requested`）—— 它连"上游没给读数"都谈不上，所以单独一格，
    不许并进 `unknown_calls`（那会让"上游不报这格"与"一个请求都没发"同形）。

    `cache_tri` 抄 `modelcost.billing_reading` 的那一格口径（`billed` /
    `not_reported` / `price_unknown`），于是"命中率低"与"这一档价没登记"分得开。
    计价三格（`usd_per_m_in*`）也一并抄下来：汇总时按**当时那一档价**算可省金额，
    而不是拿汇总那一刻的价去重算历史调用。
    """
    billing = dict(getattr(call, "billing", None) or {})
    hit = getattr(call, "cache_hit_tokens", None)
    miss = getattr(call, "cache_miss_tokens", None)
    called = bool(getattr(call, "requested", True))
    return {
        "called": called,
        "why": "" if called else str(getattr(call, "problem", "") or "没有发请求"),
        "prompt_cache_hit_tokens": None if hit is None else int(hit),
        "prompt_cache_miss_tokens": None if miss is None else int(miss),
        "tokens_in": int(getattr(call, "tokens_in", 0) or 0),
        "tokens_out": int(getattr(call, "tokens_out", 0) or 0),
        "known": called and hit is not None and miss is not None,
        "cache_tri": str(billing.get("cache_tri") or ("not_reported" if hit is None else "")),
        "usd_per_m_in": billing.get("usd_per_m_in"),
        "usd_per_m_in_hit": billing.get("usd_per_m_in_hit"),
        "usd_per_m_out": billing.get("usd_per_m_out"),
    }


def _hit_of(record: Mapping[str, Any]) -> int | None:
    """一条记录里的命中数（上游字段名；`None` = 上游没给，不是 0）。"""
    return record.get("prompt_cache_hit_tokens")


def _miss_of(record: Mapping[str, Any]) -> int | None:
    """一条记录里的未命中数（同上）。"""
    return record.get("prompt_cache_miss_tokens")


def _saved_usd_of(record: Mapping[str, Any]) -> float | None:
    """这一次调用因为命中缓存少花了多少（`modelcost.usd_for` 的两个差，不自己造价）。

    口径就是 `modelcost.py:415-432` 的那一条：命中部分按 `usd_per_m_in_hit`、
    未命中部分按 `usd_per_m_in`。于是"可省金额" = 用同一份价、同一个 `usd_for`
    算两次（一次带命中、一次当全部未命中）的差 —— 单价与公式都只有一份来源。
    算不出来就 `None`（命中价没登记 / 上游没给读数），不是 0。
    """
    hit = record.get("prompt_cache_hit_tokens")
    tokens_in = int(record.get("tokens_in") or 0)
    if hit is None:
        return None
    p_in = record.get("usd_per_m_in")
    p_out = record.get("usd_per_m_out")
    p_hit = record.get("usd_per_m_in_hit")
    if p_in is None or p_out is None or p_hit is None:
        return None
    if not hit:
        return 0.0
    from .modelgw import ModelReply     # 惰性：`usd_for` 要的就是这个形状

    price = MC.Price(usd_per_m_in=float(p_in), usd_per_m_out=float(p_out),
                     usd_per_m_in_hit=float(p_hit))
    tokens_out = int(record.get("tokens_out") or 0)
    with_hit = MC.usd_for(ModelReply(ok=True, tokens_in=tokens_in, tokens_out=tokens_out,
                                     cache_hit_tokens=int(hit),
                                     cache_miss_tokens=max(0, tokens_in - int(hit))), price)
    no_hit = MC.usd_for(ModelReply(ok=True, tokens_in=tokens_in, tokens_out=tokens_out,
                                   cache_hit_tokens=None, cache_miss_tokens=None), price)
    return round(no_hit - with_hit, 6)


def summarize_prompt_cache(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """一趟运行的缓存汇总（`LoopRun.prompt_cache`，落进 `agent_run_end`）。

    字段：
    - `calls` 有读数的调用数；`hit` / `miss` 只在**给了读数**的那些调用上求和；
    - `unknown_calls` 上游没给读数的调用数（第三态，绝不并进 0）；
    - `hit_rate` = hit/(hit+miss)，**分母只含给了读数的那几次**；都为 0/无 ⇒ `None`；
    - `mismatched_calls` = `hit + miss != tokens_in` 的次数（自洽判据，见下）；
    - `saved_usd` / `saved_unknown_calls`：按 `modelcost.usd_for` 口径估算的可省金额，
      算不出来的那几次单独计数（不是按 0 累加）。

    为什么 `mismatched_calls` 必须有一格：上游的 `usage` 里这两格与 `prompt_tokens`
    理论上相等，而"不等"意味着我们读错了字段或者上游口径变了 —— 那会让
    `hit_rate` 这个数字本身失效。把它当读数报出来，而不是在这里替上游"抹平"。
    """
    hit = miss = tokens_in = 0
    unknown = mismatched = 0
    saved = 0.0
    saved_unknown = 0
    calls = 0
    no_request = 0
    for rec in records:
        if not rec:
            continue
        # 第零态：没发请求的那几次不算"调用"，也不进 unknown（见 `prompt_cache_record`）。
        if not rec.get("called", True):
            no_request += 1
            continue
        calls += 1
        h, m = _hit_of(rec), _miss_of(rec)
        tin = int(rec.get("tokens_in") or 0)
        tokens_in += tin
        if h is None or m is None:
            unknown += 1
        else:
            hit += int(h)
            miss += int(m)
            if int(h) + int(m) != tin:
                mismatched += 1
        got = _saved_usd_of(rec)
        if got is None:
            saved_unknown += 1
        else:
            saved += got
    known = hit + miss
    why: list[str] = []
    if calls == 0 and no_request:
        why.append(f"这一趟有 {no_request} 次没发请求（没接线 / 预算已尽）"
                   "⇒ 没有命中率可算（不是 0%）")
    elif calls == 0:
        why.append("这一趟没有模型调用 ⇒ 没有命中率可算（不是 0%）")
    elif known == 0:
        why.append("上游一次都没给缓存读数 ⇒ 命中率 unknown（不是 0%）")
    elif unknown:
        why.append(f"命中率的分母只含给了读数的 {calls - unknown} 次调用"
                   f"（另有 {unknown} 次 unknown）")
    if saved_unknown:
        why.append(f"可省金额有 {saved_unknown} 次算不出来（命中价没登记或上游没给读数）")
    if mismatched:
        why.append(f"有 {mismatched} 次 hit+miss ≠ tokens_in ⇒ 这两格的读数口径可疑")
    return {
        "calls": calls,
        "no_request_calls": no_request,
        "hit": hit,
        "miss": miss,
        "unknown_calls": unknown,
        "tokens_in": tokens_in,
        "hit_rate": (round(hit / known, 4) if known else None),
        "mismatched_calls": mismatched,
        # 一次都算不出来 ⇒ `None`（不是 0）；算得出的那些照常累加，算不出的单独计数。
        "saved_usd": (None if (not calls or saved_unknown == calls) else round(saved, 6)),
        "saved_unknown_calls": saved_unknown,
        "why": "；".join(why),
    }


def cache_sentence(summary: Mapping[str, Any]) -> str:
    """收工那一行用的一句人话（空串 = 没什么可说的）。"""
    if not summary:
        return ""
    calls = int(summary.get("calls") or 0)
    if not calls:
        return ("缓存读数：这一趟没有模型调用"
                + (f"（{summary['no_request_calls']} 次没发请求）"
                   if summary.get("no_request_calls") else ""))
    rate = summary.get("hit_rate")
    rate_text = ("unknown（上游没给读数）" if rate is None else f"{rate * 100:.1f}%")
    saved = summary.get("saved_usd")
    saved_text = ("unknown（命中价没登记 / 上游没给读数）" if saved is None
                  else f"约 {float(saved):.6f} 美元")
    out = (f"缓存读数：命中 {summary.get('hit')} / 未命中 {summary.get('miss')} token，"
           f"命中率 {rate_text}（{calls} 次调用"
           + (f"，其中 {summary.get('unknown_calls')} 次 unknown" if summary.get("unknown_calls")
              else "")
           + f"）；按 modelcost 口径估算可省 {saved_text}")
    if summary.get("why"):
        out += f"（{summary['why']}）"
    return out


def missing_prompt_cache_steps(events: Sequence[Mapping[str, Any]]) -> list[int]:
    """`agent_step` 事件里**缺** `prompt_cache` 那几格的步号（判据用；空 = 都写了）。

    三态纪律在这里也成立：`prompt_cache` 这个键**存在**、只是内容为 unknown
    （`hit` / `miss` 都是 `None`），与"这个键根本没有"是两件事 —— 后者是写入被删掉
    （本函数的猎物），前者是上游没给读数（合法的第三态）。

    ## 判据收在"两个上游字段名在不在"上，而不是"整个 dict 非空"（2026-10-19）

    为什么：`"prompt_cache": {}` 是"看起来写了、其实一格没落"的形态 —— 它在会话
    记录里有一个键，`event.get("prompt_cache") is not None` 也过得去，而
    `hit` / `miss` 两格根本不存在。unknown 那一档与它的区别恰恰是**字段名在、
    值是 `None`**（见 :func:`prompt_cache_record`）。所以猎物有两个：
    键不在（`{}` 也算），或者键在而两个字段名少一个。
    """
    missing: list[int] = []
    for event in events:
        if str(event.get("kind") or "") != "agent_step":
            continue
        cache = event.get("prompt_cache")
        ok = (isinstance(cache, Mapping)
              and "prompt_cache_hit_tokens" in cache
              and "prompt_cache_miss_tokens" in cache)
        if ok:
            continue
        # `index` 用 `is None` 判而不是 `or`：**第 0 步**的索引是 `0`，
        # 而 `0 or -1` 会把它写成 -1（真机里第 0 步恰恰最常见）。
        raw = event.get("index")
        missing.append(int(raw) if raw is not None else -1)
    return missing


def cache_summary_problem(summary: Any) -> str:
    """一份缓存汇总**自洽**吗？返回问题串（空 = 合格）。

    ## 为什么汇总也要一条判据（而不只是"算的时候小心点"）

    这一格的读者是"事后判断提示词改动值不值"的人。汇总若不自洽，那个判断就是假的，
    而它看起来完全正常（一个 0.91 的命中率与一个 0.00 的命中率长得一样可信）。
    所以判据要问的是三件事，逐条对应一种"看起来正常但是错"的形态：

    1. **形状**：11 个键一个不少（键集见 :data:`CACHE_SUMMARY_KEYS`）——
       少一格说明有人另拼了一份 dict，而不是走 :func:`summarize_prompt_cache`；
    2. **自洽**：`unknown_calls == 0` 时 `hit + miss == tokens_in`
       （上游的这两格与 `prompt_tokens` 理论上相等；不等 ⇒ 读数口径可疑）；
    3. **三态**：上游一次都没给读数时，`hit_rate` 必须是 `None`（绝不折成 0%），
       且 `why` 必须说明原因；`calls == 0` 同理（"没有调用"不是"零命中"）。

    注意 `hit` / `miss` 本身是**只在给了读数的那几次调用上求和**（`summarize_prompt_cache`
    的口径）：`unknown_calls > 0` 而 `hit + miss < tokens_in` 是合法的，
    所以第 2 条只在 `unknown_calls == 0` 时成立 —— 把它推广到所有情况会把
    "上游只报了一半"误判成"口径坏了"。
    """
    if not isinstance(summary, Mapping):
        return f"汇总不是一份 dict（{type(summary).__name__}）：{summary!r}"
    if not summary:
        return ("这一格是空的（`{}`）：没算过汇总 —— 收工那一刻写的记录不该是空的，"
                "而'没算过'与'算过但上游没给读数'必须分得开")
    missing = [k for k in CACHE_SUMMARY_KEYS if k not in summary]
    if missing:
        return f"汇总少了 {missing} 这几格（键集见 `CACHE_SUMMARY_KEYS`，{len(CACHE_SUMMARY_KEYS)} 个）"
    calls = int(summary.get("calls") or 0)
    unknown = int(summary.get("unknown_calls") or 0)
    hit, miss = summary.get("hit"), summary.get("miss")
    tokens_in = int(summary.get("tokens_in") or 0)
    rate = summary.get("hit_rate")
    if calls < 0 or unknown < 0 or unknown > calls:
        return f"calls={calls} / unknown_calls={unknown} 不成比例"
    if calls == 0:
        if rate is not None:
            return f"没有一次模型调用，却给出了命中率 {rate!r}（该是 None）"
        if not str(summary.get("why") or "").strip():
            return "没有一次模型调用，却没写 `why` 说明为什么没有命中率"
        return ""
    if unknown == calls:
        # 全部 unknown：命中的和必须是 0（没有一次给了读数），而"0 命中"不许变成 0%。
        if int(hit or 0) or int(miss or 0):
            return (f"全部 {calls} 次调用都是 unknown，`hit`/`miss` 却是 "
                    f"{hit}/{miss}（这两个和只该含给了读数的那几次）")
        if rate is not None:
            return (f"全部 {calls} 次调用都是 unknown，命中率却是 {rate!r} —— "
                    "unknown 不许折成 0%")
        if not str(summary.get("why") or "").strip():
            return f"全部 {calls} 次调用都是 unknown，却没写 `why` 说明"
        return ""
    if unknown == 0:
        if int(hit) + int(miss) != tokens_in:
            return (f"hit({hit}) + miss({miss}) = {int(hit) + int(miss)} ≠ tokens_in({tokens_in})："
                    "这两格与 prompt_tokens 该相等，不等说明读数口径可疑")
        if rate is None:
            return f"有 {calls} 次调用都给了读数，命中率却是 None"
        return ""
    # 混合档：有读数的那些求和，unknown 单独计数 —— 但和不能超过 tokens_in。
    if int(hit) + int(miss) > tokens_in:
        return f"hit({hit}) + miss({miss}) > tokens_in({tokens_in})：读数不自洽"
    if rate is None:
        return f"有 {calls - unknown} 次调用给了读数，命中率却是 None"
    return ""


def checkpoint_prompt_cache_problem(checkpoint: Any) -> str:
    """检查点（`runs/agent-<角色>-<sid>.json`）里的缓存读数合格吗？返回问题串（空 = 合格）。

    三态在**这一层**的落点：
    - 键**不在** ⇒ 写入被删掉（2026-10-19 之前的形态：这份文件只有 `spend`）；
    - 键在、值 `{}` ⇒ 写的时候没有汇总可写（"没算过"，不是"零命中"）；
    - 键在、值是汇总 ⇒ 交给 :func:`cache_summary_problem` 逐条核对自洽。

    为什么这条判据必须在：`run_role` 收工时**只**写这份文件（产出文件
    `runs/<角色>-<时间戳>-<序号>.json` 只在被召唤那条路上写），所以它是顶趟
    "这一趟花了多少 / 省了多少"在盘上的唯一落点。
    """
    if not isinstance(checkpoint, Mapping):
        return f"检查点不是一份 dict（{type(checkpoint).__name__}）：{checkpoint!r}"
    if "prompt_cache" not in checkpoint:
        return ("检查点里没有 `prompt_cache` 这一格 —— 这一趟的缓存读数只落在会话记录的 "
                "`agent_run_end` 里，而顶趟的产出文件并不在 `runs/` 下")
    return cache_summary_problem(checkpoint.get("prompt_cache"))

"""判据：提醒 3 次 / 判停 5 次（裁定 10丙）+ 进度计数按委托记账（裁定 12-F）。

## 这一批判的两件事

1. 两档分开（裁定 10丙 逐字「提醒3次、判停5次」）：同一调用连到第 3 次 ⇒ 出提醒但循环继续；
   连到第 5 次 ⇒ `no_progress_limit` 收工。改前判停是 6，而且"提醒过没有"与"停没停"
   共用 `dead_loop_max` 一个读数（`draft/100` S-D 的读数那一格）。
2. 计数按委托记账（裁定 12-F + 业主补充逐字：「只有主控会和用户交互，其余子代理不会和用户交互，
   适应性地改为每做完一个委托清一次」）：三个计数（同一个调用 / 同一个读数 / 同一条路）
   的账只属于这一次委托 —— 换委托、或主控收到用户新消息时清零；
   父代理一条普通留言不清（留言不是新委托）。

## 判据形态

`agent_loop` 的这两条阈值是声明，而"连击怎么数、什么时候清"是行为 ——
所以这里两头都判：声明面（数字与散文一致）与行为面（真跑一个循环、读它落的事件与读数）。
"""

from __future__ import annotations

import pathlib
import re

from agentflow import agent_loop as AL
from agentflow import agent_prompts as AP

#: 判停那一句在散文里的词表：`连着` + 若干字（可能夹着加粗的星号）+ 数字 + `次同样的调用`。
#:
#: 为什么要留出那"若干字"：p207（2026-10-27，提交 `9147277`）把 `PARENT_STOP` 里那一句
#: 重写成「连着（加粗）5 次同样的调用 + 同样的读数」这一趟才以 `no_progress_limit` 收工
#: —— 判停那一档补上了"同样的读数"这个限定（裁定 10丙 的另一半），措辞也加粗了。
#: 逐字找"连着 5 次"于是再也找不到：散文没有丢掉那个数字，丢的是旧判据认识的写法。
#: 同一次提交里 `agent_prompts.prompt_text_problems()` 已经把口径钉成
#: `f"{stop} 次同样的调用"`（本文件的那条判据是唯一没跟上的读者）。
_STOP_CLAUSE = re.compile(r"连着[^\n]{0,16}?(\d+)\s*次同样的调用")


def test_the_two_thresholds_are_three_and_five() -> None:
    """正控（声明面）：提醒 3、判停 5，且提醒严格在判停之前。"""
    loop = AL.AgentLoop
    assert loop.dead_loop_nudge == 3, loop.dead_loop_nudge
    assert loop.max_dead_loop == 5, loop.max_dead_loop
    # 反真空：两个数不许相等/倒挂 —— 相等就意味着"提醒的那一步同时判停"。
    assert loop.dead_loop_nudge < loop.max_dead_loop, (loop.dead_loop_nudge, loop.max_dead_loop)


def test_the_prompt_says_the_same_number_as_the_code() -> None:
    """正控（散文与代码一致）：提示词里那个数字必须等于 `max_dead_loop`。

    为什么值得一条判据：这个数写在两处（`agent_loop` 的参数与提示词里的散文），
    而"改了一处忘了另一处"是本项目的经典形态（改前那句散文写的就是 6）。

    ## 2026-10-26（p207 抬版本）之后：按词表现取，不再逐字找"连着 5 次"
    改前这一条找的是 `f"连着 {max_dead_loop} 次"`（逐字），而 p207 把那一句改成
    「连着（加粗）5 次同样的调用 + 同样的读数」这一趟才以 `no_progress_limit` 收工：
    数字还在、而且判停的条件说得更严（同样的调用 + 同样的读数），只是写法变了。
    所以这里改成从那一句里现取数字（`_STOP_CLAUSE` 允许中间夹着加粗标记），
    并补上改前漏掉的两条 —— 判停那一句必须写明"同样的读数"（判停不只是"同一个调用"），
    并且必须与理由码 `no_progress_limit` 同句。它守的仍然是同一件事：
    散文里那个数等于代码里的 `max_dead_loop`，且旧的那个 6 不许回来。
    """
    text = "\n".join(_prompt_texts())
    found = _STOP_CLAUSE.search(text)
    assert found, f"散文里找不到「连着…次同样的调用」那一句：{text[:400]}"
    assert int(found.group(1)) == AL.AgentLoop.max_dead_loop, (
        found.group(0), AL.AgentLoop.max_dead_loop)
    line = next((ln for ln in text.splitlines() if found.group(0) in ln), found.group(0))
    assert "同样的读数" in line, line
    assert "no_progress_limit" in line, line
    assert "连着 6 次" not in text, "散文里还留着旧的 6：改了一处忘了另一处"
    assert f"连着第 {AL.AgentLoop.dead_loop_nudge} 次" in text, "提醒那一档的 3 也要在散文里"


def _prompt_texts() -> list[str]:
    """装配出来的十格提示词里所有出现"原地打转"那一段的文本（现算，不手抄）。"""
    out: list[str] = []
    try:
        from agentflow import agent_prompts as AP2

        for role in AP2.ALL_ROLES if hasattr(AP2, "ALL_ROLES") else ():
            out.append(str(AP2.system_prompt(role) if hasattr(AP2, "system_prompt") else ""))
    except Exception:  # noqa: BLE001 —— 装配不可用时退回模块级文本池
        pass
    # 兜底：模块级常量里也含那一段（本判据不依赖装配成功，但装配成功时更真实）。
    for name in dir(AP):
        if name.isupper():
            value = getattr(AP, name)
            if isinstance(value, str):
                out.append(value)
    return out


def test_the_run_reads_the_two_bands_apart(tmp_path: pathlib.Path) -> None:
    """正控（读数面）：`LoopRun` 把"提醒了几次"与"因此停了没有"分成两个读数。

    改前这两个问题只有一个数（`dead_loop_max`）能回答。
    """
    run = AL.LoopRun(role="M", task="t-1")
    assert hasattr(run, "dead_loop_nudges") and hasattr(run, "dead_loop_stopped")
    assert hasattr(run, "stalled_nudges") and hasattr(run, "counters_reset_at")
    blob = run.to_dict()
    for key in ("dead_loop_nudges", "stalled_nudges", "dead_loop_stopped", "counters_reset_at"):
        assert key in blob, (key, sorted(blob))
    # 三态：默认是"没提醒过"(0) 与"没因此停"(False) —— 两个都是读数，不是缺省真假。
    assert blob["dead_loop_nudges"] == 0 and blob["dead_loop_stopped"] is False


def test_the_reminder_line_names_the_stop_threshold() -> None:
    """正控（提醒文本）：那句提醒里写的上限必须等于 `max_dead_loop`（它读的是同一个数）。"""
    line = AL._dead_loop_line(streak=3, same_reading=3, limit=AL.AgentLoop.max_dead_loop,
                              what="tool fs.read")
    assert str(AL.AgentLoop.max_dead_loop) in line, line

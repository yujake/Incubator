# -*- coding: utf-8 -*-
"""循环活性：同调用 + 同读数连着到上限 ⇒ 先点名、再到上限收工（`draft/37` §136）。

## 为什么需要这一组

T2 第 4 趟真机（`projects/p6d-research-from-zero`）的盘上读数：M 连着 9 次调
`conductor.ledger`、8 次调 `conductor.closing`、6 次写同一份 `ACCEPTANCE.md`
—— 那 23 步一步也没有产生新事实，而框架当时只有"步数/预算用尽"这两道闸，
它们能把一趟跑完，却说不出"你在原地打转"。这一组把这三件事钉住：

1. 同调用 + 同读数连着 `dead_loop_nudge`（3）次 ⇒ 那一步的结果里出现
   【没有新事实】的提醒，而循环继续（提醒不是判死）；
2. 连着 `max_dead_loop`（5，业主 2026-10-10 裁定 10丙）次 ⇒ 这一趟以 `no_progress_limit` 收工
   （不是 `max_steps`：两个停止理由说的是两件事），收工语写清"没有新事实"；
3. 读数在变的重问（轮询那种）与"只重复了两次"都不算打转 —— 判据不许把
   正当的重问判成原地打转（那是把一个读数折成两个结论的反面）。

夹具与 `tests/test_agent_loop.py` 同源（同一个替身模型、同一条接线）：
这里换的只是剧本与判据，接线一行没改。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

import test_agent_loop as TAL
from agentflow.agent_loop import run_role
from agentflow.llmseam import LlmSeam

#: 读一条静态读数（工作区状态驱动的工具，同样的参数 ⇒ 同样的读数）。
STATIC_CALL = {"tool": "conductor.role_spec", "args": {"role_name": "C"},
               "why": "复核一遍 C 的规格"}

#: 同一个调用而读数在变（`_ChangingGateway` 每一步都改那个文件）。
CHANGING_CALL = {"tool": "fs.read", "args": {"path": "out/counter.txt"},
                 "why": "看同伴铺到第几行了"}


def _reply(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


class _ChangingGateway(TAL.ScriptedGateway):
    """照剧本回答，但在每次回答之前把工作区里那个"被读的文件"改一次。

    用途：造出"同一个调用、读数在变"这一档。真机里那是并发的同伴在改盘
    （一个角色读台账，别的角色同时在往台账里写）—— 它不是假想：
    `draft/37` §136 的两种措辞就是为它分出来的（读数在变 ⇒ 不叫"没有新事实"）。
    """

    def __init__(self, replies: list[str], path: pathlib.Path) -> None:
        super().__init__(replies)
        self.path = path
        self.n = 0

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.n += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(f"第 {self.n} 次\n", encoding="utf-8", newline="")
        return super().complete(prompt, scope=scope, system=system, **kw)


def _run(tmp_path: pathlib.Path, replies: list[str], *, max_steps: int = 8):
    scripts = {"M": replies}
    st, cond, registry, gw, root = TAL._wired(tmp_path, scripts, max_steps=max_steps)
    return run_role("M", "别原地打转", store=st, registry=registry, conductor=cond,
                    seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                                 sid="test-run"), workspace_root=str(root), sid="test-run",
                    from_env=False)


def test_a_static_reading_is_identical_across_identical_calls(tmp_path: pathlib.Path):
    """夹具前提（判据的可判性）：这个工具的读数在同样参数下逐字不变。

    没有这一条，下面两条判据会变成"取决于那个工具恰不巧稳定"—— 判据的前提
    必须是判据自己测出来的，不是我以为的。
    """
    run = _run(tmp_path, [_reply(STATIC_CALL)] * 2 + [_reply({"final": "收工"})])
    readings = [json.dumps(s.result, ensure_ascii=False, sort_keys=True)
                for s in run.steps if s.shape == "tool"]
    assert len(readings) >= 2, run.to_dict()
    assert readings[0] == readings[1], "两条同样的调用读数不同 ⇒ 换一个静态工具当夹具"


def test_three_identical_readings_are_named_but_do_not_stop(tmp_path: pathlib.Path):
    """正控：连着三次同调用同读数 ⇒ 第 3 步被点名【没有新事实】，而这一趟照样跑完。"""
    run = _run(tmp_path, [_reply(STATIC_CALL)] * 3 + [_reply({"final": "我看清了，收工"})],
               max_steps=8)

    assert run.stop_reason == "final", run.to_dict()
    assert run.dead_loop_max == 3, run.to_dict()
    assert run.same_call_max == 3, run.to_dict()
    third = run.steps[2]
    assert "框架提醒" in third.result, third.result
    assert "没有新事实" in str(third.result["框架提醒"]), third.result
    assert "没有新事实" in run.transcript, run.transcript[-1200:]
    # 提醒是"纠正"，不是"判死"：它必须出现在 transcript 里让模型看得见。
    assert [s.shape for s in run.steps] == ["tool", "tool", "tool", "final"], run.to_dict()


def test_five_identical_readings_stop_the_run_as_no_progress(tmp_path: pathlib.Path):
    """正控：连着五次 ⇒ 以 `no_progress_limit` 收工（不是 `max_steps`），且话说清了。

    业主 2026-10-10 裁定 10丙 把这个数从 6 改成 5（「提醒3次、判停5次」）——
    于是提醒之后还剩两次改主意的机会（改前那句注释写的是"6 给三次机会"）。
    这一条同时钉住"两档分开"：提醒出现在第 3 步，判停发生在第 5 步，两个读数各说各的。
    """
    run = _run(tmp_path, [_reply(STATIC_CALL)], max_steps=12)

    assert run.stop_reason == "no_progress_limit", run.to_dict()
    assert len(run.steps) == 5, run.to_dict()
    assert run.dead_loop_max == 5, run.to_dict()
    assert "原地打转" in run.final and "没有新事实" in run.final, run.final
    # 收工语要指向"下一趟该换什么"，而不是只说"停了"。
    assert "换" in run.final, run.final
    # 点名只发生一次（第 3 步），不是每一步都刷一行。
    named = [s.index for s in run.steps if "框架提醒" in s.result]
    assert named == [2], named
    # 两档分开（裁定 10丙）：提醒过 1 次、并且确实是因此停的 —— 两个读数各说各的。
    assert run.dead_loop_nudges == 1, run.to_dict()
    assert run.dead_loop_stopped is True, run.to_dict()


def test_two_identical_readings_are_not_enough(tmp_path: pathlib.Path):
    """负控（门槛）：只重复两次不算打转 —— 判据不许把"读一遍再读一遍"判成打转。"""
    run = _run(tmp_path, [_reply(STATIC_CALL)] * 2 + [_reply({"final": "收工"})], max_steps=8)

    assert run.stop_reason == "final", run.to_dict()
    assert run.dead_loop_max == 2, run.to_dict()
    assert all("框架提醒" not in s.result for s in run.steps), run.to_dict()


def test_a_changing_reading_is_named_differently_and_never_stops(tmp_path: pathlib.Path):
    """边界（三态）：同调用而读数在变 ⇒ 提醒是【同一个调用】那一档，且从不停这一趟。

    读数在变的重问是正当的（轮询、等同伴改盘 —— 真机里 M 读台账时别的角色正在写它）。
    判据把两种情形分开写："同样的读数"才叫【没有新事实】；"读数在变"只提醒"问了三遍了"。
    """
    scripts = {"M": [_reply(CHANGING_CALL)] * 5 + [_reply({"final": "收工"})]}
    st, cond, registry, gw, root = TAL._wired(tmp_path, scripts, max_steps=10)
    gw["M"] = _ChangingGateway(list(gw["M"].replies), root / "out" / "counter.txt")
    run = run_role("M", "别原地打转", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)

    assert run.stop_reason == "final", run.to_dict()
    assert run.same_call_max >= 3, run.to_dict()
    assert run.dead_loop_max < 3, run.to_dict()
    named = [s for s in run.steps if "框架提醒" in s.result]
    assert named, "同一个调用连着三次也该被问一句（读数在变 ≠ 什么都不说）"
    assert "同一个调用" in str(named[0].result["框架提醒"]), named[0].result
    assert "没有新事实" not in str(named[0].result["框架提醒"]), named[0].result


def test_different_arguments_reset_the_streak(tmp_path: pathlib.Path):
    """负控（另一个方向）：换了参数就不是"同一次调用" —— 连击必须从头数。"""
    a = {"tool": "conductor.role_spec", "args": {"role_name": "C"}}
    b = {"tool": "conductor.role_spec", "args": {"role_name": "D"}}
    run = _run(tmp_path, [_reply(a), _reply(b), _reply(a), _reply(b),
                          _reply({"final": "收工"})], max_steps=8)

    assert run.stop_reason == "final", run.to_dict()
    assert run.same_call_max == 1, run.to_dict()
    assert all("框架提醒" not in s.result for s in run.steps), run.to_dict()


@pytest.mark.parametrize("reason", ["no_progress_limit", "escalated"])
def test_the_new_stop_reason_has_a_badge(reason: str):
    """接口面：新停止理由必须在 Web 徽标表里（否则界面把它显示成一个空徽标）。

    2026-10-19 扩面：`escalated`（交给召唤者）与 `no_progress_limit` 同属"它自己
    决定收工"那一族（退出码 5），两格都得有徽标，且都不是 `badge-fail` ——
    它们不是出错，是"这一趟没有往前走 / 已交给召唤者"（一档读数）。
    """
    from agentflow import webui as W

    assert reason in W._STOP_BADGES, sorted(W._STOP_BADGES)
    assert W._STOP_BADGES[reason][0] != "badge-fail", "它不是失败，是'这一趟没有往前走'"


#: 徽标判据的"该有哪些格"只从一张表来：`cli.EXIT_CODE_BY_STOP`。
#: 手抄一份名单会与那张表两处漂移，而"新加一档忘了登记徽标"正是这条要防的形态。
def _badge_problems(badges: dict[str, tuple[str, str]]) -> list[str]:
    """`EXIT_CODE_BY_STOP` 的每一档是否都在徽标表里、且形状像一条徽标。"""
    from agentflow import cli as CLI

    out: list[str] = []
    for reason in sorted(CLI.EXIT_CODE_BY_STOP):
        got = badges.get(reason)
        if got is None:
            out.append(f"`{reason}` 在退出码表里（{CLI.EXIT_CODE_BY_STOP[reason]}），"
                       f"但徽标表里没有它 ⇒ 界面会显示一个空徽标")
            continue
        if not (isinstance(got, tuple) and len(got) == 2):
            out.append(f"`{reason}` 的徽标不是 (class, 文案) 二元组：{got!r}")
            continue
        klass, text = got
        if not str(klass).startswith("badge-") or not str(text).strip():
            out.append(f"`{reason}` 的徽标形状不对：{got!r}")
    return out


def test_every_registered_stop_reason_has_a_badge() -> None:
    """通用形态（2026-10-19 业主裁定）：退出码表的每一档都必须解释得出来。

    改前这条判据只参数化了 `no_progress_limit` 一个值 —— 于是新增一档忘了加徽标时
    它照样绿，而界面显示的是一个空徽标。现在"该有哪些格"从 `cli.EXIT_CODE_BY_STOP`
    现取，口径只有一处。
    """
    from agentflow import cli as CLI
    from agentflow import webui as W

    problems = _badge_problems(W._STOP_BADGES)
    assert not problems, "有停止理由没有徽标：\n" + "\n".join(problems)
    # 反真空：表与徽标表都得有量（否则"都没扫到"会冒充"都对得上"）。
    assert len(CLI.EXIT_CODE_BY_STOP) >= 20, sorted(CLI.EXIT_CODE_BY_STOP)
    assert len(W._STOP_BADGES) >= len(CLI.EXIT_CODE_BY_STOP), sorted(W._STOP_BADGES)


def test_negative_control_a_missing_badge_goes_red() -> None:
    """负控：从徽标表里删掉一档 ⇒ 同一个判据必须看见（"忘了加徽标"真的会红）。"""
    from agentflow import webui as W

    badges = dict(W._STOP_BADGES)
    del badges["escalated"]
    problems = _badge_problems(badges)
    assert any("escalated" in p for p in problems), problems


def test_notes_differing_only_by_a_step_prefix_still_count_as_repeats(tmp_path: pathlib.Path):
    """正控（`draft/37` §140 补的漏洞）：正文只差"第 N 步"前缀的 note 仍算同一次调用。

    真机形态（T2 第 5 趟）：M 连写 14 条近乎相同的 note（每条只是把"第 N 步"改一个号），
    而那 3 分钟里一步没往前走 —— §136 的活性判据当时一次也没响：
    指纹把"第 41 步"与"第 42 步"当成了两次不同的调用。自述里的时间戳不是调用内容。
    """
    notes = [{"note": f"第{i}步：我连续在写重复的 note，这是原地打转。"} for i in range(1, 5)]
    run = _run(tmp_path, [_reply(n) for n in notes] + [_reply({"final": "收工"})], max_steps=8)

    assert run.stop_reason == "final", run.to_dict()
    assert run.same_call_max >= 3, run.to_dict()
    assert run.dead_loop_max >= 3, run.to_dict()
    assert "框架提醒" in run.steps[2].result, run.steps[2].result


def test_a_reworded_rationale_does_not_reset_the_repeat_counter(tmp_path: pathlib.Path):
    """负控（另一个方向）：`why` 是自述，换个说法不该让同一次调用变成"新的"。"""
    calls = [{"tool": "conductor.role_spec", "args": {"role_name": "C"}, "why": f"第 {i} 次复核"}
             for i in range(1, 4)]
    run = _run(tmp_path, [_reply(c) for c in calls] + [_reply({"final": "收工"})], max_steps=8)

    assert run.same_call_max == 3, run.to_dict()
    assert "框架提醒" in run.steps[2].result, run.steps[2].result


# ==================================================== D31：同一条路 + 同一类读数


def _summon(claim: str, extra: str = "") -> dict:
    """同一个主题（`claim`）上的一次召唤，`extra` 用来造"参数改了"这一档。"""
    params = {"claim": claim}
    if extra:
        params["description"] = extra
    return {"summon": {"role": "E", "action": "check_formal", "params": params}}


def test_the_same_road_is_named_even_when_the_arguments_change(tmp_path: pathlib.Path):
    """正控（D31 的回归）：同一个主题 + 同一类读数，参数每次改一处也要算同一条路。

    真机读数（T1 第 17 趟，`projects/p5-review-t17`）：M 连着 19 次派 `E.check_formal`，
    每一步都改一处 Lean 源码再试，读数一路是 `reason=compile_error`
    —— 参数每次不同 ⇒ `_call_key` 那条连击每步归零，`dead_loop_max` 全程是 1，
    活性判据一句话都没说，那 60 步 / $1.6 花在同一类失败上。
    """
    calls = [_summon("trace identity for block-diagonal matrices", f"第 {i} 版源码")
             for i in range(1, 4)]
    run = _run(tmp_path, [_reply(c) for c in calls] + [_reply({"final": "收工"})], max_steps=8)

    assert run.stop_reason == "final", run.to_dict()
    assert run.same_call_max == 1, "参数确实变了 ⇒ 同调用那条连击本来就该是 1"
    assert run.stalled_max >= 3, run.to_dict()
    remark = str(run.steps[2].result.get("框架提醒") or "")
    assert "同一条路" in remark, remark


def test_a_different_subject_is_not_the_same_road(tmp_path: pathlib.Path):
    """负控：换了主题就不是同一条路 —— 连击必须从头数（不许把并行的正常派活判成卡住）。"""
    calls = [_summon(f"第 {i} 个互不相干的命题") for i in range(1, 5)]
    run = _run(tmp_path, [_reply(c) for c in calls] + [_reply({"final": "收工"})], max_steps=8)

    assert run.stop_reason == "final", run.to_dict()
    assert run.stalled_max == 1, run.to_dict()
    assert all("同一条路" not in str(s.result.get("框架提醒") or "") for s in run.steps), run.to_dict()


def test_the_same_road_never_stops_the_run(tmp_path: pathlib.Path):
    """边界（刻意的设计）：同一条路只提醒、不判停。

    为什么不停：真机里那条路最后走通了（第 19 次拿到 proof 行，`experiments` 0004）
    —— 在这里判停会把"走得通但走得慢"判成"没有往前走"。判停仍然只有"同调用 + 同读数"
    那一条（`no_progress_limit`），它与这一条是两种不同的卡法。
    """
    calls = [_summon("同一个命题", f"第 {i} 版") for i in range(1, 8)]
    run = _run(tmp_path, [_reply(c) for c in calls] + [_reply({"final": "收工"})], max_steps=10)

    assert run.stop_reason == "final", run.to_dict()
    assert run.stalled_max >= 7, run.to_dict()
    assert run.dead_loop_max == 1, run.to_dict()


def test_the_stall_key_ignores_the_edited_part_but_not_the_verdict():
    """判据的两半各来一条：主题与读数类都参与，参数里"改掉的那一处"不参与。"""
    from agentflow.agent_loop import _stall_key

    def key(params: dict, reason: str) -> str:
        result = {"payload": json.dumps({"reason": reason, "verified": False})}
        return _stall_key("summon", {"role": "E", "action": "check_formal",
                                     "params": params}, result)

    base = {"claim": "trace identity", "description": "第 1 版"}
    edited = {"claim": "trace identity", "description": "第 2 版（只改了源码那一处）"}
    assert key(base, "compile_error") == key(edited, "compile_error")
    assert key(base, "compile_error") != key(base, "uses_sorry"), "读数类变了就不是同一条路"
    assert key(base, "compile_error") != key({"claim": "另一个命题"}, "compile_error")

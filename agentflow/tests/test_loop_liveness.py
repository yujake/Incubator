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


class _BodyScript(TAL.ScriptedGateway):
    """剧本只归本体：秘书那几发判断另给一份中性回答，不占本体的台词。

    ## 为什么需要这一层（2026-10-26，秘书自调模型）

    业主裁定「秘书处理将发出的信息时，要看内容是否与接受面相符」之后，每一步 `summon`
    在出去之前都会多发一次秘书判断（`AgentLoop._outbound_hook` →
    `Secretary.optimize_outbound(face=...)` → `Secretary.judge`，类别 `rearrange`），
    而那名秘书用的是本体同一条缝、同一个网关（`agent_loop._secretary_for`）。

    `ScriptedGateway` 按"第几次调用"取台词 ⇒ 那几发秘书调用把本体的剧本吃掉一半：
    三步的剧本只剩一步半，`stalled_max` 于是读到 2（要求 3）、4（要求 7）——
    这就是 D31 那两条改前红的读数。吃掉的是剧本，不是输赢。

    这一层按调用方分派：本体的回合（`system` 是角色提示词）拿剧本，秘书那一格
    （`system` 以「秘书」的判断面开头）拿一份判不成的中性回答 —— `judge` 于是退回
    机械判据，与改前那发被它吃掉的剧本同一条收场。`self.prompts` / `self.systems`
    只记本体的回合，所以"第 i 步用的是哪一条台词"仍然一一对应。

    判据本身一字未动：三步同一条路仍然要求 `stalled_max >= 3`（见下面两条）。
    """

    #: 秘书那一格的回答：不是受控词表里的结论 ⇒ `judge` 落"判不成"，退回机械判据。
    _NEUTRAL = "{}"

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        if "「秘书」的判断面" in str(system or ""):
            return type("Reply", (), {"ok": True, "text": self._NEUTRAL, "tokens_in": 10,
                                      "tokens_out": 10, "error_detail": "",
                                      "error_kind": ""})()
        return super().complete(prompt, scope=scope, system=system, **kw)


def _run(tmp_path: pathlib.Path, replies: list[str], *, max_steps: int = 8):
    scripts = {"M": replies}
    st, cond, registry, gw, root = TAL._wired(tmp_path, scripts, max_steps=max_steps)
    # 本体与它的秘书共用这一条缝：剧本按调用方分派，否则秘书那几发会吃掉本体的台词
    # （见 `_BodyScript` 的 docstring）。
    gw["M"] = _BodyScript(list(gw["M"].replies))
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


#: 徽标表用过的全部样式名（页面 CSS 里四种都有定义）。新造一个没定义过的
#: class 等于把这一档画成看不见的样式，而表本身照样绿 —— 所以它由判据钉住。
_BADGE_CLASSES = frozenset({"badge-pass", "badge-unknown", "badge-pending", "badge-fail"})


def _stop_table_problems(
        entries: dict[str, tuple[int | None, str, str, bool]],
        codes: dict[str, int],
        badges: dict[str, tuple[str, str]],
) -> list[str]:
    """Q23 的结构判据：退出码表 == live 条目，徽标表 == 全部条目。

    三件事逐条查，而不是比长度：
    1. 退出码表逐字等于 `live=True` 的集合（两个方向）；
    2. 徽标表逐字等于真身表的全部条目（两个方向）；
    3. 徽标表比退出码表多出来的那些，逐格必须 `live=False`。

    为什么不是 `len(徽标表) >= len(退出码表)`：改前两表各 22 格 —— 退出码表少了
    `final_refused`、徽标表多了 `max_steps`，两处错误在长度上互相抵消，于是旧判据
    亮绿。格数相等既不等于键集合相等，也不等于"在跑的档都有码、有码的档都解释
    得出来"。
    """
    out: list[str] = []
    live = {reason for reason, row in entries.items() if row[3]}
    # 1) 退出码表只许装 live 条目，且 live 条目一个都不许漏。
    for reason in sorted(live - set(codes)):
        out.append(f"`{reason}` 标了 live=True，但退出码表里没有它 ⇒ 运行期读到它"
                   f"只会落进未登记兜底")
    for reason in sorted(set(codes) - live):
        row = entries.get(reason)
        if row is None:
            out.append(f"`{reason}` 在退出码表里，但真身表里没有它 ⇒ 没有徽标，也"
                       f"没有来源")
        else:
            out.append(f"`{reason}` 在退出码表里，但真身里它不是 live=True ⇒ 退出码表"
                       f"混进了旧读数（它只该有徽标）")
    # 2) 徽标表要解释得出来每一条（live 与旧读数都要）。
    for reason in sorted(set(entries) - set(badges)):
        out.append(f"`{reason}` 在真身表里，但徽标表里没有它 ⇒ 界面会显示一个空徽标")
    for reason in sorted(set(badges) - set(entries)):
        out.append(f"`{reason}` 只在徽标表里，真身表里没有它 ⇒ 无法证明它该不该有退出码")
    # 3) 多出来的徽标项必须是 live=False（这是"旧读数可以只有徽标"的唯一许可）。
    for reason in sorted(set(badges) - set(codes)):
        row = entries.get(reason)
        if row is not None and row[3]:
            out.append(f"`{reason}` 只在徽标表里，但真身里它是 live=True ⇒ 一个还在"
                       f"产生的档没有退出码")
    # 4) 每格徽标与退出码的形状。
    for reason in sorted(set(entries) & set(badges)):
        code, klass, text, is_live = entries[reason]
        got = badges[reason]
        if not (isinstance(got, tuple) and len(got) == 2):
            out.append(f"`{reason}` 的徽标不是 (class, 文案) 二元组：{got!r}")
        else:
            if got != (klass, text):
                out.append(f"`{reason}` 的徽标与真身不一致：真身 {(klass, text)!r} / "
                           f"徽标表 {got!r}")
            if klass not in _BADGE_CLASSES:
                out.append(f"`{reason}` 的徽标 class 是 {klass!r}，不在既有样式里："
                           f"{sorted(_BADGE_CLASSES)}")
            if not str(text).strip():
                out.append(f"`{reason}` 的徽标文案是空的 ⇒ 界面会显示一个空徽标")
        if is_live:
            if not isinstance(code, int) or isinstance(code, bool):
                out.append(f"`{reason}` 是 live=True，退出码却不是整数：{code!r}")
            elif reason == "final":
                if code != 0:
                    out.append(f"`final` 的退出码是 {code}，必须是 0（正常完成）")
            elif code not in (1, 2, 3, 4, 5):
                out.append(f"`{reason}` 是 live=True，退出码是 {code}，必须是 1..5 的"
                           f"整数（0 只留给 final）")
            if reason in codes and codes[reason] != code:
                out.append(f"`{reason}` 的退出码两处不一致：真身 {code!r} / 退出码表 "
                           f"{codes[reason]!r}")
        elif code is not None:
            out.append(f"`{reason}` 是 live=False（旧读数），却带着退出码 {code!r} ⇒ "
                       f"它不该进退出码表")
    return out


def test_every_registered_stop_reason_has_a_badge() -> None:
    """判据 a+b（2026-10-26 Q23）：两张投影表与真身逐格对得上。

    改前这条只查"退出码表的每一格在徽标表里有没有"，是单向的；徽标表反向多出的
    `max_steps` 与退出码表单向缺的 `final_refused` 同时存在，而两表格数相同，
    于是旧判据的 `>=` 长度检查也没响。
    2026-10-26 业主裁定：`live=False` 的旧读数只许有徽标、不许进退出码表。
    """
    from agentflow import cli as CLI
    from agentflow import webui as W
    from agentflow.stop_reasons import STOP_REASONS

    problems = _stop_table_problems(STOP_REASONS, CLI.EXIT_CODE_BY_STOP, W._STOP_BADGES)
    assert not problems, "停止理由的两张表与真身对不上：\n" + "\n".join(problems)

    live = {reason for reason, row in STOP_REASONS.items() if row[3]}
    assert set(CLI.EXIT_CODE_BY_STOP) == live, (
        f"退出码表 − live：{sorted(set(CLI.EXIT_CODE_BY_STOP) - live)}；"
        f"live − 退出码表：{sorted(live - set(CLI.EXIT_CODE_BY_STOP))}")
    assert set(W._STOP_BADGES) == set(STOP_REASONS), (
        f"徽标表 − 真身：{sorted(set(W._STOP_BADGES) - set(STOP_REASONS))}；"
        f"真身 − 徽标表：{sorted(set(STOP_REASONS) - set(W._STOP_BADGES))}")
    # 反真空：两表都得有量（否则"都没扫到"会冒充"都对得上"）；旧读数那一支
    # 也必须真的被跑到，否则"只投影 live"这条规则没有被任何一格验证。
    assert len(CLI.EXIT_CODE_BY_STOP) >= 20, sorted(CLI.EXIT_CODE_BY_STOP)
    assert len(W._STOP_BADGES) >= len(CLI.EXIT_CODE_BY_STOP), sorted(W._STOP_BADGES)
    legacy = set(W._STOP_BADGES) - set(CLI.EXIT_CODE_BY_STOP)
    assert legacy, "徽标表里一格旧读数都没有 ⇒ live=False 那条投影规则没被验证"
    assert all(STOP_REASONS[r][3] is False for r in legacy), sorted(legacy)
    # b 的锚点：0 只属于 final；其余 live 档是 1..5 的正整数（None/0 都不许）。
    assert CLI.EXIT_CODE_BY_STOP["final"] == 0
    assert all(isinstance(v, int) and not isinstance(v, bool) and v in (1, 2, 3, 4, 5)
               for k, v in CLI.EXIT_CODE_BY_STOP.items() if k != "final"), (
        {k: v for k, v in CLI.EXIT_CODE_BY_STOP.items() if k != "final"})


def test_an_unknown_stop_reason_still_renders_text() -> None:
    """判据 c（正控）：未知 stop_reason 也有非空徽标文案（不是空串）。

    为什么要有兜底：`_STOP_BADGES` 只解释登记过的档；旧会话记录、手工写坏的
    checkpoint、以及下一个还没登记的 stop_reason 都会走到表外。表外的这一格
    如果渲染成空串，界面看起来就是"这一趟没有理由"—— 那比"未知"更假。
    """
    from agentflow.webui.server import stop_badge

    for probe in ("a_stop_reason_nobody_registered", ""):
        klass, text = stop_badge(probe)
        assert str(klass).startswith("badge-"), (probe, klass)
        assert str(text).strip(), (probe, text)
        assert "未知收场" in text, (probe, text)
        if probe:
            assert probe in text, "兜底文案要把原值留在括号里，读的人才知道去查哪个词"


def test_negative_control_a_missing_badge_goes_red() -> None:
    """判据 d（反真空）：从徽标表里删掉一档 ⇒ 判据 a 必红（live 与旧读数都试）。"""
    from agentflow import cli as CLI
    from agentflow import webui as W
    from agentflow.stop_reasons import STOP_REASONS

    for victim in ("escalated", "max_steps"):
        badges = dict(W._STOP_BADGES)
        del badges[victim]
        problems = _stop_table_problems(STOP_REASONS, CLI.EXIT_CODE_BY_STOP, badges)
        assert any(victim in p for p in problems), (victim, problems)


def test_negative_control_an_extra_entry_goes_red() -> None:
    """判据 d（反方向）：多一格、少一个码、旧读数混进退出码表，三样都要红。

    最后一条就是 `max_steps` 那一格的教训：它只在徽标表里时可以理解，
    一旦被补进退出码表，就把"旧读数"伪装成一个运行期档。
    """
    from agentflow import cli as CLI
    from agentflow import webui as W
    from agentflow.stop_reasons import STOP_REASONS

    badges = dict(W._STOP_BADGES)
    badges["a_stop_reason_only_in_the_badge_table"] = ("badge-unknown", "只有徽标")
    problems = _stop_table_problems(STOP_REASONS, CLI.EXIT_CODE_BY_STOP, badges)
    assert any("a_stop_reason_only_in_the_badge_table" in p for p in problems), problems

    codes = dict(CLI.EXIT_CODE_BY_STOP)
    del codes["escalated"]
    problems = _stop_table_problems(STOP_REASONS, codes, W._STOP_BADGES)
    assert any("escalated" in p for p in problems), problems

    codes = dict(CLI.EXIT_CODE_BY_STOP)
    codes["max_steps"] = 5
    problems = _stop_table_problems(STOP_REASONS, codes, W._STOP_BADGES)
    assert any("max_steps" in p for p in problems), problems


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

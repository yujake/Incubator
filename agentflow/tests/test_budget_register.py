# -*- coding: utf-8 -*-
"""预算寄存器（`budget.py`）与它的四个消费点：业主 2026-10-12 的预算轴。

> 业主口径（逐字）：「我们不硬性限制运行步数，但限制预算。请做好预算设置和显示窗口，
> 用户可追加预算，运行消耗的钱从总预算里实时扣除，扣完时自动发送优雅停止请求
> （这时预算可能会继续扣成负的一点点，但无大碍）。」

## 这一批锁住的四件事

1. 寄存器本身：设 / 追加（单调、只收正数）/ 三态（没设过 ≠ 读不懂）/ 剩余可为负；
2. 每一次花钱之前现读（`LlmSeam.budget_of`）：追加之后下一个调用就受新上限约束
   —— 这条是"用户可追加预算"唯一能被机器验证的形态（不需要重启、不需要重跑）；
3. 扣完优雅停：步循环写一个一次性停机记录（`stopctl` 的历史 + 立刻消费），
   不留开关 —— 否则"追加预算后 `--resume`"会在第 0 步被自己上一趟的开关停掉；
4. 多轮闸门每一轮现读（`autonomy._round_budget`）：加钱之后下一轮照跑。
"""
from __future__ import annotations

import dataclasses
import json
import pathlib

import pytest

from agentflow import budget as B
from agentflow import stopctl as SC
from agentflow import autonomy as AU
from agentflow.llmseam import LlmSeam, SeamSpend
from agentflow.store import Store


@pytest.fixture()
def ws(tmp_path: pathlib.Path) -> pathlib.Path:
    st = Store(tmp_path / "ws")
    st.init()
    return tmp_path / "ws"


class _Gateway:
    """一个永远成功的最小网关（这一组只看闸门，不看模型）。"""

    spec = type("Spec", (), {"model": "g", "api_key": "k"})()

    def complete(self, prompt, *, scope="", system=None, max_tokens=None, tools=None):
        return type("Reply", (), {"ok": True, "text": '{"final": "ok"}', "tokens_in": 1,
                                  "tokens_out": 1, "tool_calls": (), "reasoning": "",
                                  "error_detail": ""})()


# ============================================================ 1. 寄存器本体
def test_missing_register_is_not_applicable_not_zero(ws: pathlib.Path) -> None:
    """没设过预算 ⇒ `not_applicable` + 回退到调用方给的上限（不是 0、也不是不限量）。"""
    got = B.read_register(ws)
    assert got["checked"] is True and got["exists"] is False and got["problem"] == ""
    assert B.limit_usd(ws, fallback=1.5) == 1.5, "寄存器缺席时用调用方给的上限"
    assert B.limit_usd(ws, fallback=None) is None, "两边都没有 ⇒ 不限量"
    snap = B.reading(ws, spent_usd=0.0, fallback=None)
    assert snap["tri"] == "not_applicable" and snap["total_usd"] is None
    assert snap["source"] == "unlimited"


def test_set_then_add_is_monotonic_and_keeps_history(ws: pathlib.Path) -> None:
    """设 5 ⇒ 追加 2 ⇒ 总额 7，且追加历史逐条留着（谁、什么时候、为什么）。"""
    assert B.write_initial(ws, 5.0, by="Yu", note="初始")["ok"] is True
    assert B.limit_usd(ws, fallback=None) == 5.0
    got = B.add_usd(ws, 2.0, by="Yu", note="让它跑完")
    assert got["ok"] is True and got["total_usd"] == 7.0
    snap = B.reading(ws, spent_usd=6.5)
    assert snap["total_usd"] == 7.0 and snap["spent_usd"] == 6.5
    assert snap["remaining_usd"] == 0.5 and snap["exceeded"] is False
    assert [a["kind"] for a in snap["added"]] == ["set", "add"]
    assert snap["added"][1]["note"] == "让它跑完"


def test_exceeding_the_budget_is_a_reading_not_an_error(ws: pathlib.Path) -> None:
    """业主：「预算可能会继续扣成负的一点点，但无大碍」⇒ 剩余为负是读数，不是异常。"""
    B.write_initial(ws, 1.0)
    snap = B.reading(ws, spent_usd=1.004)
    assert snap["remaining_usd"] == pytest.approx(-0.004)
    assert snap["exceeded"] is True and snap["tri"] == "computed"


def test_a_broken_register_falls_back_and_says_so(ws: pathlib.Path) -> None:
    """读不懂的寄存器：回退到调用方上限（少花是安全的那一侧），但问题必须留在读数里。"""
    (ws / B.REGISTER_NAME).write_text("{ 这不是 JSON", encoding="utf-8")
    got = B.read_register(ws)
    assert got["problem"] and got["total_usd"] is None
    assert B.limit_usd(ws, fallback=2.0) == 2.0
    assert B.add_usd(ws, 1.0)["ok"] is False, "读不懂时拒绝在它上面追加（不许猜一个基数）"
    assert B.reading(ws, spent_usd=0.0, fallback=2.0)["tri"] == "unreadable"


def test_only_positive_amounts_are_accepted(ws: pathlib.Path) -> None:
    """0 / 负数 / 非数字一律当场拒 —— 一次静默的"加了 0"会让用户以为加上了。"""
    B.write_initial(ws, 3.0)
    for bad in (0, -1, float("nan"), "abc"):
        got = B.add_usd(ws, bad)          # type: ignore[arg-type]
        assert got["ok"] is False, bad
    assert B.limit_usd(ws, fallback=None) == 3.0, "被拒的追加不许改动总额"


def test_setting_a_new_total_keeps_the_history_and_says_what_it_lost(
        ws: pathlib.Path) -> None:
    """改总额（`--set` 第二回）不许抹掉追加历史；坏寄存器上显式重设要留"丢了什么"。

    为什么钉第一条：`added` 是同一份账上的两种事件（谁把总额改成多少 / 谁追加了多少）。
    抹掉后者会让"已花 7.5 而历史里只有一笔 set"变成一笔无解的账 —— 而那一份历史
    正是"运行消耗从总预算里实时扣除"这句话唯一的凭证。
    """
    B.write_initial(ws, 5.0, by="Yu", note="初始")
    B.add_usd(ws, 1.0, by="Yu", note="追一笔")
    got = B.write_initial(ws, 2.0, by="Yu", note="改小")
    assert got["ok"] is True and got["total_usd"] == 2.0
    snap = B.reading(ws, spent_usd=0.0)
    assert [a["kind"] for a in snap["added"]] == ["set", "add", "set"], snap["added"]
    assert snap["added"][1]["note"] == "追一笔", "追加历史不许被改总额抹掉"
    assert snap["total_usd"] == 2.0
    # 坏寄存器上显式重设：允许（`add_usd` 算不出基数只能拒），但丢了什么要留痕
    (ws / B.REGISTER_NAME).write_text("nope", encoding="utf-8")
    got2 = B.write_initial(ws, 2.0)
    assert got2["ok"] is True and got2.get("history_lost"), got2
    assert len(B.reading(ws, spent_usd=0.0)["added"]) == 1, "覆盖之后是一份能读懂的账"


def test_every_name_the_module_exports_exists(ws: pathlib.Path) -> None:
    """反真空：`__all__` 里写的名字必须真的存在。

    为什么单为这一个模块立一条：`budget.py` 的读函数从 `state` 改名成 `reading`
    （避开与 `paperbuild.state` 之类的重名），而 `__all__` 里漏改的那一格没有任何
    判据看着 —— `from agentflow.budget import *` 会当场炸，而"没人 import *"
    不等于"公开面是对的"。
    """
    missing = [n for n in B.__all__ if not hasattr(B, n)]
    assert not missing, f"__all__ 里这些名字不存在：{missing}"
    assert "reading" in B.__all__ and "state" not in B.__all__


# ============================================================ 2. 缝：每次调用前现读
def _seam(ws: pathlib.Path, *, static: float | None, resolver) -> LlmSeam:
    return LlmSeam(role="M", session_root=ws, gateway=_Gateway(), price=(0.0, 0.0),
                   usd_budget=static, budget_of=resolver,
                   spend=SeamSpend(usd=1.0, calls=1))


def test_a_top_up_lets_the_next_call_through(ws: pathlib.Path) -> None:
    """核心一条：加钱之后下一个调用就放行（这就是"可追加预算"的机器形态）。"""
    B.write_initial(ws, 1.0)
    seam = _seam(ws, static=None, resolver=lambda: B.limit_usd(ws, fallback=None))
    blocked = seam.ask("问一句")
    assert blocked.problem == "judge_over_budget", blocked.problem
    assert B.add_usd(ws, 1.0, by="Yu")["ok"] is True
    after = seam.ask("再问一句")
    assert after.problem != "judge_over_budget", "追加之后这一次必须真的发出去"
    assert after.ok is True


def test_the_resolver_falling_over_falls_back_to_the_static_cap(ws: pathlib.Path) -> None:
    """现读那一口炸了 ⇒ 退回构造期上限（少花），绝不变成"不限量"。"""
    def _boom():
        raise OSError("盘坏了")

    seam = _seam(ws, static=0.5, resolver=_boom)
    assert seam.budget_limit() == 0.5
    assert seam.ask("问一句").problem == "judge_over_budget"
    # 没有静态上限且现读炸了 ⇒ 不限（这是"两个都没有"那一档，与上面那条不同）
    loose = _seam(ws, static=None, resolver=_boom)
    assert loose.budget_limit() is None


# ============================================================ 3. 扣完优雅停
def test_budget_exhaustion_leaves_one_shot_history_and_no_lingering_switch(
        ws: pathlib.Path) -> None:
    """步循环那一支：写一个一次性停机记录（历史有、开关不留）。"""
    from agentflow import agent_loop as AL

    loop = AL.AgentLoop(role="M", session_root=ws, registry=None, seam=None, sid="t-budget")
    note = loop._land_budget_stop_record(1.25)
    assert note == "", note
    hist = ws / "runs" / "stop-history.jsonl"
    assert hist.is_file(), "停机记录必须落一笔历史"
    rows = [json.loads(x) for x in hist.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows and rows[-1]["by"] == "budget" and "预算耗尽" in rows[-1]["reason"]
    assert rows[-1]["level"] == "budget" and rows[-1]["removed"] is True
    assert not (ws / SC.STOP_FILE_NAME).exists(), \
        "开关必须被消费掉 —— 否则追加预算后的 --resume 会在第 0 步被自己上一趟停掉"


def test_a_foreign_switch_is_never_touched(ws: pathlib.Path) -> None:
    """盘上已经有别人的开关 ⇒ 只记读数，不写、不消费（谁写的谁清）。"""
    from agentflow import agent_loop as AL

    SC.request_stop_detail(ws, reason="user", by="user", sid="other")
    loop = AL.AgentLoop(role="M", session_root=ws, registry=None, seam=None, sid="t-budget")
    note = loop._land_budget_stop_record(1.0)
    assert "已有一把停机开关" in note, note
    assert (ws / SC.STOP_FILE_NAME).exists(), "别人的开关不许被这一支撤掉"


# ============================================================ 4. 多轮闸门现读
def test_each_round_reads_the_register_again(ws: pathlib.Path) -> None:
    """多轮那条路：加钱之后下一轮照跑（取一次会把"追加"变成"重启才生效"）。"""
    B.write_initial(ws, 1.0)
    assert AU._round_budget(ws, None) == 1.0
    assert AU._round_budget(ws, 9.0) == 1.0, "寄存器在场时压过调用方给的那个数"
    B.add_usd(ws, 4.0)
    assert AU._round_budget(ws, None) == 5.0
    # 寄存器读不懂 ⇒ 退回调用方给的上限
    (ws / B.REGISTER_NAME).write_text("nope", encoding="utf-8")
    assert AU._round_budget(ws, 2.5) == 2.5


# ============================================================ 5. 台面（CLI）
def test_the_cli_reads_and_appends(ws: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
    """`agentflow budget --set/--add/--status --json`：台面就是那一份读数。"""
    from agentflow import cli

    def _last_json(text: str) -> dict:
        """台面输出里最后一个 JSON 对象（`--json` 那一段；前面可能还有写入回执行）。

        为什么不用"从最后一个 `{` 行读到底"那种写法：`--set` / `--add` 的回执行长这样
        `[budget] 设总额度：{"ok": true, …}`（同一行、前面带前缀），
        而 `--json` 的那一段是多行缩进的对象 —— 两种形状都要认，所以按
        "扫描全文、逐个 raw_decode、取最后一个 dict"来做。
        """
        dec = json.JSONDecoder()
        best: dict | None = None
        idx = 0
        while True:
            i = text.find("{", idx)
            if i < 0:
                break
            try:
                obj, end = dec.raw_decode(text[i:])
            except json.JSONDecodeError:
                idx = i + 1
                continue
            if isinstance(obj, dict):
                best = obj
            idx = i + end
        assert best is not None, f"输出里没有 JSON：{text!r}"
        return best

    assert cli.main(["--root", str(ws), "budget", "--json"]) == 0
    first = _last_json(capsys.readouterr().out)
    assert first["total_usd"] is None and first["tri"] == "not_applicable"
    assert cli.main(["--root", str(ws), "budget", "--set", "2", "--by", "Yu"]) == 0
    capsys.readouterr()
    assert cli.main(["--root", str(ws), "budget", "--add", "1.5", "--note", "追一笔"]) == 0
    capsys.readouterr()
    assert cli.main(["--root", str(ws), "budget", "--json"]) == 0
    last = _last_json(capsys.readouterr().out)
    assert last["total_usd"] == 3.5 and len(last["added"]) == 2
    # 拒掉的追加要让退出码说话（2 = 没查成），不是静默成功
    assert cli.main(["--root", str(ws), "budget", "--add", "-1"]) == 2

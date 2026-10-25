"""D19：用户摁停之后不许再开下一轮（多轮驱动那一层）。

## 这一组守住什么

改前这条链上有三层断点，每一层单独都能让"用户摁停"这件事在下一轮开跑前消失：

1. `cli` 的多轮那一档把 `stop_file` 传成 `None` ⇒ `autonomy.run_autonomous` 里
   `stop_path = Path(stop_file) if ... else None` ⇒ 下面每一处"盘上有没有"整条短路；
2. 就算给了路径：读到它那一趟的树根在收尾时把开关撤走（`agent_loop` 的
   `_consume_stop_at_teardown`）⇒ 下一轮再问"文件还在不在"必然得到"没有了"；
3. 最深的一层：`autonomy._stop_before_round` 只认 `waiting_for_user` / `escalated`
   两档理由码，用户叫停那一族（`stop_file` / `force_stop` / `interrupted_by_parent`）
   根本不在判据里 —— 所以即使上一轮明明白白以 `stop_file` 收工，它照开第二轮。

判据（每条都在"跑一次真的多轮"上判，不是读代码）：
- 正控：`--rounds 3` + 第 1 轮中途摁停 ⇒ 只跑 1 轮、退出码 4、
  `runs/stop-history.jsonl` 与 `runs/autonomy-<角色>.json` 都读得出"按用户要求停"；
- 负控（反真空的另一半）：同一个剧本不摁停 ⇒ 照旧跑满 3 轮（没有把多轮一并掐死）；
- 负控（改前红）：把用户叫停那一档从 `_stop_before_round` 上摘掉 ⇒ 正控必须红。

替身模型与 `tests/test_agent_cli.py` 同款（`complete(prompt, *, scope, system)`），
不花模型钱：这一组判的是"停机判据在哪一步生效"，不是模型答得好不好。
"""
from __future__ import annotations

import json
import pathlib
from argparse import Namespace
from typing import Any

from agentflow import autonomy as AU
from agentflow import cli
from agentflow import sessions as SS
from agentflow import stopctl
from agentflow.llmseam import LlmSeam
from agentflow.tools.conductor_tools import reset_cache


class ScriptedGateway:
    """照剧本回答的替身模型：奇数步给一条 `note`，偶数步给 `final`。

    为什么要两种形状：只有让第 1 轮出现"第 1 步之后还有第 2 步"，轮内那条停机判据
    才有机会在两步之间生效（这一步就是"用户在第 1 轮中途摁停"的机器形态）。
    """

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, *, on_call: Any = None) -> None:
        self.prompts: list[str] = []
        self.on_call = on_call

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        """记下这一次的 prompt，按步号答一句；第 n 次调用前先做那件"外部事件"。"""
        self.prompts.append(prompt)
        n = len(self.prompts)
        if self.on_call is not None:
            self.on_call(n)
        if n % 2:
            text = json.dumps({"note": f"第 {n} 步：先看一眼盘"}, ensure_ascii=False)
        else:
            text = json.dumps({"final": f"第 {n} 步收工：这一轮做完了", "evidence": []},
                              ensure_ascii=False)
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 5, "tokens_out": 5,
                                  "error_detail": "", "error_kind": ""})()


def _run(tmp_path: pathlib.Path, monkeypatch: Any, *, press_stop: bool,
         rounds: int = 3) -> dict[str, Any]:
    """跑一趟真的 `--rounds N`：返回退出码、逐轮读数、检查点与 stop-history。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    state = {"pressed": False}

    def on_call(n: int) -> None:
        """第 1 轮的第 1 次模型调用之后摁停（用户手上有 `agentflow stop` 那条命令）。"""
        if press_stop and n == 1 and not state["pressed"]:
            state["pressed"] = True
            stopctl.request_stop(root, reason="user", by="user")

    def fake_seam_factory(role: str, *, root: pathlib.Path, sid: str | None,
                          usd_budget: float | None, store: Any = None) -> Any:
        return LlmSeam(role=role, session_root=root, gateway=ScriptedGateway(on_call=on_call),
                       price=(0.0, 0.0), sid=sid, usd_budget=usd_budget, meter=None)

    monkeypatch.setattr(cli, "_agent_seam_factory", fake_seam_factory)
    reset_cache()
    args = Namespace(root=str(root), sid="t", json=False, budget_usd=None, dispatch=False,
                     role="D", task="把这件活做完", drive=[], max_steps=4,
                     rounds=rounds, report_every=1, resume=False, stop_file=None,
                     provider="fixture", config=None, wall_clock_sec=0, no_ask=True,
                     semantic_review=False, experiment_reasoning=False, subagents=False,
                     allow_foreign_entries=False, user_wait_sec=None)
    rc = cli.cmd_run_agent(args)
    events, problems = SS.read_session(root, sid="t")
    assert not problems, problems
    cp_path = AU.checkpoint_path(root, "D")
    cp = json.loads(cp_path.read_text(encoding="utf-8")) if cp_path.is_file() else {}
    return {
        "rc": rc,
        "rounds": [int(e["index"]) for e in events if e.get("kind") == "autonomy_round"],
        "reports": [int(e["round"]) for e in events if e.get("kind") == "autonomy_report"],
        "checkpoint": cp,
        "stop_reason": str(cp.get("stop_reason") or ""),
        "history": stopctl.stop_history(root, limit=10),
        "switch_on_disk": stopctl.stop_path(root).is_file(),
        "root": root,
    }


def test_a_user_stop_in_round_one_stops_before_round_two(tmp_path: pathlib.Path,
                                                        monkeypatch: Any) -> None:
    """正控（D19）：`--rounds 3` + 第 1 轮中途摁停 ⇒ 只跑 1 轮，退出码 4。

    三个读数一起断言，因为它们回答的是三个不同的问题：
    - 轮数 = 1：下一轮没有开起来（这一条是缺陷本身）；
    - 退出码 = 4：`stop_file` 在 `EXIT_CODE_BY_STOP` 里那一档（"有人叫停"不是失败）；
    - stop-history 与检查点：事后读得出"按用户要求停"，不是只剩一句"停了"。
    """
    got = _run(tmp_path, monkeypatch, press_stop=True)
    assert got["rounds"] == [1], (
        f"用户在第 1 轮摁停之后又开了下一轮：{got['rounds']}（会话在 {got['root']}）")
    assert got["reports"] == [1], f"汇报轮次与轮次对不上：{got['reports']}"
    assert got["rc"] == 4, f"退出码应当是 4（用户叫停），收到 {got['rc']}"
    assert got["stop_reason"] == "stop_file", got["checkpoint"]
    # stop-history：那一笔必须读得出来"谁按的、为什么"，而不只是"停过"
    assert got["history"], "runs/stop-history.jsonl 里没有那一笔 —— 事后无从复核"
    last = got["history"][-1]
    assert str(last.get("level") or "") in stopctl.USER_STOP_REASONS, last
    assert str(last.get("reason") or "") == "user" and str(last.get("by") or "") == "user", last
    # autonomy-<角色>.json：检查点里那份开关负载（谁在什么时候为什么按的）
    switch = dict(got["checkpoint"].get("stop_switch") or {})
    assert switch, f"检查点里没有 stop_switch：{got['checkpoint']}"
    assert str(switch.get("reason") or "") == "user", switch
    assert str(switch.get("by") or "") == "user", switch
    # 开关是一次性信号：停完这一趟它不该还留在盘上（否则下一趟在第 0 轮又被它停一次）
    assert not got["switch_on_disk"], "开关还留在盘上"


def test_negative_control_without_a_stop_all_rounds_still_run(tmp_path: pathlib.Path,
                                                              monkeypatch: Any) -> None:
    """负控（反真空）：同一个剧本、不摁停 ⇒ 照旧跑满 3 轮。

    没有这一条，"只跑 1 轮"可以靠"把多轮整个掐死"满足 —— 那是把缺陷换成了另一个缺陷。
    """
    got = _run(tmp_path, monkeypatch, press_stop=False)
    assert got["rounds"] == [1, 2, 3], f"没摁停却没跑满：{got['rounds']}"
    assert got["stop_reason"] == "rounds", got["checkpoint"]
    assert got["rc"] == 0, f"三轮都以 final 收工，退出码应当是 0，收到 {got['rc']}"
    assert not got["history"], f"没人叫停却留下了停机审计：{got['history']}"


def test_negative_control_dropping_the_user_stop_tier_makes_it_red(
        tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """改前红（反真空）：把用户叫停那一档从判据上摘掉 ⇒ 正控必须红。

    这一条是"正控真的依赖那一档"的唯一证据：改前 `_stop_before_round` 正是这个形状
    （只认 `waiting_for_user` / `escalated`）。摘掉之后第 1 轮照样以 `stop_file` 收工，
    但第 2 轮会照开 —— 于是"只跑 1 轮"这条断言变成红。
    """
    real = AU._stop_before_round

    def without_the_user_stop_tier(*args: Any, **kw: Any) -> str:
        """改前形态：理由码里没有用户叫停那一族，也没有闩式快照。"""
        if kw.get("last_stop_reason") in stopctl.USER_STOP_REASONS:
            kw["last_stop_reason"] = ""
        kw["stop_latch_reason"] = ""
        return real(*args, **kw)

    monkeypatch.setattr(AU, "_stop_before_round", without_the_user_stop_tier)
    got = _run(tmp_path, monkeypatch, press_stop=True)
    assert got["rounds"] != [1], (
        "把用户叫停那一档摘掉之后判据仍然是绿的 ⇒ 正控没有咬合力（它没在测那一档）")
    assert got["rc"] != 4, f"摘掉那一档之后退出码不该再是 4，收到 {got['rc']}"

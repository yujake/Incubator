"""产品路径上的模型驱动与用户频道：`host.wired_llm_conductor` + CLI 三个动词。

## 这一组守什么（`draft/28` §184.5 第 1 步的判据）

`draft/28` §184.1 记的两条架构缺口在这里收口：

1. `LlmBackend` 原先只出现在它自己的定义文件里（真机验收靠脚本手工接线）⇒
   现在有 `host.wired_llm_conductor` 与 CLI 的 `run-agent` 这条产品路径；
2. 用户频道有 API 没有入口 ⇒ 现在有 `inbox` / `answer` 两个动词。

三条纪律各配判据：默认接线表为空（不接线就不改变确定性行为）、
没有 key 一律退出码 2 且一次请求都不发、被驱动的动作真的走 LLM 循环且台账成链。
"""
from __future__ import annotations

import json
import pathlib
from argparse import Namespace
from typing import Any

from agentflow import cli
from agentflow import sessions as SS
from agentflow import userio as U
from agentflow.agent_loop import LlmBackend
from agentflow.host import DEFAULT_LLM_LOOPS, wired_llm_conductor
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools.conductor_tools import reset_cache


class ScriptedGateway:
    """照剧本回答的替身模型（与真模型同接口）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 5, "tokens_out": 5,
                                  "error_detail": "", "error_kind": ""})()


SCRIPTS: dict[str, list[str]] = {}


def fake_seam_factory(role: str, *, root: pathlib.Path, sid: str | None, usd_budget: float | None):
    """替身模型工厂：按角色取剧本（测试用它替换 `cli._agent_seam_factory`）。"""
    gw = ScriptedGateway(SCRIPTS.get(role, ['{"final": "（没有剧本）", "evidence": []}']))
    return LlmSeam(role=role, session_root=root, gateway=gw, price=(0.0, 0.0), sid=sid,
                   usd_budget=usd_budget)


def _args(tmp_path: pathlib.Path, **kw: Any) -> Namespace:
    base = dict(root=str(tmp_path / "ws"), sid="t", json=False, budget_usd=None, dispatch=False)
    base.update(kw)
    return Namespace(**base)


def test_the_default_loops_table_is_empty(tmp_path: pathlib.Path):
    """负控（不许静默改变行为）：默认接线表为空 ⇒ 环境里有 key 也不会换掉确定性实现。"""
    assert DEFAULT_LLM_LOOPS == {}, DEFAULT_LLM_LOOPS
    st = Store(tmp_path / "ws")
    st.init()
    reset_cache()
    wiring = wired_llm_conductor(st, session_root=st.root, sid="t")
    assert wiring["loops"] == {}
    assert isinstance(wiring["conductor"].backend, LlmBackend)
    assert wiring["backend"].loops == {}


def test_the_cached_conductor_gets_its_backend_replaced_loudly(tmp_path: pathlib.Path):
    """正控（挑明缓存陷阱）：先建确定性主控、再要模型驱动 ⇒ backend 被换掉并留痕。"""
    st = Store(tmp_path / "ws")
    st.init()
    reset_cache()
    from agentflow.host import wired_conductor

    first = wired_conductor(st, workspace_root=str(st.root))
    assert not isinstance(first.backend, LlmBackend)
    second = wired_llm_conductor(st, loops={("D", "consider"): {}}, session_root=st.root, sid="t")
    assert second["conductor"] is first, "同一个工作区必须复用同一个主控（否则台账/预算不是同一份）"
    assert isinstance(first.backend, LlmBackend), "backend 没被换掉 ⇒ 会静默跑确定性实现"
    assert getattr(first, "backend_note", ""), "换 backend 这件事必须留痕"


def test_summoning_a_role_through_the_wired_conductor_actually_runs(tmp_path: pathlib.Path):
    """正控（真机读数抓出来的缺陷）：经模型驱动的主控派活，确定性实现要真的跑起来。

    §185 那批测试漏了这条路径：那个用例把子角色也登记进 `loops`（走 LLM 循环），
    于是 `LocalBackend` 一次都没走 —— 而 `wired_llm_conductor` 当时给内层 backend
    建的是 `LocalBackend(role_reg)`，没把 store 注进去 ⇒ 被召唤的角色在
    `factory(role, store=None)` 上炸。实测（2026-09-29，只读重放门槛 A）：
    `run-agent M` 派 H 做 review，两次都是
    `TypeError: factory(H) 需要一个 store（backend 的契约是 fn(*, store=...)）`，
    而台账里那两行长得像"H 自己失败了"。
    """
    st = Store(tmp_path / "ws")
    st.init()
    reset_cache()
    wiring = wired_llm_conductor(st, loops={}, session_root=st.root, sid="t")
    res = wiring["conductor"].summon("E", "list_experiments", {}, by="M")
    assert res.status == "done", (
        f"被召唤的角色没跑起来：status={res.status} outcome={res.outcome} "
        f"detail={getattr(res, 'detail', '')} error={getattr(res, 'error', '')}"
    )


def test_run_agent_without_a_key_is_not_checked_and_makes_no_request(tmp_path: pathlib.Path,
                                                                    monkeypatch, capsys):
    """负控（三态）：没有 key ⇒ 退出码 2，且一条模型调用记录都不许留下。"""
    monkeypatch.delenv("AGENTFLOW_MODEL_API_KEY", raising=False)
    reset_cache()
    rc = cli.cmd_run_agent(_args(tmp_path, role="D", task="随便", drive=[], max_steps=2, rounds=1,
                                 report_every=1))
    err = capsys.readouterr().err
    assert rc == 2, err
    assert "没查成" in err, err
    events, _ = SS.read_session(tmp_path / "ws", sid="t")
    assert not [e for e in events if e.get("kind") == "llm_call"], "没查成却记了模型调用"


def test_run_agent_drives_a_child_action_through_the_llm_loop(tmp_path: pathlib.Path, monkeypatch,
                                                              capsys):
    """正控（产品路径）：`--drive D.consider` ⇒ M 召唤 D 时 D 也走 LLM 循环，台账成链。"""
    monkeypatch.setattr(cli, "_agent_seam_factory", fake_seam_factory)
    reset_cache()
    SCRIPTS.clear()
    SCRIPTS.update({
        "M": [json.dumps({"summon": {"role": "D", "action": "consider",
                                     "params": {"qid": "q-1"}}}, ensure_ascii=False),
              json.dumps({"final": "交付：D 已跑过", "evidence": []}, ensure_ascii=False)],
        "D": [json.dumps({"note": "我先记一句", "evidence": []}, ensure_ascii=False),
              json.dumps({"final": "D 的结论", "evidence": []}, ensure_ascii=False)],
    })
    rc = cli.cmd_run_agent(_args(tmp_path, role="M", task="把这件事交给 D", drive=["D.consider"],
                                 max_steps=3, rounds=1, report_every=1))
    out = capsys.readouterr().out
    assert rc == 0, out
    st = Store(tmp_path / "ws")
    rows = sorted(st.rows("tasks"), key=lambda r: str(r.get("task_id")))
    assert rows, "台账里没有任何任务行"
    assert str(rows[-1].get("role")) == "D" and str(rows[-1].get("called_by")) == "M", rows
    events, _ = SS.read_session(tmp_path / "ws", sid="t")
    ends = [e for e in events if e.get("kind") == "agent_run_end"]
    assert {str(e.get("role")) for e in ends} >= {"M", "D"}, "D 没有跑自己的循环"
    # D 是走 LLM 循环的：它的循环记录落在 runs/ 下
    assert list((tmp_path / "ws" / "runs").glob("D-*.json")), "D 的循环产出没有落盘"


def test_a_bad_drive_spec_is_a_usage_error(tmp_path: pathlib.Path, capsys):
    """负控（用法错）：`--drive` 写成 `D`（没有动作）⇒ 退出码 2 且不建工作区。"""
    reset_cache()
    rc = cli.cmd_run_agent(_args(tmp_path, role="M", task="x", drive=["D"], max_steps=2, rounds=1,
                                 report_every=1))
    err = capsys.readouterr().err
    assert rc == 2 and "用法错" in err, err


def test_inbox_and_answer_round_trip_through_the_cli(tmp_path: pathlib.Path, capsys):
    """正控（用户频道有入口了）：提问 → `inbox` 列出来 → `answer` 写回去 → 清单变空。"""
    root = tmp_path / "ws"
    root.mkdir()
    out = U.ask_user(root, role="D", question="口径用哪个？", options=("A", "B"), timeout_sec=0,
                     sid="t")
    rc = cli.cmd_inbox(_args(tmp_path, sid="t"))
    listed = capsys.readouterr().out
    assert rc == 0 and out.qid in listed and "口径用哪个？" in listed, listed
    rc2 = cli.cmd_answer(_args(tmp_path, sid="t", qid=out.qid, text="用 B"))
    assert rc2 == 0, capsys.readouterr().err
    assert U.pending_questions(root, sid="t") == []
    replies = U.read_replies(root, role="D", sid="t")
    assert [r["answer"] for r in replies] == ["用 B"]


def test_answering_an_unknown_question_is_not_checked(tmp_path: pathlib.Path, capsys):
    """负控（三态）：回答一个不在待答清单里的问题号 ⇒ 退出码 2（没查成），不写事件。"""
    root = tmp_path / "ws"
    root.mkdir()
    rc = cli.cmd_answer(_args(tmp_path, sid="t", qid="q9999", text="随便"))
    err = capsys.readouterr().err
    assert rc == 2 and "没查成" in err, err
    events, _ = SS.read_session(root, sid="t")
    assert not [e for e in events if e.get("kind") == "user_answer"], "没查成却写了回答"


def test_run_agent_resume_skips_rounds_done_in_the_previous_segment(tmp_path: pathlib.Path,
                                                                   monkeypatch, capsys):
    """正控（长时驱动接进 CLI）：第二段带 `--resume` ⇒ 只跑没做过的轮，并如实报恢复轮数。"""
    monkeypatch.setattr(cli, "_agent_seam_factory", fake_seam_factory)
    reset_cache()
    SCRIPTS.clear()
    SCRIPTS.update({"D": [json.dumps({"final": "本轮结论", "evidence": []}, ensure_ascii=False)]})
    args = dict(role="D", task="把这件事推进下去", drive=[], max_steps=2, report_every=99,
                budget_usd=None, resume=False, stop_file=None)
    # 第一段：跑 2 轮（`--rounds 1` 是单次运行，不走自主轮那条路，也就没有检查点）
    rc1 = cli.cmd_run_agent(_args(tmp_path, rounds=2, **args))
    out1 = capsys.readouterr().out
    assert rc1 == 0, out1
    assert "检查点" in out1, out1
    from agentflow.autonomy import checkpoint_path, load_checkpoint

    root = tmp_path / "ws"
    assert load_checkpoint(root, "D")["completed_rounds"] == 2
    # 第二段：目标 4 轮，带 --resume ⇒ 只跑第 3、4 轮
    rc2 = cli.cmd_run_agent(_args(tmp_path, rounds=4, **{**args, "resume": True}))
    out2 = capsys.readouterr().out
    assert rc2 == 0, out2
    assert "2 轮是上一段做过的" in out2, out2
    assert "检查点" in out2, out2
    assert load_checkpoint(root, "D")["completed_rounds"] == 4
    assert checkpoint_path(root, "D").is_file()


def test_run_agent_refuses_to_resume_a_different_task(tmp_path: pathlib.Path, monkeypatch,
                                                      capsys):
    """负控（三态接进 CLI）：指纹不一致 ⇒ 退出码 2（没查成），且不发起任何调用。"""
    monkeypatch.setattr(cli, "_agent_seam_factory", fake_seam_factory)
    reset_cache()
    SCRIPTS.clear()
    SCRIPTS.update({"D": [json.dumps({"final": "本轮结论", "evidence": []}, ensure_ascii=False)]})
    args = dict(role="D", drive=[], max_steps=2, report_every=99, budget_usd=None, resume=False,
                stop_file=None)
    assert cli.cmd_run_agent(_args(tmp_path, rounds=2, task="第一件事", **args)) == 0
    capsys.readouterr()
    rc = cli.cmd_run_agent(_args(tmp_path, rounds=4, task="完全不同的第二件事",
                                 **{**args, "resume": True}))
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "checkpoint_mismatch" in out, out


def test_gate_without_a_key_is_unknown_not_pass(tmp_path: pathlib.Path, monkeypatch, capsys):
    """负控（三态，直接测 `cmd_gate`）：没接线 ⇒ 退出码 2，判据逐条落 `judge_not_wired`。

    这一条的要点是"没判成 ≠ 通过"：报告照样落盘、工作项照样写出，
    但结论必须是 `unknown`、退出码必须是 2 —— 折叠成 `pass` 就等于把"没查"读成"没问题"。

    刻意「不」替换 `cli._agent_seam_factory`：走的就是"环境里没有 key"那条真路。
    """
    monkeypatch.delenv("AGENTFLOW_MODEL_API_KEY", raising=False)
    root = tmp_path / "ws"
    root.mkdir()
    art = tmp_path / "稿.md"
    art.write_text("# 稿子\n\n一句话。\n", encoding="utf-8")
    rc = cli.cmd_gate(_args(tmp_path, name="g1", artifact=str(art), criterion=["overview.essence"],
                           json=False, pair=[], context="", disclaimer=""))
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "unknown" in out and "judge_not_wired" in out, out
    assert (root / "gates" / "g1.json").is_file(), "没判成也要留下报告（否则没人知道跑过）"


def test_gate_writes_a_report_and_work_items_when_a_criterion_fails(tmp_path: pathlib.Path,
                                                                    monkeypatch, capsys):
    """正控（直接测 `cmd_gate`）：判据判不通过 ⇒ `needs_work`、退出码 1、工作项落盘。"""
    monkeypatch.setattr(cli, "_agent_seam_factory", fake_seam_factory)
    SCRIPTS.clear()
    SCRIPTS.update({"H": ['{"verdict": "listing", "why": "只是在罗列", "findings": []}']})
    root = tmp_path / "ws"
    root.mkdir()
    art = tmp_path / "稿.md"
    art.write_text("# 稿子\n\n一句。两句。\n", encoding="utf-8")
    rc = cli.cmd_gate(_args(tmp_path, name="g2", artifact=str(art), criterion=["overview.essence"],
                            json=True, pair=[], context="", disclaimer=""))
    out = capsys.readouterr().out
    assert rc == 1, out
    payload = json.loads(out[out.index("{"):])
    assert payload["verdict"] == "needs_work" and payload["unknown_criteria"] == [], payload
    assert payload["work_items"], payload
    assert payload["work_items"][0]["who"] == "C", "高观点不达标该派给 C（FACULTY_FIXERS）"


def test_gate_on_a_missing_artifact_is_not_checked(tmp_path: pathlib.Path, capsys):
    """负控（三态）：交付物读不到 ⇒ 退出码 2，且一条判据都没跑、报告没落。"""
    rc = cli.cmd_gate(_args(tmp_path, name="g3", artifact=str(tmp_path / "没有这个文件.md"),
                            criterion=[], json=False, pair=[], context="", disclaimer=""))
    err = capsys.readouterr().err
    assert rc == 2 and "没查成" in err, err
    assert not (tmp_path / "ws" / "gates").exists(), "没查成却落了报告"


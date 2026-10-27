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
from agentflow.tokenmeter import TokenMeter
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


def fake_seam_factory(role: str, *, root: pathlib.Path, sid: str | None, usd_budget: float | None,
                      store: Any = None):
    """替身模型工厂：按角色取剧本（测试用它替换 `cli._agent_seam_factory`）。

    `store` 是 `draft/37` §64 加进来的：真工厂用它给缝接上账本（`meter=`）。
    替身「不」记账（剧本里的价是 0.0），但签名必须与真工厂一致 ——
    否则"调用方多传一个参数"这件事会在测试里变成 TypeError，
    而真机上它是"记账悄悄没接上"（本判据要防的那一类）。
    """
    gw = ScriptedGateway(SCRIPTS.get(role, ['{"final": "（没有剧本）", "evidence": []}']))
    return LlmSeam(role=role, session_root=root, gateway=gw, price=(0.0, 0.0), sid=sid,
                   usd_budget=usd_budget, meter=(TokenMeter(store) if store is not None else None))


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
    # 2026-10-19 口径：2 = 研究启动失败（连跑都没开始）。只换词，不放宽：
    # 改前断言的是"没查成"这四个字，现在断言新标签同样精确地在 stderr 里出现。
    assert "研究启动失败" in err, err
    events, _ = SS.read_session(tmp_path / "ws", sid="t")
    assert not [e for e in events if e.get("kind") == "llm_call"], "没查成却记了模型调用"


def test_run_agent_drives_a_child_action_through_the_llm_loop(tmp_path: pathlib.Path, monkeypatch,
                                                              capsys):
    """正控（产品路径）：`--drive D.consider` ⇒ M 召唤 D 时 D 也走 LLM 循环，台账成链。

    2026-10-26 起这一条多一步：业主裁定「最终 final 时应该是 M 下整棵树都已销号」
    （`agent_loop` 的结构完整性闸，判据 `tests/test_cascade_retire_closes_the_tree.py`）。
    于是"派了子就收工"的剧本会被受控拒绝，而且一拒就是三拍补救（每拍一次模型调用，
    实测 5 次调用才以 `final_refused`（退出码 5）收尾）—— 那不是缺陷，是收工门在
    正常工作：M 没有销号这一支，树就不干净。所以剧本按新契约补一步
    `conductor.retire_child`（名册名 `D1`：第一次召唤的 D 在名册上的名字），
    final 才落得下来。销号之后这一趟只花 3 次模型调用（派活 / 销号 / 收工）。
    """
    monkeypatch.setattr(cli, "_agent_seam_factory", fake_seam_factory)
    reset_cache()
    SCRIPTS.clear()
    SCRIPTS.update({
        "M": [json.dumps({"summon": {"role": "D", "task": "派活：把这件事办掉",
                                     "params": {"qid": "q-1"}}}, ensure_ascii=False),
              json.dumps({"tool": "conductor.retire_child",
                          "args": {"child_name": "D1", "reason": "D 交完了"},
                          "why": "收工之前把这一支销号"}, ensure_ascii=False),
              json.dumps({"final": "交付：D 已跑过", "evidence": []}, ensure_ascii=False)],
        "D": [json.dumps({"note": "我先记一句", "evidence": []}, ensure_ascii=False),
              json.dumps({"final": "D 的结论", "evidence": []}, ensure_ascii=False)],
    })
    rc = cli.cmd_run_agent(_args(tmp_path, role="M", task="把这件事交给 D", drive=["D.consider"],
                                 max_steps=5, rounds=1, report_every=1))
    out = capsys.readouterr().out
    assert rc == 0, out
    st = Store(tmp_path / "ws")
    # 只看实例行（`kind` 为空）：板项（终态回报的 `notice` 等）也是 `tasks` 的行
    # （业主 2026-10-08 裁 A1=甲），而这一条问的是"被召唤的那一件活"。
    rows = sorted((r for r in st.rows("tasks") if not str(r.get("kind") or "")),
                  key=lambda r: str(r.get("task_id")))
    assert rows, "台账里没有任何任务行"
    assert str(rows[-1].get("role")) == "D" and str(rows[-1].get("called_by")) == "M", rows
    events, _ = SS.read_session(tmp_path / "ws", sid="t")
    ends = [e for e in events if e.get("kind") == "agent_run_end"]
    assert {str(e.get("role")) for e in ends} >= {"M", "D"}, "D 没有跑自己的循环"
    # D 是走 LLM 循环的：它的循环记录落在 runs/ 下
    assert list((tmp_path / "ws" / "runs").glob("D-*.json")), "D 的循环产出没有落盘"
    # 剧本里那个名册名不是"测试知道答案"：销号真的落到了名册上，名字与状态都要对。
    from agentflow.secretary import Secretary

    rostered, problems = Secretary("M", root=st.root, store=st).roster_rows("t-000001")
    assert not problems, problems
    assert [(r.get("name"), r.get("role"), bool(r.get("retired"))) for r in rostered] == [
        ("D1", "D", True)], rostered



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


def test_the_gate_subcommand_has_retired_and_deliver_keeps_no_cli_dependency():
    """L-05c（`48-09 §4.10`）：`cli gate` 子命令退场，而语义判据与机械半都留着。

    改前必红：`build_parser()` 的 choices 里有 `gate`、`cli.cmd_gate` 存在、`cli.py` 里 import 着 `deliver`（`cmd_gate` 是它的唯一
    CLI 入口）。

    退场的依据（真机读数）：`gates/*.json` 0 份、`delivery_gate` 事件 0 —— 这个入口从来没人用过；而语义判据真的跑过（116
    份任务产物含 `claims_semantically_judged`，其中 44 份 > 0）。所以"没人用的 CLI"退场、"真在跑的判据"留着，两件事不许混为一谈。

    这一条同时钉住没有造出孤儿模块：`faculty_checks` 的机械半现在有真生产调用者（`statusreport` 那条链，B 的 EE-04）⇒ 判据断言那条链仍在。"""
    import pathlib as _p

    parser = cli.build_parser()
    sub = next(a for a in parser._subparsers._group_actions if a.choices)  # type: ignore[attr-defined]
    assert "gate" not in sub.choices, f"gate 子命令还在：{sorted(sub.choices)}"
    assert not hasattr(cli, "cmd_gate"), "cmd_gate 还在（子命令退场要一起删）"
    src = (_p.Path(__file__).resolve().parents[1] / "src" / "agentflow" / "cli.py").read_text(
        encoding="utf-8")
    assert "import deliver" not in src, "cli.py 还依赖 deliver（L-05c 的第 4 条）"
    # deliver.py / faculty_checks.py 都不许删（施工单逐字）；faculty_checks 仍有生产调用者
    from agentflow import deliver as _D  # noqa: F401  （存在性）
    from agentflow import statusreport as _SR

    text = _p.Path(_SR.__file__).read_text(encoding="utf-8")
    assert "faculty_checks" in text, "faculty_checks 失去了唯一的生产调用者（孤儿模块）"
    assert "FACULTY_LAYERS" in text or True   # 锚点在 agent_prompts，下面用另一条判据守着
    from agentflow import agent_prompts as _AP

    layers = getattr(_AP, "FACULTY_LAYERS", ())
    assert len(tuple(layers)) >= 5, f"`FACULTY_LAYERS` 锚点被动了：{layers!r}"


def test_gate_retirement_keeps_the_semantic_criteria_alive():
    """L-05c 的另一半（`draft/44` 的警告逐字）：别把"CLI 没人用"误读成"判据没人用"。

    `deliver.gate` 保留 + 登记为已决定的例外（它是第二套交付闸门，与 C 的收工门
    同族重叠 ⇒ 再给它接一个新入口会造出"两套闸门各说一套"）。它的状态是
    "有 `tests/test_deliver.py` 守着、零生产调用者" —— 这一条钉住"零调用者"这件事
    是如实登记的，而不是靠编一个假入口。
    """
    import pathlib as _p

    src_root = _p.Path(__file__).resolve().parents[1] / "src" / "agentflow"
    users = []
    for path in src_root.rglob("*.py"):
        if path.name == "deliver.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "import deliver" in text or "deliver.gate(" in text or "deliver as" in text:
            users.append(path.name)
    assert users == [], (
        "deliver 出现了新的生产调用者（那会造出第二套闸门入口）："
        f"{users} —— 如实登记为『零生产调用者 + 有 tests/test_deliver.py 守着』")
    # 而它的判据本体仍然在（不许删）
    assert (src_root / "deliver.py").is_file()
    assert (_p.Path(__file__).resolve().parents[0] / "test_deliver.py").is_file(), \
        "deliver 的判据文件被删了（施工单：不许删 `deliver.py`）"


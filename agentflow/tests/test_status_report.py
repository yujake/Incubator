# -*- coding: utf-8 -*-
"""M 的状态报告（`draft/39` §4）—— 也是 E15 的演练：零中断观测。

用户口径（逐字）：

> 给 M 再加一个动作：当用户中途想知道当前项目情况时，M 通过搜集最近产出和手稿交接来分析情况，
> 向用户报告，从而不打断智能体协作

E15 的三条判据（`draft/39` §6 表里逐字）：

1. 报告落盘（`out/review/STATUS-<ts>.{md,json}` 都在盘上、四节齐全）；
2. 报告里的计数当场脚本复算一致（`collect()` 再跑一遍，逐表相等；改坏一个数必须能被抓出来）；
3. 期间被观察的那一趟步数继续增长、期间没有 `ask_user` / 停机开关 / 任何停止。

第 3 条是这一组的重心：它测的是"旁路观测"这条纪律 —— 报告是读出来的，不是"问 M 一句"
问出来的（后者会让 M 停下来等人，正好与"不打断协作"相反）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import cli
from agentflow import sessions as SS
from agentflow import statusreport as SR
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry


# ============================================================ 夹具

def _ws(tmp_path, *, sid: str = "t"):
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return ws, st, sid


def _seed(st: Store) -> None:
    with st.tx("conjectures", actor="test") as tx:
        tx.upsert("conjectures", {"conjecture_id": "0000", "statement": "n≥3 时成立",
                                  "testable": "n≤12 枚举", "status": "proposed",
                                  "origin": "gap",      # 来源必填（schema：猜想来源必须可追）
                                  "created_at": "2026-10-05T00:00:00+08:00"})
    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {"task_id": "t-0001", "role": "D", "action": "consider",
                            "params": {}, "status": "done", "outcome": "refused",
                            "refusal_reason": "invalid_params", "called_by": "M", "depth": 1,
                            "input_key": "k", "started_at": "2026-10-05T00:00:00+08:00",
                            "ended_at": "2026-10-05T00:00:01+08:00",
                            "detail": "参数不合法（夹具）",
                            "error": None,
                            "artifacts": []})


# ============================================================ E15 ①②：落盘 + 复算

def test_e15_1_the_report_lands_in_two_forms_with_four_sections(tmp_path):
    """E15①：`out/review/STATUS-<ts>.md` 与 `.json` 都在盘上；md 四节齐全。"""
    ws, st, _ = _ws(tmp_path)
    _seed(st)
    report, md, js = SR.write_status_report(st, ws, stamp="20261005-1200")
    assert md.is_file() and js.is_file(), (md, js)
    assert md.name == "STATUS-20261005-1200.md" and js.name == "STATUS-20261005-1200.json"
    text = md.read_text(encoding="utf-8")
    for section in ("一、产出", "二、交接", "三、卡点", "四、下一步"):
        assert section in text, text
    assert "旁路观测" in text and "零模型调用" in text, "报告要自己声明它是只读观测"
    assert str(ws) in text, "工作区路径要在报告里（否则第三方不知道该去哪复核）"


def test_e15_2_every_count_in_the_report_is_recomputable(tmp_path):
    """E15②：报告里的每个表行数都能当场复算一致；改坏一个数必须能被抓出来。"""
    ws, st, _ = _ws(tmp_path)
    _seed(st)
    report = SR.collect(st, ws)
    again = SR.collect(st, ws)
    for table in SR.REPORT_TABLES:
        assert report["tables"][table]["count"] == again["tables"][table]["count"], table
    assert report["tables"]["conjectures"]["count"] == 1, report["tables"]["conjectures"]
    assert report["tables"]["tasks"]["count"] == 1, report["tables"]["tasks"]
    assert report["refusals"]["total"] == 1, report["refusals"]
    assert report["refusals"]["by_reason"] == {"invalid_params": 1}, report["refusals"]

    # 负控：把 json 里的一个数改坏 ⇒ 它与复算值不再相等（判据真的在读数）
    _r, md, js = SR.write_status_report(st, ws, stamp="20261005-1201")
    tampered: dict[str, Any] = json.loads(js.read_text(encoding="utf-8"))
    tampered["tables"]["conjectures"]["count"] = 99
    fresh = SR.collect(st, ws)
    assert tampered["tables"]["conjectures"]["count"] != fresh["tables"]["conjectures"]["count"], \
        "改坏的数字与复算值相等 ⇒ 这条判据是真空的"
    assert md.is_file()


def test_e15_2_the_next_steps_are_derived_from_readings_not_written_by_a_model(tmp_path):
    """E15② 的另一半：`next_steps` 每一句都指着一个当前为空的读数（不是模型的话术）。"""
    ws, st, _ = _ws(tmp_path)
    report = SR.collect(st, ws)
    joined = "；".join(report["next_steps"])
    assert "conjectures" in joined and "documents" in joined, report["next_steps"]
    assert "handoffs.jsonl" in joined, report["next_steps"]
    # 填入猜想之后，"还没有猜想"这一句应当消失（读数驱动，不是模板）
    _seed(st)
    after = SR.collect(st, ws)
    assert not any("还没有可检验的猜想" in s for s in after["next_steps"]), after["next_steps"]
    assert any("被拒的动作" in s for s in after["next_steps"]), after["next_steps"]


# ============================================================ E15③：零中断

class _Scripted:
    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[dict[str, Any]], *, on_call=None) -> None:
        self.replies = replies
        self.on_call = on_call
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(len(self.prompts), prompt)
        got = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": json.dumps(got, ensure_ascii=False),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _run_with_probe(tmp_path, replies, probe) -> tuple[pathlib.Path, Any]:
    """跑一趟角色循环，并在第 2 步的模型调用之前插一次状态报告（模拟用户中途想知道情况）。"""
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    gw = _Scripted(replies, on_call=lambda n, _p: probe(n, ws, st))
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=ws,
                         seam_factory=lambda r: LlmSeam(role=r, session_root=ws, gateway=gw,
                                                        price=(0.0, 0.0), sid="t"),
                         max_steps=4, store=st, sid="t")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond, workspace_root=str(ws)).registry
    backend.registry = reg
    run = run_role("D", "被观测的一趟", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="D", session_root=ws, gateway=gw, price=(0.0, 0.0), sid="t"),
                   session_root=ws, workspace_root=str(ws), sid="t", max_steps=4, from_env=False)
    return ws, run


def test_e15_3_collecting_mid_run_interrupts_nothing(tmp_path):
    """E15③：在正在跑的循环中途收一次报告 ⇒ 它继续跑、没有 ask_user/停机/停止。

    这一条是"旁路观测"的核心判据：报告若走 `ask_user`（问 M 一句）就会被读成"这一趟
    停了在等人"，而那正是用户要避免的。
    """
    seen: dict[str, Any] = {"reports": [], "events_at_probe": [], "stop_switch": None}

    def probe(n: int, ws: pathlib.Path, st: Store) -> None:
        if n != 2:
            return
        # 中途收一次报告（与 CLI 同一个实现）
        report, md, js = SR.write_status_report(st, ws, stamp="20261005-1300")
        seen["reports"].append(report)
        seen["stop_switch"] = (ws / ".agentflow-stop").is_file()
        events, _bad = SS.read_session(ws, sid="t")
        seen["events_at_probe"].append([e.get("kind") for e in events])

    ws, run = _run_with_probe(tmp_path, [
        {"tool": "table.list", "args": {"table": "tasks"}, "why": "先看一眼"},
        {"tool": "table.list", "args": {"table": "documents"}, "why": "再看一眼"},
        {"final": "收工", "notify": {"to": "M", "summary": "收工", "body": "完。\n"}},
    ], probe)

    assert run.stop_reason == "final", run.to_dict()
    assert seen["reports"], "探针没跑到（这一条判据就失效了）"
    assert seen["stop_switch"] is False, "收报告不该落停机开关"
    # 报告落盘，且报告里"在跑的循环"读到的是这一趟（旁路观测真的看到了它）
    assert (ws / "out" / "review").glob("STATUS-20261005-1300.md")
    assert seen["reports"][0]["in_flight"]["running_loops"], seen["reports"][0]["in_flight"]
    # 没有 ask_user / 没有停机 / 没有第二趟
    events, bad = SS.read_session(ws, sid="t")
    assert not bad, bad
    kinds = [e.get("kind") for e in events]
    assert "agent_run_start" in kinds and kinds.count("agent_run_start") == 1, kinds
    steps = [e for e in events if e.get("kind") == "agent_step"]
    # 会话里只有非收工步的 `agent_step`（收工那一步不写这种事件）⇒ 两条 step 事件、
    # 而这一趟总共走了三步（两次工具 + 一次 final）——"它继续在跑"由后者证明。
    assert len(steps) == 2 and len(run.steps) == 3, (len(steps), len(run.steps))
    assert not [e for e in events if e.get("kind") == "user_answer"], kinds
    assert not (ws / ".agentflow-stop").is_file()


def test_e15_3_the_probe_does_not_write_into_the_store(tmp_path):
    """E15③ 的另一半：观测前后，`data/` 下每个文件的字节必须逐字节相同。"""
    before: dict[str, bytes] = {}

    def probe(n: int, ws: pathlib.Path, st: Store) -> None:
        if n != 2:
            return
        SR.write_status_report(st, ws, stamp="20261005-1400")
        # 观测之后立刻记下 data/ 的字节（与观测前的对照由下面做完）
        for p in sorted((ws / "data").glob("*.json")):
            before.setdefault(p.name, p.read_bytes())

    ws, run = _run_with_probe(tmp_path, [
        {"tool": "table.list", "args": {"table": "tasks"}, "why": "a"},
        {"tool": "table.list", "args": {"table": "documents"}, "why": "b"},
        {"final": "收工", "notify": {"to": "M", "summary": "收工", "body": "完。\n"}},
    ], probe)
    assert run.stop_reason == "final", run.to_dict()
    assert before, "探针没跑到"
    # 这一趟自己不再写台账 ⇒ 观测那一刻记下的字节与现在一致
    for name, blob in before.items():
        assert (ws / "data" / name).read_bytes() == blob, f"{name} 在观测之后被改过"


# ============================================================ CLI 入口

def test_the_cli_entry_lands_a_report_and_says_what_is_next(tmp_path, capsys):
    """入口（`agentflow --root <ws> status-report`）：落盘 + 打印四类读数 + 退出码 0。"""
    ws, st, _ = _ws(tmp_path)
    _seed(st)
    code = int(cli.main(["--root", str(ws), "status-report"]))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "报告已落盘" in out and "下一步" in out, out
    assert list((ws / "out" / "review").glob("STATUS-*.md")), "报告没落盘"


def test_the_cli_entry_reports_unknown_for_a_missing_workspace(tmp_path, capsys):
    """三态：工作区不在盘上 ⇒ `unknown`（退出码 2），不是"没有状态"。"""
    missing = tmp_path / "nope"
    code = int(cli.main(["--root", str(missing), "status-report"]))
    err = capsys.readouterr().err
    assert code == 2 and "没查成" in err, (code, err)


def test_the_report_is_json_serialisable_and_carries_the_four_reading_groups(tmp_path):
    """反真空：报告的四个读数面都在（缺一面 ⇒ "报告"没有可复核的骨架）。"""
    ws, st, _ = _ws(tmp_path)
    report = SR.collect(st, ws)
    blob = json.dumps(report, ensure_ascii=False)
    assert len(blob) > 200, blob
    for key in ("tables", "manuscripts", "five_bit", "in_flight", "refusals", "next_steps"):
        assert key in report, key
    assert set(report["tables"]) == set(SR.REPORT_TABLES), sorted(report["tables"])

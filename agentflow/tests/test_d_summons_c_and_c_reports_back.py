# -*- coding: utf-8 -*-
"""D 唤起 C、C 向 D 汇报（2026-10-20 业主裁定：改回 C 无出边、由 D 唤起 C）。

裁定与它要落的东西：上一批（2026-10-19）给 C 开了一条 `C → D` 的出边，业主现在把它改回原设定 ——
C 没有出边，链条是 `D → C` 单向：要「候选的更短路径」由 D 自己用 `conductor.summon` 派 C；C 的
"汇报"就是它的返回值（它没有出边、也不许给它加一条把话送回去的通道）。所以这一组守的不是"表里有
个字符串"，而是这条单向链真的走得通、且报告真的回到了 D 的手上：

① 正控：D（桩模型）走真的 `run_role` 循环，用 `summon` 形状派 C（桩 C 跑真循环，用
`analysis.register_report` 落一份 `analysis_reports` 形态的报告）⇒ D 的下一步里拿得到那份报告
（`summon` 返回值里带着报告号与路径，且它们出现在 D 第二步的提示词里）；`tasks` 里那条 C 任务
`called_by == "D"`、`parent_task_id == D 的任务号`。
② 反真空：`C.edges == ()` 且 `ALLOWED_EDGES["C"] == frozenset()`，边总数 32（2026-10-20 同日业主裁定
「M 不再直连 V」：33 → 32）—— 不是"我没找到那条边"，是"它真的不在权限面上"。
③ 负控：把 `ALLOWED_EDGES["C"]` 塞成 `{"D"}` ⇒ ② 必须红（证明 ② 真的在读权限面）。
④ 负控：把 D 的 `_do_summon` 改成"不读返回值直接 final" ⇒ ① 必须红（证明 ① 守的是"报告回到了 D
手上"，不是"派出去过"）。
为什么 ④ 改在 `_do_summon` 而不是 `conductor.summon`：④ 要考的正是"D 把返还值用了没有"这件事本身 —— 召唤照样发生（台账那两格仍然对），只是 D 把答案扔了；
若改在 `conductor.summon`，那条 C 任务行
都不会有，红的就变成"没派"，与命题无关。判据口径与 `test_two_hop_summon.py` 同一份：真循环、真边
闸门、真台账，只把模型换成照剧本回答的替身（不联网、不调 API）。"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentflow import capabilities as C
from agentflow.agent_loop import AgentLoop, LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.specs import builtin_specs
from agentflow.store import Store
from agentflow.tools import build_registry

#: 边总数的现读（2026-10-20 改回 C 无出边之后：34 → 33；同日业主裁定「M 不再直连 V」：
#: 33 → 32 —— V 的两个入口是 F 与 B，M→V 撤掉）。
EXPECTED_EDGE_TOTAL = 32

#: 这一趟要跑的两条循环：D 派活、C 干自己的活（空动作 ⇒ 角色级那一档）。
LOOPS: dict[tuple[str, str], dict] = {("D", ""): {}, ("C", ""): {}}

#: C 登记的那份报告（`analysis_reports` 那行的形状）。
REPORT_SUMMARY = "绕行长度 4 → 2：中间那一步可以省掉"
REPORT_MARKDOWN = ("## 候选的更短路径\n\n"
                   "关键那一步：把 `rel:` 的两跳合成一跳。\n"
                   "边界：这是图读数，不是数学结论。\n")


class _Scripted:
    """照剧本回答的替身模型：每条回复可以是字符串，也可以是 `prompt -> str`。

    为什么允许给函数：C 的"汇报"必须带着这一趟真的分配到的报告号走，
    而号是 `analysis.register_report` 在运行期才发的 ⇒ 固定字符串做不到
    "C 的 final 里写着那份报告的号"。给函数就等于让替身模型"读到上一步的结果
    再回话"，那正是真模型做的事（提示词里带着上一步的 `框架执行结果`）。
    """

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None, **kw):
        self.prompts.append(prompt)
        reply = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        text = reply(prompt) if callable(reply) else str(reply)
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


#: 观测层把工具结果的 `data` 摊平一层成 `data.report_id` 这样的键
#: （`_flatten_one_level`）；嵌套形态下前面还会有转义的反斜杠 ⇒ 两种都要认得出。
_RID_RE = re.compile(r'report_id"?\s*:\s*"?([^",\\]+)')
_PATH_RE = re.compile(r'markdown_path"?\s*:\s*"?([^",\\]+)')


def _report_call(prompt: str) -> str:
    """C 的第一步：把这次图读数登记进 `analysis_reports`（唯一的写入口）。"""
    return json.dumps({"tool": "analysis.register_report",
                       "args": {"kind": "paths", "summary": REPORT_SUMMARY,
                                "markdown": REPORT_MARKDOWN},
                       "why": "把图读数登记进台账交给派我的人"},
                      ensure_ascii=False)


def _report_final(prompt: str) -> str:
    """C 的第二步：汇报就是这一句话（带着报告号与路径），随返回值交回 D。

    提示词里上一步的 `框架执行结果` 是转义过的 JSON（观测层把 `data` 当字符串再
    dump 一次 ⇒ 里面的引号前面多了反斜杠）⇒ 先把那一层转义还原，再读号。
    这正是模型在真机上做的事：读上一步的结果，再回一句话。
    """
    text = prompt.replace('\\"', '"')
    rid = _RID_RE.search(text)
    path = _PATH_RE.search(text)
    return json.dumps({"final": (f"报告 {rid.group(1) if rid else '（没拿到号）'} 已登记；"
                                 f"路径 {path.group(1) if path else '（没拿到路径）'}"),
                       "evidence": []}, ensure_ascii=False)


SCRIPTS: dict[str, list] = {
    "D": [
        # 第一步：D 自己唤起 C（不给动作 —— 派活不点能力，S2 口径）
        json.dumps({"summon": {"role": "C",
                               "task": "给出这条链上可能的更短证明路径，并登记成一份分析报告",
                               "params": {},
                               "why": "候选路径是 C 的关系分析面，D 自己要报告"},
                    "why": "要候选路径就派 C"},
                   ensure_ascii=False),
        # 第二步：拿到 C 的报告之后再收工
        json.dumps({"final": "已按 C 的报告立猜想", "evidence": []}, ensure_ascii=False),
    ],
    "C": [
        _report_call,
        _report_final,
    ],
}


def _world(tmp_path: pathlib.Path):
    """最小的真接线：store + LlmBackend（D / C 都跑真循环）+ 真工具面。"""
    st = Store(tmp_path / "ws")
    st.init()
    gateways = {role: _Scripted(replies) for role, replies in SCRIPTS.items()}
    # 内层后端空着：这两条活都由模型驱动（空动作也走循环，见 `LlmBackend.call`）。
    backend = LlmBackend(
        inner=LocalBackend({}), loops=LOOPS, session_root=st.root,
        seam_factory=lambda role: LlmSeam(role=role, session_root=st.root,
                                          gateway=gateways[role],
                                          price=(0.0, 0.0), sid="t"),
        max_steps=6, store=st, sid="t")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond, workspace_root=str(st.root))
    backend.registry = built.registry
    return st, cond, built.registry, gateways


def _run_d(tmp_path: pathlib.Path):
    st, cond, reg, gateways = _world(tmp_path)
    run = run_role("D", "把这条链上可能的更短路径立成一条可判猜想", store=st,
                   registry=reg, conductor=cond,
                   seam=LlmSeam(role="D", session_root=st.root, gateway=gateways["D"],
                                price=(0.0, 0.0), sid="t"),
                   workspace_root=str(st.root), sid="t", from_env=False, max_steps=6)
    return st, run, gateways


def _summon_step(run) -> dict:
    steps = [s for s in run.steps if s.shape == "summon"]
    assert len(steps) == 1, (
        f"这一趟应当只有一次唤起（D→C），实际 {[s.shape for s in run.steps]}")
    return steps[0].result


# ============================================================ ① 正控：报告真的回到 D 手上


def _assert_the_report_comes_back_to_d(tmp_path: pathlib.Path) -> None:
    """① 的全部断言（负控 ④ 也调它 —— 那一条要证明的正是"这些断言真的会红"）。"""
    st, run, gateways = _run_d(tmp_path)
    assert run.stop_reason == "final", run.to_dict()

    res = _summon_step(run)
    assert res.get("ok") is True, res
    assert res.get("task_id"), "被受理的召唤必须落一个台账号"

    # (a) 返回值里就有那份报告：C 的 final 带着报告号与路径（"汇报 = 返回值"）
    path = str(res.get("llm_run_path") or "")
    assert path, f"summon 返回值里没有 C 那一趟的落点：{res}"
    assert pathlib.Path(path).exists(), f"返回值给的落点在盘上不存在：{path}"
    artifact = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    tool_results = [s for s in artifact.get("steps", [])
                    if str((s.get("payload") or {}).get("name")) == "analysis.register_report"]
    assert tool_results, f"C 那一趟没有登记报告（步骤：{artifact.get('steps')}）"
    data = (tool_results[0].get("result") or {}).get("data") or {}
    rid, md_path = str(data.get("report_id") or ""), str(data.get("markdown_path") or "")
    assert rid and md_path, f"登记结果里没有报告号 / 路径：{data}"

    final = str(res.get("final") or "")
    assert rid in final and md_path in final, (
        f"C 的汇报（返回值里的 final）没有带回报告号与路径：{final!r}")

    # (b) 台账里那一行是真的（不是只在返回值里写着）
    rows = [r for r in st.rows("analysis_reports") if str(r.get("report_id")) == rid]
    assert len(rows) == 1, f"analysis_reports 里没有 {rid} 那一行：{st.rows('analysis_reports')}"
    assert rows[0]["kind"] == "paths" and rows[0]["summary"] == REPORT_SUMMARY, rows[0]
    # `markdown_path` 是工作区相对路径（`reports/<rid>-<kind>.md`）⇒ 按工作区根解析
    assert (st.root / md_path).exists(), (
        f"报告正文没有真的落盘：{md_path}（工作区 {st.root}）")

    # (c) D 的下一步拿得到它：第二步的提示词里逐字有报告号与落点那一格
    prompts = gateways["D"].prompts
    assert len(prompts) >= 2, f"D 只调了一次模型（{len(prompts)}）⇒ 没有'下一步'可考"
    assert rid in prompts[1], (
        "D 的第二步提示词里读不到 C 的报告号 ⇒ 报告没有回到 D 的手上："
        f"{prompts[1][-800:]}")
    assert "llm_run_path" in prompts[1], (
        "D 的第二步提示词里连 C 那一趟的落点都没有 ⇒ 它拿不到能去读的那一份："
        f"{prompts[1][-800:]}")

    # (d) 台账上的父子关系：这一次 C 是 D 唤起的
    tasks = st.rows("tasks")
    d_row = next((r for r in tasks
                  if str(r.get("role")) == "D" and str(r.get("called_by")) == "user"), None)
    assert d_row is not None, (
        f"台账里没有 D 那一趟的开场行："
        f"{[(r.get('task_id'), r.get('role'), r.get('called_by')) for r in tasks]}")
    d_task = str(d_row["task_id"])
    c_rows = [r for r in tasks if str(r.get("role")) == "C"]
    assert len(c_rows) == 1, (
        f"这一趟该只有一行 C 任务，读到 {[(r.get('task_id'), r.get('role')) for r in tasks]}")
    assert str(c_rows[0]["called_by"]) == "D", c_rows[0]
    assert str(c_rows[0]["parent_task_id"]) == d_task, c_rows[0]


def test_positive_d_summons_c_and_the_report_comes_back(tmp_path: pathlib.Path) -> None:
    """正控：D 派 C ⇒ C 的报告随返回值交回 ⇒ D 下一步读得到它，台账上 C 的父是 D。"""
    _assert_the_report_comes_back_to_d(tmp_path)


# ============================================================ ② 反真空：C 真的没有出边


def _assert_c_has_no_outgoing_edge() -> None:
    """② 的全部断言（负控 ③ 也调它）。"""
    spec = builtin_specs()["C"]
    assert tuple(spec.edges) == (), (
        f"C 的出边又变成 {spec.edges!r} 了 —— 2026-10-20 业主裁定：C 无出边、由 D 唤起 C")
    assert C.ALLOWED_EDGES["C"] == frozenset(), (
        f"派生层（ALLOWED_EDGES['C']）不是空的：{sorted(C.ALLOWED_EDGES['C'])}")
    total = sum(len(v) for v in C.ALLOWED_EDGES.values())
    assert total == EXPECTED_EDGE_TOTAL, (
        f"边总数是 {total}，不是 {EXPECTED_EDGE_TOTAL} —— 改回 C 无出边之后应当少一条")


def test_the_spec_and_the_derived_table_say_c_has_no_outgoing_edge() -> None:
    """② 反真空：声明层与派生层都读得到"C 无出边"，且边总数回到 33。

    "我没找到那条边"与"它真的不在权限面上"必须分得开：这一条同时读
    `specs.c.SPEC.edges`（声明层）与 `capabilities.ALLOWED_EDGES`（派生层），
    并数一遍总数 —— 三层读数同时说"C 出边为空"才算数。
    """
    _assert_c_has_no_outgoing_edge()


def test_negative_control_spec_and_table_are_really_read(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 负控：把 `ALLOWED_EDGES["C"]` 塞成 `{"D"}` ⇒ ② 必须红。

    这一条防的是"② 只是在背一句写死的话"：它读的必须是那张权限表，
    表一变，它就当场不成立。
    """
    with monkeypatch.context() as mp:
        mp.setitem(C.ALLOWED_EDGES, "C", frozenset({"D"}))
        with pytest.raises(AssertionError) as exc:
            _assert_c_has_no_outgoing_edge()
    assert "ALLOWED_EDGES" in str(exc.value) or "出边" in str(exc.value), (
        f"② 红是红了，但不是因为读到那张权限表变了：{exc.value}")
    # 收尾：patch 撤掉之后同一条断言必须重新成立（负控的负控）
    _assert_c_has_no_outgoing_edge()


# ============================================================ ④ 负控：D 不读返回值 ⇒ ① 红


#: 改前的 `_do_summon`（负控 ④ 用它真的把活派出去，只把答案扔掉）。
_REAL_DO_SUMMON = AgentLoop._do_summon


def _summon_that_throws_the_answer_away(self, payload):
    """"派了就不管了"：召唤照发（台账那两格仍然对），C 的返回值一律不往下一步带。

    这正是 ① 要排除的那种写法 —— 派活成功、台账漂亮、而 D 从没读过 C 说了什么。
    """
    out = _REAL_DO_SUMMON(self, payload)
    for key in ("final", "payload", "llm_run_path"):
        out.pop(key, None)
    return out


def test_negative_control_a_summon_that_never_reads_back_is_caught(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 负控：把 D 的 summon 改成"不读返回值直接 final" ⇒ ① 必须红。"""
    with monkeypatch.context() as mp:
        mp.setattr(AgentLoop, "_do_summon", _summon_that_throws_the_answer_away)
        with pytest.raises(AssertionError) as exc:
            _assert_the_report_comes_back_to_d(tmp_path)
    assert "落点" in str(exc.value) or "报告号" in str(exc.value), (
        f"① 红是红了，但不是因为'报告没回到 D 手上'：{exc.value}")

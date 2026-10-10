# -*- coding: utf-8 -*-
"""三处「LLM 的工作结果到不了账本」的结构性缺口：判据 + 负控（2026-10-08）。

这个文件是新加的判据，不改任何既有的判据，也不重冻快照。每一处都写清
"改前必红"的形态与"改后断言什么"，并给一条负控（证明判据不是恒真）。

## 缺口 1（真丢）：原生工具面下 `framework_final` 的 `notify` 到不了循环

`llmseam.META_FUNCTIONS` 里 `framework_final` 的参数 schema 先前只有
`final` / `evidence`，而 `ToolFace.to_shape` 翻这个形状时只重建这两个键、
其余参数静默丢弃 ⇒ 提示词（`agent_prompts.py` §7）要求非 M 角色收工填的
`notify`（交接手稿那一栏）在原生工具面下结构上给不出来。

改法：schema 补 `notify`（字段表与 `agent_loop.NOTIFY_FIELDS` 同源），
`to_shape` 原样透传（缺省时不凭空造一个空表）。

## 缺口 2（真丢）：收工那一步不落 `agent_step` ⇒ notify / evidence / 读数不落盘

`agent_loop.AgentLoop.run` 的 `shape == "final"` 那一支在 `break` 之前只 append
到内存 `run.steps`，而 `agent_step` 事件落在 `break` 之后的公共尾段落 ⇒
收工这一步的事件一条都没有（`tests/test_status_report.py` 那条
`len(steps) == 2 and len(run.steps) == 3` 把这个形态逐字钉着）。
实测后果：`agent_run_end` 的键集里没有 `evidence` / `notes` / 收工那一步的载荷，
模型填的 `notify` 只活在内存里。

改法：不走"给 final 补一条 `agent_step`"（那会让 `resume_transcript` 重建的简报
多一行、与当时那一份不再逐字相等 —— 代价更大），而是把 `evidence` / `notes` /
`final_payload` 三个键落进 `agent_run_end`。

## 缺口 3（真会丢）：`except Exception: secretary = None` 无日志无事件

`run_role` 里秘书装配失败是 fail-open（这一趟照跑），但那一支此前不留任何痕迹：
之后每次 `handoff` 都返回 `ok is False`，而盘上读不出"哪一步、因为什么没装配"。

改法：与既有风格一致 —— 落一条 `agent_note` 事件 + 把同一句话并进 `run.notes`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import agent_loop as AL
from agentflow import llmseam as LL
from agentflow import sessions as SS
from agentflow.agent_loop import run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "gaps"

#: 一份合法的 `notify`（形状口径见 `agent_loop.notify_shape_problem`：
#: `to` / `summary` / `body` 必填，`refs` / `why` 可选）。`refs` 留空是有意的：
#: 填一个不存在的 `exp:`/`lit:` 号会被 `manuscripts.ref_problem` 判成悬空引用，
#: 那会把这一条判据变成"在测 ref 校验"。
NOTIFY: dict[str, Any] = {
    "to": "M",
    "summary": "交给 M：X 的族构造证据",
    "body": "## 我做了什么\n扫了 n≤12。\n## 依据\n见这一趟的步骤\n## 要你做什么\n判定 n=14。\n",
    "refs": [],
}


class _Gate:
    """按脚本回原生 `tool_calls` 或文本的替身网关（不联网）。

    与 `tests/test_native_tool_calls.py::_StubGateway` 同形：缺口 1 只有在
    "上游给了结构化工具调用"那条路上才存在，用文本回落那条路测它等于测另一件事。
    """

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 max_tokens: int | None = None, tools: Any = None,
                 tool_choice: str = "auto") -> Any:
        self.prompts.append(prompt)
        item = self.script.pop(0) if self.script else {"tool_calls": []}
        return type("R", (), {"ok": True, "text": item.get("text", ""),
                              "tool_calls": tuple(item.get("tool_calls", ())),
                              "tokens_in": 1, "tokens_out": 1, "error_detail": "",
                              "error_kind": ""})()


def _registry(tmp_path: pathlib.Path) -> tuple[Store, Any, pathlib.Path]:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    return st, reg, ws


def _native_final(**args: Any) -> dict:
    return {"tool_calls": [{"id": "c1", "name": "framework_final",
                            "arguments": json.dumps(args, ensure_ascii=False)}]}


def _events(root: pathlib.Path) -> list[dict]:
    events, problems = SS.read_session(root, sid=SID)
    assert not problems, problems
    return events


# ============================================================ 缺口 1：原生面

def test_the_advertised_final_schema_carries_the_notify_column():
    """正控（缺口 1 的广告面）：`framework_final` 的参数 schema 里有 `notify`，
    且它的字段表与 `agent_loop.NOTIFY_FIELDS` 逐字同一份。

    改前必红：`framework_final.parameters.properties` 只有 `{evidence, final}` ——
    模型的传输层看不到这一格，提示词里那句"收工要填 notify"就成了空话。

    为什么断言"逐字同一份字段表"而不是"有个叫 notify 的键"：两处字段表漂了
    （广告一份、收进去判另一份）正是本仓反复登记的形态；这一条把两份钉在一起。
    """
    meta = {name: schema for name, _shape, schema in LL.META_FUNCTIONS}
    fin = meta["framework_final"]
    assert "notify" in fin["properties"], sorted(fin["properties"])
    notify = fin["properties"]["notify"]
    assert notify.get("type") == "object", notify
    assert tuple(sorted(notify["properties"])) == tuple(sorted(AL.NOTIFY_FIELDS)), (
        f"广告面的 notify 字段表 {sorted(notify['properties'])} "
        f"≠ `agent_loop.NOTIFY_FIELDS` {sorted(AL.NOTIFY_FIELDS)}")
    # 收工是"一步一件事"里的最后一件事：`final` 仍然必填，`notify` 不进 required
    # （L-05e 之后"没填/填错都不打回，只落读数" —— 把它列成传输层必填会把收工拒掉）。
    assert fin["required"] == ["final"], fin["required"]
    assert "notify" not in fin["required"], fin["required"]
    # 收件人那一格的口径与提示词一致（`ALL` = 给所有人）
    assert "ALL" in notify["properties"]["to"]["description"], notify["properties"]["to"]


def test_a_native_final_with_notify_carries_it_through_verbatim(tmp_path: pathlib.Path):
    """正控（缺口 1 的主判据）：原生工具面的 `final` 带 `notify` ⇒ 形状里有它，
    且逐字等于调用方给的那一份。

    改前必红：`to_shape` 只重建 `{final, evidence}`，`notify` 被静默丢弃
    （实测：`{"final": "结论文本", "evidence": ["e-1"]}`）。
    """
    st, reg, ws = _registry(tmp_path)
    seam = LlmSeam(role="D", session_root=ws, gateway=_Gate([
        _native_final(final="结论文本", evidence=["e-1"], notify=NOTIFY)]))
    face = LL.build_tool_face("D", reg)
    data, call = seam.ask_step("t", face=face)
    assert call.ok and call.protocol == "tool_calls", call.to_dict()
    assert data["final"] == "结论文本" and data["evidence"] == ["e-1"], data
    assert data.get("notify") == NOTIFY, data
    # 逐字：不是"形状像"，是同一个字典（嵌套的 refs 数组也要逐字相等）
    assert json.dumps(data["notify"], ensure_ascii=False, sort_keys=True) == \
        json.dumps(NOTIFY, ensure_ascii=False, sort_keys=True)


def test_a_native_final_without_notify_does_not_invent_one(tmp_path: pathlib.Path):
    """负控（缺口 1）：不传 `notify` ⇒ 形状里没有 `notify` 这个键。

    为什么这一条必须有：最省事的"修法"是 `payload.setdefault("notify", {})` ——
    于是"模型没填"与"框架替它填了一份空表"在会话记录里长得一样
    （`agent_loop._with_notify` 的 docstring 记的是同一条纪律）。
    这里断言 `"notify" not in data`，不许补空 dict 冒充"填了"。
    """
    st, reg, ws = _registry(tmp_path)
    seam = LlmSeam(role="D", session_root=ws, gateway=_Gate([
        _native_final(final="没有这一栏", evidence=[])]))
    face = LL.build_tool_face("D", reg)
    data, _call = seam.ask_step("t", face=face)
    assert "notify" not in data, data
    assert data == {"final": "没有这一栏", "evidence": []}, data


def test_a_native_final_with_a_malformed_notify_is_carried_not_swallowed(tmp_path: pathlib.Path):
    """负控（缺口 1 的另一面）：形状不对的 `notify` 也要照带，不许在翻译层丢掉。

    理由：`notify` 的校验只有一处（`agent_loop.notify_shape_problem`），它的产物是
    读数（`result.notify_problem`）而不是拒信。翻译层若把"形状不对的都删掉"，
    模型就再也看不到"我那一栏错在哪" —— 而"没填"与"填错了"会折成同一格。
    """
    st, reg, ws = _registry(tmp_path)
    bad = {"to": "D", "body": "缺 summary"}
    seam = LlmSeam(role="D", session_root=ws, gateway=_Gate([
        _native_final(final="做完了", notify=bad)]))
    face = LL.build_tool_face("D", reg)
    data, _call = seam.ask_step("t", face=face)
    assert data.get("notify") == bad, data


# ============================================================ 缺口 2：落盘

def _run(tmp_path: pathlib.Path, replies: list[dict], *, role: str = "D",
         ) -> tuple[pathlib.Path, Any]:
    """跑一趟（脚本化替身，不联网）。返回 `(工作区, run)`。"""
    st, reg, ws = _registry(tmp_path)
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    gw = _Gate(replies)
    run = run_role(role, "把这一趟做完", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role=role, session_root=ws, gateway=gw,
                                price=(0.0, 0.0), sid=SID),
                   session_root=ws, workspace_root=str(ws), sid=SID, from_env=False)
    return ws, run


def test_the_closing_notify_and_conclusion_reach_the_ledger(tmp_path: pathlib.Path):
    """正控（缺口 2 的主判据）：`stop_reason == "final"` 的一趟跑完之后，
    盘上（`agent_run_end` 事件里）找得到模型那一步的 `notify` 与最终结论。

    改前必红（实测）：`agent_run_end` 的键集是
    `{elapsed_sec, final, final_chars, final_sha256, handoffs, kind, messages,
      notify_rejections, role, spend, steps, stop_reason, summons, ts, waiting_for}`
    —— 没有 `evidence` / `notes` / 收工那一步的载荷；盘上 `agent_step` 0 条。
    `notify` 那句话只能从"框架代发的留言"里读到，而"模型自己填了什么"读不到。

    反负控（"不是随便哪个地方出现过就算"）：命中的那一条事件必须是
    `agent_run_end`，且原文在它的 `final_payload.notify` 里 —— 不是从手稿账本或
    留言里捞出来的。
    """
    ws, run = _run(tmp_path, [{"text": json.dumps(
        {"final": "模型给的收工结论：这三条断言证据最弱", "evidence": ["exp:0007"],
         "notify": NOTIFY}, ensure_ascii=False)}])
    assert run.stop_reason == "final", run.to_dict()
    events = _events(ws)
    ends = [e for e in events if e.get("kind") == "agent_run_end"]
    assert ends, [e.get("kind") for e in events]
    end = ends[-1]
    payload = end.get("final_payload")
    assert isinstance(payload, dict), f"agent_run_end 没有收工那一步的载荷：{sorted(end)}"
    # ① notify 逐字在盘上
    assert payload.get("notify") == NOTIFY, payload
    # ② 最终结论与模型自报的证据也在盘上
    assert payload.get("final") == "模型给的收工结论：这三条断言证据最弱", payload
    assert payload.get("evidence") == ["exp:0007"], payload
    assert end.get("evidence") == ["exp:0007"], end
    assert "notes" in end, sorted(end)
    # ③ 反负控：这三样确实来自这一条事件（与内存里的 run 对得上）
    assert run.final_payload == payload, (run.final_payload, payload)


def test_the_closing_reading_is_on_disk_when_notify_is_missing(tmp_path: pathlib.Path):
    """负控（缺口 2）：模型没填 `notify` ⇒ 盘上也没有 `notify` 键，
    但"为什么没有"这句读数（`notes`）必须在盘上。

    为什么这一条与缺口 1 的负控并列：两处的"不凭空造一份"是同一件事的两端 ——
    翻译层不造空表，落盘层也不许把 `notify: null` 写上去冒充"填过了"。
    """
    ws, run = _run(tmp_path, [{"text": json.dumps(
        {"final": "没填就是没交接", "evidence": []}, ensure_ascii=False)}])
    assert run.stop_reason == "final", run.to_dict()
    end = [e for e in _events(ws) if e.get("kind") == "agent_run_end"][-1]
    payload = end.get("final_payload") or {}
    assert "notify" not in payload, payload
    assert end.get("final") == "没填就是没交接", end
    assert any("没有交接手稿" in str(n) for n in (end.get("notes") or [])), end.get("notes")
    assert not (ws / "manuscripts" / "handoffs.jsonl").is_file(), "没填就不该有手稿"


def test_the_closing_step_still_leaves_no_agent_step_event(tmp_path: pathlib.Path):
    """负控（缺口 2 的"改法边界"）：收工那一步仍然不落 `agent_step`。

    这不是"漏改"，是选择：补一条 `agent_step(shape="final")` 会让
    `resume_transcript` 重建的简报多一行（它按 `agent_step` 逐条重拼），于是
    `tests/test_user_channel_stop_and_resume.py::test_resume_messages_is_item_equal_to_the_live_sequence`
    那条"重建 == 当时那一份"的判据就守不住了。所以留痕走 `agent_run_end`。
    这一条把那个取舍钉住：谁哪天改成"顺手补一条 step 事件"，这里会红。
    """
    ws, run = _run(tmp_path, [{"text": json.dumps(
        {"final": "收工", "evidence": []}, ensure_ascii=False)}])
    steps = [e for e in _events(ws) if e.get("kind") == "agent_step"]
    assert steps == [], [e.get("shape") for e in steps]
    assert [s.shape for s in run.steps] == ["final"], run.to_dict()


# ============================================================ 缺口 3：秘书没装配

def test_a_failed_secretary_build_leaves_a_trace_and_closes_the_write_path(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """正控（缺口 3）：秘书工厂必然抛异常 ⇒ ① 盘上有留痕；② 之后的 handoff 返回 `ok is False`。

    改前必红（实测）：`run.notes == []`、盘上事件是
    `['agent_run_start', 'agent_tool_face', 'llm_call', 'agent_run_end']`
    —— 一句关于秘书的话都没有。而"没装配秘书"这件事本来是有后果的
    （`_do_handoff` 一律返回 `ok is False`），于是"写路径关闭"在盘上无痕迹。

    注入点选 `agent_loop._secretary_for`（生产装配的唯一入口）：这样注入的是
    "工厂坏了"，不是"秘书类被整体替换" —— 后者会连 `handoff_add` 一起换掉，
    这一条判据就变成在测替身。
    """
    st, reg, ws = _registry(tmp_path)
    cond = Conductor(st, policy=None, backend=LocalBackend({}))

    def boom(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("注入的秘书工厂故障")

    monkeypatch.setattr(AL, "_secretary_for", boom)
    run = run_role("D", "把这一趟做完", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="D", session_root=ws,
                                gateway=_Gate([{"text": json.dumps(
                                    {"final": "照常收工", "evidence": [],
                                     "notify": NOTIFY}, ensure_ascii=False)}]),
                                price=(0.0, 0.0), sid=SID),
                   session_root=ws, workspace_root=str(ws), sid=SID, from_env=False)

    # ① 盘上有留痕（事件），理由是注入的那一句原文（三态：名字与原文都照抄）
    notes = [e for e in _events(ws) if e.get("kind") == "agent_note"]
    assert notes, [e.get("kind") for e in _events(ws)]
    assert any("秘书装配失败" in str(n.get("note") or "") for n in notes), notes
    assert any("RuntimeError" in str(n.get("note") or "") for n in notes), notes
    # ② 这一事实也能从返回值读到（两条路都要有：只看其中一处会以为"秘书没问题"）
    assert any("秘书装配失败" in str(x) for x in run.notes), run.notes
    # ③ 写路径确实关着：没装配秘书 ⇒ handoff 不许静默成功
    res = run.steps[0].result.get("notify_handoff") or {}
    assert res.get("ok") is False, (res, run.steps[0].to_dict())
    assert not (ws / "manuscripts" / "handoffs.jsonl").is_file(), "没装配秘书却写出了手稿"
    # ④ 这一趟本身照跑（fail-open 的姿态没被改掉）
    assert run.stop_reason == "final", run.to_dict()


def test_a_healthy_secretary_is_still_assembled_and_writes_the_handoff(tmp_path: pathlib.Path):
    """反负控（缺口 3）：不注入故障时秘书照旧装配、手稿照旧落行。

    没有这一条，上面那条判据在"秘书路径整体坏掉"的世界里也会绿 ——
    它证明的会是"什么都没写"而不是"坏掉时留了痕"。
    """
    ws, run = _run(tmp_path, [{"text": json.dumps(
        {"final": "照常收工", "evidence": [], "notify": NOTIFY}, ensure_ascii=False)}])
    assert run.handoffs == ["0000"], run.to_dict()
    hp = ws / "manuscripts" / "handoffs.jsonl"
    assert hp.is_file(), "装配正常时手稿必须落行"
    assert len(hp.read_text(encoding="utf-8").splitlines()) == 1
    assert not [e for e in _events(ws)
                if e.get("kind") == "agent_note" and "秘书装配失败" in str(e.get("note"))]

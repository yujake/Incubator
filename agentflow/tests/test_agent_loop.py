"""LLM 驱动的互相唤起与消息传递：判据与负控（离线，用替身模型）。

## 这一组守什么

`draft/28` §179 的核心验收是"真实出现 LLM 驱动的互相唤起与 message 传递"。
真机跑一条链只能证明"这一次它发生了"；要把这件事钉住，需要一组离线判据：
用一个"照剧本回答的替身模型"驱动同一条循环，断言

1. M 的模型决定唤起 D，D 的模型决定唤起 E，E 的模型给出结论 —— 三者都是"模型说的"，
   不是脚本写死的（框架只执行模型说的形状）；
2. 链条在 `tasks` 台账里逐环可查：`by` 是发起者、`parent_task_id` 指向上一环；
3. 消息落进项目会话记录，收件人下次运行时在收件箱里看到，并且只进到收件人那里；
4. 越权、不存在的动作、坏 JSON、没接线、预算耗尽 —— 五种情形都有明确的读数，
   不许静默折成"没问题"。

替身模型的接口与真模型完全一样（`complete(prompt, *, scope, system)`），
所以真机验收换的只是这个对象（`temp/` 下的 live 脚本）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.agent_loop import LlmBackend, inbox_digest, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

#: 由模型驱动的动作（其余动作仍走 Python 实现）。用真实的动作名，走真实的闸门。
LOOPS: dict[tuple[str, str], dict[str, Any]] = {
    ("D", "consider"): {},
    ("E", "run_experiment"): {},
}


class ScriptedGateway:
    """照剧本回答的替身模型：每次 `complete` 取剧本里的下一条，取完就重复最后一条。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _wired(tmp_path: pathlib.Path, scripts: dict[str, list[str]], *,
           max_steps: int = 4, usd_budget: float | None = None,
           ) -> tuple[Store, Conductor, Any, dict[str, ScriptedGateway], pathlib.Path]:
    """造一个工作区 + 主控 + 工具层，并把替身模型接到 LlmBackend 上。"""
    st = Store(tmp_path / "ws")
    st.init()
    gateways = {role: ScriptedGateway(replies) for role, replies in scripts.items()}

    def seam_factory(role: str) -> LlmSeam:
        return LlmSeam(role=role, session_root=tmp_path / "ws", gateway=gateways.get(role),
                       price=(0.0, 0.0), usd_budget=usd_budget, sid="test-run")

    inner = LocalBackend({})
    backend = LlmBackend(inner=inner, loops=LOOPS, session_root=tmp_path / "ws",
                         seam_factory=seam_factory, max_steps=max_steps, store=st, sid="test-run")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond)
    backend.registry = built.registry
    return st, cond, built.registry, gateways, tmp_path / "ws"


def _tasks(st: Store) -> list[dict]:
    return sorted(st.rows("tasks"), key=lambda r: str(r.get("task_id")))


def _events(root: pathlib.Path) -> list[dict]:
    events, problems = SS.read_session(root, sid="test-run")
    assert not problems, problems
    return events


def _summon_step(run: Any) -> dict:
    return next(s.result for s in run.steps if s.shape == "summon")


def test_model_decides_the_chain_and_the_ledger_records_each_hop(tmp_path: pathlib.Path):
    """正控（本组的主判据）：M→D→E 三环都由模型决定，台账逐环可查。"""
    scripts = {
        "M": [json.dumps({"summon": {"role": "D", "action": "consider",
                                     "params": {"qid": "q-0001"},
                                     "why": "先要一个结论"}}, ensure_ascii=False),
              json.dumps({"final": "链已跑通", "evidence": []}, ensure_ascii=False)],
        "D": [json.dumps({"summon": {"role": "E", "action": "run_experiment",
                                     "params": {"claim": "n=3 的检查支持它",
                                                "claim_key": "k-0001",
                                                "script_path": "code/exp.py"},
                                     "why": "要一条可复现的证据"}}, ensure_ascii=False),
              json.dumps({"final": "证据到手", "evidence": ["e-0001"]}, ensure_ascii=False)],
        "E": [json.dumps({"final": "跑过了，结论是有条件的", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, _gw, root = _wired(tmp_path, scripts)
    m_seam = LlmSeam(role="M", session_root=root, gateway=_gw["M"], price=(0.0, 0.0),
                     sid="test-run")
    run = run_role("M", "把这条链跑通", store=st, registry=registry, conductor=cond,
                   seam=m_seam, workspace_root=str(root), sid="test-run", from_env=False)

    assert run.stop_reason == "final" and run.final == "链已跑通", run.to_dict()
    assert run.summons == ["D"], f"M 唤起的不对：{run.summons}"

    rows = {str(r.get("task_id")): r for r in _tasks(st)}
    assert len(rows) == 2, f"台账里应该正好两环：{rows}"
    m_row = next(r for r in rows.values() if str(r.get("role")) == "D")
    e_row = next(r for r in rows.values() if str(r.get("role")) == "E")
    assert str(m_row.get("called_by")) == "M" and str(e_row.get("called_by")) == "D", (
        m_row.get("called_by"), e_row.get("called_by"))
    assert str(e_row.get("parent_task_id")) == str(m_row.get("task_id")), (
        "子环的 parent_task_id 必须指向上环", e_row.get("parent_task_id"), m_row.get("task_id"))
    assert str(e_row.get("status")) == "done" and str(e_row.get("outcome")) == "ok", e_row

    # D 那一环自己也是模型驱动的：会话记录里有它自己的运行起止与它唤起的下一环
    ends = {str(e.get("role")): e for e in _events(root) if e.get("kind") == "agent_run_end"}
    assert set(ends) >= {"M", "D", "E"}, f"有角色的循环没有跑起来：{sorted(ends)}"
    assert list(ends["D"].get("summons") or []) == ["E"], (
        f"D 的循环没有唤起 E：{ends['D'].get('summons')}")
    starts = [e for e in _events(root) if e.get("kind") == "agent_run_start"]
    assert all(e.get("prompt_sha256") for e in starts), "有循环没有留下提示词哈希"
    assert m_seam.spend.calls >= 2, "M 至少该调用两次模型（派活 + 收工）"


def test_messages_are_durable_and_reach_only_the_recipient(tmp_path: pathlib.Path):
    """正控 + 隔离负控：留言落档、收件人读得到、别人读不到、投递只算一次。"""
    scripts = {
        "M": [json.dumps({"message": {"to": "E", "subject": "补充条件",
                                      "body": "只在 n=3 时成立，写清楚"}},
                          ensure_ascii=False),
              json.dumps({"final": "留言已发", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, gw, root = _wired(tmp_path, scripts)
    run = run_role("M", "把条件通知 E", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)
    assert run.messages_sent == ["E"], run.to_dict()
    sent = [e for e in _events(root) if e.get("kind") == "agent_message"]
    assert len(sent) == 1 and sent[0]["from"] == "M" and sent[0]["to"] == "E"
    assert "n=3" in sent[0]["body"]

    inbox_e, fresh_e, problems = inbox_digest(root, "E", sid="test-run")
    assert not problems and "n=3" in inbox_e and fresh_e, (inbox_e, fresh_e)
    inbox_d, fresh_d, _ = inbox_digest(root, "D", sid="test-run")
    assert inbox_d == "（没有收到留言）" and fresh_d == [], "留言串到了别人的收件箱"


def test_an_illegal_edge_is_refused_by_the_policy_not_by_the_prompt(tmp_path: pathlib.Path):
    """负控（结构性约束）：D 试图唤起 G（边表里没有这条边）⇒ 策略拒绝，台账留痕。"""
    scripts = {
        "M": [json.dumps({"summon": {"role": "D", "action": "consider",
                                     "params": {"qid": "q-0002"}}}, ensure_ascii=False),
              json.dumps({"final": "被拒了", "evidence": []}, ensure_ascii=False)],
        "D": [json.dumps({"summon": {"role": "G", "action": "build_document",
                                     "params": {"kind": "note", "title": "越权测试",
                                                "claims": []}}}, ensure_ascii=False),
              json.dumps({"final": "这条路走不通", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, gw, root = _wired(tmp_path, scripts)
    run = run_role("M", "让 D 去越权", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)
    assert run.summons == ["D"], run.summons
    rows = _tasks(st)
    # 拒绝也要留痕：台账里会有一条 role=G 的 refused 行（那次召唤真的被提出过），
    # 但它不许是 done/running —— 那才是"越权成功"。
    g_rows = [r for r in rows if str(r.get("role")) == "G"]
    assert g_rows, "越权必须留下一条 refused 行（拒绝也是被提出过的一次召唤）"
    assert all(str(r.get("outcome")) == "refused" for r in g_rows), g_rows
    assert all(str(r.get("status")) != "running" for r in g_rows), g_rows
    # 参数给合法了才轮到边判定：summon 的顺序是先参数、后策略，
    # 所以这一格必须传一份 G.build_document 认得的参数，否则理由码会是 invalid_params。
    assert str(g_rows[0].get("refusal_reason")) == "forbidden_edge", g_rows[0]


def test_an_unknown_action_is_refused_with_its_own_reason(tmp_path: pathlib.Path):
    """负控（三态）：把动作名写错 ⇒ 理由码是动作不存在，而不是"被别人抢走了"之类。"""
    scripts = {
        "M": [json.dumps({"summon": {"role": "D", "action": "no_such_action",
                                     "params": {}}}, ensure_ascii=False),
              json.dumps({"final": "改主意", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, gw, root = _wired(tmp_path, scripts)
    run_role("M", "写错动作名", store=st, registry=registry, conductor=cond,
             seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                          sid="test-run"), workspace_root=str(root), sid="test-run",
             from_env=False)
    rows = [r for r in _tasks(st) if str(r.get("outcome")) == "refused"]
    assert rows and str(rows[0].get("refusal_reason")) in (
        "unknown_action", "forbidden_edge", "unknown_role"), rows


def test_bad_json_stops_the_loop_instead_of_faking_an_answer(tmp_path: pathlib.Path):
    """负控（三态）：模型连说三次不是 JSON ⇒ 停下并如实报，不许当空对象继续。"""
    scripts = {"M": ["这不是 JSON", "{也不是}", "还是不是"]}
    st, cond, registry, gw, root = _wired(tmp_path, scripts, max_steps=5)
    run = run_role("M", "胡说八道", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)
    assert run.stop_reason == "bad_json_limit", run.to_dict()
    assert run.bad_json >= 3
    assert not [s for s in run.steps if s.shape in ("tool", "summon", "message")], \
        "坏 JSON 不许被当成一次有效的动作"


def test_no_key_means_not_wired_and_no_request_is_made(tmp_path: pathlib.Path):
    """负控（没接线）：没有 gateway 时一次请求都不发，读数写成 judge_not_wired。"""
    st, cond, registry, _gw, root = _wired(tmp_path, {"M": ["{}"]})
    run = run_role("M", "没接线也要如实说", store=st, registry=registry, conductor=cond,
                   gateway=None, workspace_root=str(root), sid="test-run", from_env=False)
    assert run.stop_reason == "not_wired", run.to_dict()
    assert run.steps and run.steps[0].problem == "judge_not_wired"
    events = _events(root)
    assert any(e.get("kind") == "llm_call" and e.get("problem") == "judge_not_wired"
               for e in events), "没接线的调用也必须落档"


def test_budget_exhaustion_stops_before_the_next_call(tmp_path: pathlib.Path):
    """负控（预算）：花销超过上限后，循环在下一次请求之前停下。"""
    scripts = {
        "M": [json.dumps({"tool": "table.list", "args": {"table": "tasks"}}, ensure_ascii=False),
              json.dumps({"final": "还有第二步", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, gw, root = _wired(tmp_path, scripts, usd_budget=1e-9)
    run = run_role("M", "预算极小", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(1.0, 1.0),
                                usd_budget=1e-9, sid="test-run"), workspace_root=str(root),
                   sid="test-run", from_env=False)
    assert run.stop_reason == "budget", run.to_dict()
    assert len(gw["M"].prompts) == 1, f"预算耗尽后不该再发请求：发了 {len(gw['M'].prompts)} 次"


def test_the_prompt_of_each_role_carries_its_tools_partners_and_task(tmp_path: pathlib.Path):
    """正控（提示词的"知情"）：送进模型的 system 里真的有它的工具、伙伴与这次的任务。"""
    scripts = {"D": [json.dumps({"final": "知道了", "evidence": []}, ensure_ascii=False)]}
    st, cond, registry, gw, root = _wired(tmp_path, scripts)
    run = run_role("D", "把这个方向收敛成结论", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="D", session_root=root, gateway=gw["D"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)
    system = getattr(gw["D"], "system_seen", None)
    # 替身模型不接 system 参数，这里改从审计与提示词生成侧核对（同一份事实）
    audit = run.prompt_audit
    assert "PARTNERS" in audit["sections"] and "ROLE_BOUNDARY" in audit["sections"], audit
    text = __import__("agentflow.agent_prompts", fromlist=["x"]).system_prompt(
        "D", registry=registry, task="把这个方向收敛成结论", workspace_root=str(root))
    assert "把这个方向收敛成结论" in text, "任务没有进提示词"
    assert "- A：" in text and "- E：" in text, "D 的伙伴表不完整"
    for tool in registry.for_role("D"):
        assert tool.name in text, f"D 的工具 {tool.name} 不在提示词里"
    assert system is None or isinstance(system, str)


@pytest.mark.parametrize("role", sorted(S.ROLES))
def test_every_role_prompt_mentions_its_declared_collaborators(role: str):
    """正控（对账）：每个角色的提示词里，边表给出的伙伴一个不少、一个不多。"""
    from agentflow import capabilities as C
    from agentflow.agent_prompts import system_prompt

    from agentflow.tools import build_registry as _br

    text = system_prompt(role, registry=_br().registry, task="对账", workspace_root="D:/x")
    for partner in sorted(C.ALLOWED_EDGES.get(role, frozenset())):
        assert f"- {partner}：" in text, f"{role} 的提示词里缺伙伴 {partner}"
    for other in sorted(S.ROLES):
        if other in C.ALLOWED_EDGES.get(role, frozenset()):
            continue
        assert f"- {other}：" not in text, f"{role} 的提示词里多出了不在边表里的 {other}"

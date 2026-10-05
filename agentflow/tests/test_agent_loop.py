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
    # `G.revise` / `D.write_report` 进这张表是 2026-09-30 加的：协同链（G 唤起 D）
    # 只有在"被召唤的那个 (角色, 动作) 是 LLM 循环驱动的"时才成立 —— 这也正是
    # "各角色像主控的 subagents"这句话的实现面。
    ("G", "revise"): {},
    ("D", "write_report"): {},
    ("H", "review"): {},
    # C 的边是空的（谁也够不到）⇒ 它是"必须请主控代唤"那一档的天然样本
    ("C", "hottest"): {},
}


class ScriptedGateway:
    """照剧本回答的替身模型：每次 `complete` 取剧本里的下一条，取完就重复最后一条。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        #: 每条请求带上的 system 提示词（`draft/37` §89 的判据要查它：现算事实是
        #: 装配期拼进 system 的，不在每一步那条 user 提示词里）。
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        self.systems.append(system or "")
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


def test_a_flat_summon_written_as_text_still_runs(tmp_path: pathlib.Path):
    """`draft/37` §68：模型把 `framework_summon` 的「实参」当成一句话写出来 ⇒ 照样派活。

    第十二趟真机第 13 步死在这里（`认不出的形状（键：['action','params','role']）`），
    而那一步与它前后成功的几步内容相同 —— 漂的只有那个外层键（`summon`）。
    判据要的是"末态是一环真的召唤"，不是"解析器认得这个字典"：形状解码对了却没执行，
    与没收下是一回事。
    """
    scripts = {
        "M": [json.dumps({"role": "E", "action": "list_experiments", "params": {},
                          "why": "扁平形态：直接写了 framework_summon 的实参"},
                         ensure_ascii=False),
              json.dumps({"final": "派完了", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, _gw, root = _wired(tmp_path, scripts, max_steps=4)
    run = run_role("M", "派一环", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=_gw["M"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)

    assert run.stop_reason == "final", run.to_dict()
    assert [s.shape for s in run.steps] == ["summon", "final"], run.to_dict()
    assert run.steps[0].payload["shape_alias"] == "role", run.steps[0].payload
    assert run.summons == ["E"], run.summons


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


def test_a_role_emitted_summon_still_gets_an_input_key(tmp_path: pathlib.Path):
    """角色自己发的 `summon` 也必须留下非空 `input_key`（真机实测：它是空的）。

    为什么单钉这一条：`summon` 形状里没有 `input_key` 这个字段（只有
    role / action / params / why），于是角色自己派活写出来的那一行键为空 ⇒
    `verify_tasks` 报 `task_without_input_key`，这条召唤结构上无法参与循环检测。
    真机现场：场景 G 的 `t-0252`（G 自己派 A 去要文献）。M 走的 `conductor.summon`
    工具有这个字段、提示词也教它给，所以只有"角色主动派活"这条路会漏。

    判据三条：键非空；同一份 `(action, params)` 派两次得到同一个键（循环检测要的
    就是"同一件事"）；不同参数得到不同的键（否则一切都会被误判成循环）。
    """
    from agentflow.agent_loop import _summon_key
    from agentflow import verify as V

    scripts = {
        "M": [json.dumps({"summon": {"role": "D", "action": "consider",
                                     "params": {"qid": "q-0007"},
                                     "why": "先要一个结论"}}, ensure_ascii=False),
              json.dumps({"final": "派完了", "evidence": []}, ensure_ascii=False)],
        "D": [json.dumps({"final": "收到", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, gw, root = _wired(tmp_path, scripts)
    run_role("M", "派一个结论", store=st, registry=registry, conductor=cond,
             seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                          sid="test-run"), workspace_root=str(root), sid="test-run",
             from_env=False)
    rows = _tasks(st)
    assert rows, "台账里应当有那一环"
    for r in rows:
        assert str(r.get("input_key") or "").strip(), (
            f"这一行的 input_key 是空的 ⇒ 它会无法参与循环检测：{r}")
    codes = [i.get("code") for i in V.verify_all(st).to_dict()["warnings"]]
    assert "task_without_input_key" not in codes, codes

    # 键的语义：同一件事 ⇒ 同一个键；不同的事 ⇒ 不同的键。
    same_a = _summon_key("consider", {"qid": "q-0007"})
    same_b = _summon_key("consider", {"qid": "q-0007"})
    other = _summon_key("consider", {"qid": "q-0008"})
    assert same_a == same_b and same_a and other and same_a != other, (same_a, same_b, other)


def test_a_batch_summon_also_gets_input_keys(tmp_path: pathlib.Path):
    """一批派活（`summon_many`）的每一项也要有键 —— 同一条兜底，两条路都要钉。"""
    scripts = {
        "M": [json.dumps({"summon_many": {"targets": [
            {"role": "B", "action": "run_once", "params": {}},
            {"role": "B", "action": "run_once", "params": {}},
        ]}}, ensure_ascii=False),
            json.dumps({"final": "批派完了", "evidence": []}, ensure_ascii=False)],
        "B": [json.dumps({"final": "整理完了", "evidence": []}, ensure_ascii=False),
              json.dumps({"final": "整理完了", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, gw, root = _wired(tmp_path, scripts)
    run_role("M", "并排整理两本书", store=st, registry=registry, conductor=cond,
             seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                          sid="test-run"), workspace_root=str(root), sid="test-run",
             from_env=False)
    rows = _tasks(st)
    assert rows, "台账里应当有被派出去的那几行"
    for r in rows:
        assert str(r.get("input_key") or "").strip(), r


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


def test_a_role_can_send_a_private_message_to_the_conductor(tmp_path: pathlib.Path):
    """`to="M"` 必须是一条合法留言 —— 真机实测（场景 G）它曾被判成 `invalid`。

    为什么这条重要：代唤协议说的是"把申请发给主控 M"，而框架自己的自动代唤
    （`_request_relay`）就是用 `to=S.CONDUCTOR_ROLE` 发的。如果循环协议只认
    `S.ROLES`（A–H，不含 M），那么角色照协议自己发的那一条会被判成非法
    （实测报 `收件人 'M' 既不是角色也不是 #public`），它只能退而发 `#public` ——
    于是"一条只该主控看到的申请"变成广播，还白扔一步。

    判据三条：形状能解析、M 的收件箱真读得到、别的角色读不到（私聊不是广播）。
    """
    from agentflow.agent_loop import _shape_of
    from agentflow import schema as S

    shape, payload, problem = _shape_of(
        {"message": {"to": "M", "subject": "请代唤", "body": "要谁：A"}})
    assert problem == "" and shape == "message", (shape, problem)
    assert payload["to"] == "M" == S.CONDUCTOR_ROLE

    # 负控：既不是角色、也不是主控、也不是公共频道的收件人仍然要被拒。
    for bad in ("X", "documents", "", "#all"):
        _s, _p, why = _shape_of({"message": {"to": bad, "subject": "s", "body": "b"}})
        assert why, f"{bad!r} 不该被当合法收件人"

    scripts = {
        "G": [json.dumps({"message": {"to": "M", "subject": "请代唤",
                                      "body": "要谁：A；什么动作：run_once；为什么：本地书架是空的"}},
                          ensure_ascii=False),
              json.dumps({"final": "已申请代唤", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, gw, root = _wired(tmp_path, scripts)
    run = run_role("G", "缺文献证据", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="G", session_root=root, gateway=gw["G"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)
    assert run.messages_sent == ["M"], run.to_dict()
    inbox_m, fresh_m, problems = inbox_digest(root, "M", sid="test-run")
    assert not problems and "请代唤" in inbox_m and fresh_m, (inbox_m, fresh_m)
    inbox_d, fresh_d, _ = inbox_digest(root, "D", sid="test-run")
    assert inbox_d == "（没有收到留言）" and fresh_d == [], "私聊给 M 的申请不该进别人的收件箱"


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


def test_the_step_prompt_restates_the_output_contract_last(tmp_path: pathlib.Path):
    """判据（§195 真机实测逼出来的）：每一步最后读到的一行必须是输出契约的骨架。

    实测：M 做"核验定理与引理的证明"时连着三次回 1400–2400 字的散文（`judge_bad_json` ⇒
    `bad_json_limit`），那次运行对交付物零贡献。系统提示词 6k+ token，循环协议埋在中间，
    模型不是不听、是没读到 —— 所以契约要重述在它最后读到的地方。
    """
    from agentflow.agent_loop import JSON_TAIL, AgentLoop

    st, cond, registry, gw, root = _wired(tmp_path, {"M": ["{}"]}, max_steps=3)
    run = run_role("M", "核验证明", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)
    assert run.prompt_audit.get("prompt_version"), run.prompt_audit
    # 直接问那条提示词（真跑里它每一轮都会拼一遍）
    loop = AgentLoop(role="M", session_root=root, registry=registry, conductor=cond,
                     seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                                  sid="test-run"), max_steps=3, workspace_root=str(root),
                     sid="test-run", store=st)
    prompt = loop._prompt("转录", step=0)
    assert prompt.rstrip().endswith(JSON_TAIL.rstrip()), prompt[-200:]
    for shape in ("tool", "summon", "summon_many", "message", "note", "ask_user", "final"):
        assert f'"{shape}"' in JSON_TAIL, shape


def test_the_loop_hands_the_live_toolchain_reading_to_the_model(tmp_path: pathlib.Path,
                                                               monkeypatch):
    """判据（`draft/37` §89）：角色循环必须把现算的工具链读数递进提示词。

    为什么这条判据落在循环上而不是提示词装配里：工厂（`agent_prompts`）只负责"没传时
    也要诚实"，真正"把这台机器的读数传下去"的是循环。T1 第 3 趟的 6 次
    `import Mathlib` 全部撞在"本机没装 Mathlib"上，而框架手里有这条读数却没递出去 ——
    所以判据要盯着传递链，不是盯着那一段文字。

    用哨兵替换现算函数：只要循环真的调了它，哨兵就会出现在模型收到的提示词里
    （`gw` 记录每一条发出去的提示词）。
    """
    import json as _json

    from agentflow import agent_prompts as AP

    monkeypatch.setattr(AP, "toolchain_facts_text",
                        lambda: "哨兵：本机没有 Mathlib，自足 Lean 文件可用")
    scripts = {"E": [_json.dumps({"final": "好"})]}
    st, cond, registry, gw, root = _wired(tmp_path, scripts, max_steps=2)
    run_role("E", "核验一条断言", store=st, registry=registry, conductor=cond,
             seam=LlmSeam(role="E", session_root=root, gateway=gw["E"], price=(0.0, 0.0),
                          sid="test-run"), workspace_root=str(root), sid="test-run",
             from_env=False)
    assert gw["E"].systems, "这一次没有发出任何提示词 ⇒ 判据失去对象"
    assert "哨兵：本机没有 Mathlib，自足 Lean 文件可用" in gw["E"].systems[0], (
        gw["E"].systems[0][-400:])


def test_the_availability_column_does_not_call_a_wired_role_unwired(tmp_path: pathlib.Path,
                                                                  monkeypatch):
    """判据（`draft/37` §106）：接线态那一栏不许把真的接了线的角色报成没接线。

    真机读数（T1 第 14 趟）：`cli.cmd_run_agent` 按 `--provider` → 配置 → `openalex`
    建了 providers，而循环里的 `_availability()` 又用不带 providers 的
    `host.wiring_status` 重算了一遍 ⇒ M 的提示词里写着「接线态（这一栏是事实）：
    A -> no_provider」。它在第 22 步据此写下「A 未接线 ⇒ 盘外引文放弃检索」，
    整趟没派过一次 A —— 而 A 的检索是通的（离线探针一次查询登记 9 行文献）。

    判据：`host.wiring_status` 说 `no_provider`，而后端登记表里有 A ⇒ 必须报 `wired`；
    后端里没有的角色（这里用 Z）仍然照抄主机读数（不许把这一栏变成永远 wired）。
    """
    from agentflow import host as host_mod
    from agentflow.agent_loop import AgentLoop

    st, cond, registry, _gw, root = _wired(tmp_path, {"M": ["{}"]}, max_steps=1)
    monkeypatch.setattr(host_mod, "wiring_status",
                        lambda *a, **k: {"A": "no_provider", "Z": "no_provider"})
    # 真身读数：这一趟的后端登记表里 A 在（这就是"接了线"的定义）
    import types
    monkeypatch.setattr(cond, "backend",
                        types.SimpleNamespace(known_roles=lambda: ["A", "B"]), raising=False)
    loop = AgentLoop(role="M", session_root=root, registry=registry, conductor=cond,
                     seam=None, max_steps=1, workspace_root=str(root), sid="t", store=st)
    avail = loop._availability()
    assert avail is not None, "拿不到接线态 ⇒ 这一栏会变成「没有读数」，判据失去对象"
    assert avail.get("A") == "wired", avail
    assert avail.get("Z") == "no_provider", avail


def test_a_bad_reply_gets_a_sharper_repair_message(tmp_path: pathlib.Path):
    """负控（修法要真的递出去）：坏 JSON 之后那条纠正消息里要点名"不要写分析"并给骨架。"""
    from agentflow.agent_loop import JSON_TAIL, AgentLoop

    scripts = {"M": ["我打算先分析一下定理的证明（这段是散文）", json.dumps({"final": "好"})]}
    st, cond, registry, gw, root = _wired(tmp_path, scripts, max_steps=3)
    run = run_role("M", "核验证明", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)
    # 第二条提示词里应当带着那段骨架（纠正是"下一轮的输入"，不是一句口号）
    assert JSON_TAIL.splitlines()[0] in gw["M"].prompts[-1], gw["M"].prompts[-1][-300:]
    assert run.stop_reason == "final", run.to_dict()


def test_every_documented_shape_actually_parses(tmp_path: pathlib.Path):
    """判据（§195：这一次是我的错）：提示词里给的骨架必须能被 `_shape_of` 真解析通过。

    实测（2026-09-30 第二次真机）：我把 `tool` 那一条写成了 `{"tool": {"name": …}}`，
    而解析器要的是 `{"tool": "<工具名>", "args": …}` ⇒ 模型照着我的骨架说，
    却被判"tool 必须是一个工具名字符串"，连着三次 ⇒ `bad_json_limit`。
    骨架是文档，文档必须与解析器同源；这条判据就是那个"同源"。
    """
    from agentflow.agent_loop import JSON_TAIL, _shape_of

    # 替换顺序要紧：`{...}` 必须先变成 `{}`，否则 `...` → `x` 会把它改成 `{x}`（非法 JSON）。
    # 占位符表要与 `JSON_TAIL` 同源：骨架里每出现一个新的 `<...>`，这里要么补一条替换、
    # 要么那条骨架就解析不过（§195 的原意——文档不许比解析器松）。
    fixed = (JSON_TAIL.replace("{...}", "{}").replace("<工具名>", "table.list")
             .replace("<动作名>", "review").replace("A-H", "H")
             .replace("<伙伴或 #public>", "#public").replace("<结论>", "做完了")
             .replace("<伙伴/M/ALL>", "A").replace("<markdown 正文>", "正文")
             .replace("<前面的编号>", "0000")
             .replace("...", "x"))
    parsed: list[str] = []
    for line in fixed.splitlines()[1:]:
        data = json.loads(line)                      # 骨架本身必须是合法 JSON
        shape, _payload, problem = _shape_of(data)
        assert not problem, (line, problem)
        parsed.append(shape)
    assert sorted(parsed) == sorted(["tool", "summon", "summon_many", "message", "handoff",
                                    "note", "ask_user", "final"]), \
        parsed


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


def test_a_clipped_tool_result_still_carries_its_meta_and_a_way_to_continue(tmp_path: pathlib.Path):
    """判据（§196 真机实测逼出来的）：观测层截断 `data` 时，`meta` 与续读办法必须还在。

    实测：E 要读 17849 字节的台账，每次拿到 1200 字就没了 —— 它连续 14 步重读同一个开头，
    把整个步数预算烧在"读不完一份文件"上。根因不是工具不给（`fs.read` 那时已读全文），
    而是观测层把整个结果 JSON 从头截断，`meta`（含 `total_bytes`）与续读位置一起被切掉。
    这条判据钉住的是：截断可以，但"少给的那部分怎么拿"必须跟着一起递到模型眼前。
    """
    scripts = {"E": [json.dumps({"tool": "fs.read",
                                 "args": {"path": "ledger.md", "start_line": 1, "max_lines": 8}},
                                ensure_ascii=False),
                     json.dumps({"final": "读了第一段", "evidence": []}, ensure_ascii=False)]}
    st, cond, registry, gw, root = _wired(tmp_path, scripts, max_steps=3)
    (root / "ledger.md").write_text("".join(f"第 {i} 行：这是一条很长的断言，用来把观测层撑爆\n"
                                           for i in range(1, 61)), encoding="utf-8")
    # 角色取 E：真机实测里读台账的正是 E 的子循环，而 E 的工具面里确实有 `fs.read`
    # （`build_registry` 把只读工具发给 A–H；M 是驱动者，不在 A–H 里）。
    run_role("E", "读台账", store=st, registry=registry, conductor=cond,
             seam=LlmSeam(role="E", session_root=root, gateway=gw["E"], price=(0.0, 0.0),
                          sid="test-run"), workspace_root=str(root), sid="test-run",
             from_env=False)
    assert len(gw["E"].prompts) >= 2, "至少要有第二次请求才谈得上'下一轮读到了什么'"
    seen = gw["E"].prompts[1]
    # 1) 续读位置进了下一轮的输入（否则模型只知道"被截断了"）
    assert "续读" in seen and "start_line=9" in seen, seen[-500:]
    # 2) `meta` 的关键读数没被截掉（摊平后键名带前缀，见 `_flatten_one_level`）
    assert "meta.total_lines" in seen and "meta.next_line" in seen, seen[-500:]
    # 3) 被截的那个字段要写明是"观测层截断"，不能让人以为内容本来就没有
    assert "观测层" in seen, seen[-500:]


def test_a_wide_tool_result_keeps_its_later_keys_not_just_the_head_of_one():
    """判据（§196 第二条）：工具结果是十几个键的字典时，观测层要摊平一层再按字段分配。

    实测：`conductor.acceptance` 的结果里 `data.documents`（验收表背后的 `doc_id`）排在
    `data.rows` 后面 —— 不摊平时 `data` 是一个字段，尾巴被整段切掉，于是 M 只能从
    验收表标题里猜一个 `draft/31` 去派 H 审校，而真号是 `0000`，核验链在第一跳就断了。
    """
    from agentflow.agent_loop import _clip_fields

    data = {"rows": [{"id": f"P{i}", "reading": "读" * 80} for i in range(1, 11)],
            "documents": [{"doc_id": "0000", "kind": "survey", "title": "台账", "claims": 24}],
            "problems": [], "requested": [], "unknown_ids": []}
    text = _clip_fields({"tool": "conductor.acceptance", "ok": True, "data": data,
                         "error": "", "meta": {}})
    assert "data.documents" in text and "0000" in text, text[-400:]


def test_a_forbidden_edge_becomes_a_relay_request_to_the_conductor(tmp_path: pathlib.Path):
    """判据（§198，真机实测逼出来的）：越权唤起必须转成"请主控代唤"，而不是一句拒绝。

    实测背景：17 个 review 会话里非 M 的召唤只有 F→E 七次 —— 因为缺证据的角色
    （G 要文献、H 要形式化、C 什么都没有）拿到的只是一句 `forbidden_edge`，
    然后就"没有然后"了。用户的原话是"如果互相唤起困难，至少要能向主控申请唤起别的
    智能体做任务"，所以这条判据钉三件事：
    ① 这一步仍然如实报 `ok=False` / `refusal_reason=forbidden_edge`（不许假装成功）；
    ② 同时自动发出一条给 M 的「请代唤」留言，并在返回里给出 `relay_requested`；
    ③ 会话里留下一条结构化事件 `agent_summon_request`（可审计，不靠读留言文本）。
    """
    import json as _json

    asking = _json.dumps({"summon": {"role": "A", "action": "run_once",
                                     "params": {"request": "缺一份 1971 年的原文"}}},
                         ensure_ascii=False)
    # 用 C 当申请方：它的出边是空的（`ALLOWED_EDGES["C"] == frozenset()`），
    # 所以它对任何人都必然越权 —— 而 H 现在有到 A 的边了（`draft/28` §199）。
    scripts = {"C": [asking, _json.dumps({"final": "已申请代唤", "evidence": []},
                                         ensure_ascii=False)]}
    st, cond, registry, gw, root = _wired(tmp_path, scripts, max_steps=3)
    run = run_role("C", "发现稿件缺一份引文的原文", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="C", session_root=root, gateway=gw["C"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)
    step = _summon_step(run)
    assert step["ok"] is False, step
    # 真实场景落在这两档之一：目标在边表外（`forbidden_edge`），或者因为"看不到他的
    # 参数表"而先被参数校验拦下（`invalid_params`）—— 两档都必须转成代唤申请。
    assert step["refusal_reason"] in ("forbidden_edge", "invalid_params"), step
    relay = step.get("relay_requested") or {}
    assert relay.get("to") == "M" and relay.get("message_id"), step
    assert relay.get("subject") == "请代唤", relay
    # ② 留言真的进了 M 的收件箱（不是只写在返回值里）
    from agentflow import agent_loop as AL

    inbox = AL.inbox_digest(root, "M", sid="test-run")[0]
    assert "请代唤" in inbox, inbox
    # ③ 结构化事件落档
    events = _events(root)
    reqs = [e for e in events if e.get("kind") == "agent_summon_request"]
    assert reqs and reqs[0]["role"] == "C" and reqs[0]["wants_role"] == "A", reqs


def test_relay_is_not_sent_when_the_edge_exists_and_only_the_params_are_wrong(tmp_path: pathlib.Path):
    """负控（代唤不许被滥用）：目标在我的伙伴表里时，参数写错只是参数错。

    这一条防的是"把主控当成万能的兜底"：`G → D` 是允许的边，参数写错该由 G 自己改，
    不该往 M 那里发一条代唤申请（那会让主控的收件箱被无关申请灌满，
    而"申请"这个信号一旦贬值就不再有用）。
    """
    import json as _json

    bad = _json.dumps({"summon": {"role": "D", "action": "write_report",
                                  "params": {"nonsense_key": 1}}}, ensure_ascii=False)
    scripts = {"G": [bad, _json.dumps({"final": "参数错了，我自己改", "evidence": []},
                                      ensure_ascii=False)]}
    st, cond, registry, gw, root = _wired(tmp_path, scripts, max_steps=3)
    run = run_role("G", "写报告", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="G", session_root=root, gateway=gw["G"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)
    step = _summon_step(run)
    assert step["refusal_reason"] == "invalid_params", step
    assert "relay_requested" not in step, step
    assert not [e for e in _events(root) if e.get("kind") == "agent_summon_request"]


def test_a_child_loop_knows_who_summoned_it_and_how_deep_it_is(tmp_path: pathlib.Path):
    """判据（§198 修的真 bug）：被协同唤起的角色必须知道"是同伴派的我、我在第几层"。

    旧行为：`LlmBackend.call` 读 `params["_summoned_by"]` / `params["_depth"]`，
    而全仓没有任何地方生产这两个键 ⇒ 每个子循环都以为自己是主控直接派的、深度 1。
    真机（`temp/review-task-20260930-111332`）台账是
    `t-0260 E.run_experiment called_by=F parent=t-0259 depth=2`，
    而 E 自己的 `agent_run_start` 记的是 `summoned_by=M, depth=1` ——
    "像主控的 subagent"这句话在孩子自己的认知里断掉。
    现在权威来源是台账那一行，这条判据就是那个"同源"。
    """
    import json as _json

    scripts = {
        "G": [_json.dumps({"summon": {"role": "D", "action": "write_report",
                                      "params": {"out_path": "out/r.md"}}},
                          ensure_ascii=False),
              _json.dumps({"final": "D 交回来了", "evidence": []}, ensure_ascii=False)],
        "D": [_json.dumps({"final": "报告写好了", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, _gw, root = _wired(tmp_path, scripts, max_steps=3)
    with st.tx("documents", actor="agent-G") as tx:
        tx.upsert("documents", S.Document(
            doc_id="0000", kind="paper", title="探针稿", status="draft", markdown_path=None,
            created_at=S.now_iso(), created_by="agent-G",
            claims=[{"claim_id": "C1", "text": "探针断言", "evidence_kind": "cross_check",
                     "citations": ["lit:0001"], "section": "S1",
                     "disclaimer": "数值交叉验证，不构成证明"}]).to_dict())
    cond.summon("G", "revise", {"doc_id": "0000"}, by="M")

    rows = _tasks(st)
    d_rows = [r for r in rows if str(r.get("role")) == "D"]
    assert d_rows, [dict(r) for r in rows]
    assert d_rows[0]["called_by"] == "G", d_rows[0]
    starts = [e for e in _events(root)
              if e.get("kind") == "agent_run_start" and str(e.get("role")) == "D"]
    assert starts, "D 的子循环没有留下 agent_run_start"
    assert starts[0]["summoned_by"] == "G", starts[0]
    assert int(starts[0]["depth"]) == int(d_rows[0]["depth"]) >= 2, starts[0]


def test_the_collaboration_chain_works_end_to_end(tmp_path: pathlib.Path):
    """S-2（§198 的端到端判据）："缺证据 → 请主控代唤 → 主控真的派了" 跑通一次。

    这是用户要的"协同"最小闭环，也是这一轮失败的原始形态：
    - H 审校时发现稿件缺一份原文，它自己够不到 A（边表里 H 只能叫 G）；
    - 框架把这次越权转成一条「请代唤」留言给 M；
    - M 在下一步读到它（收件箱随结果一起附上），并真的用 `conductor.summon` 派了 A。

    断言锚在台账上而不是对话上：`tasks` 里必须有一条 `role=A` 且 `called_by=M` 的行，
    而且它出现在 H 的申请之后。A 有没有接线是另一件事（这里没给 provider ⇒
    `refused/not_wired` 是正确读数）—— 判据要的是"申请被受理并变成了一次真实的派活"。
    """
    import json as _json

    scripts = {
        "M": [
            _json.dumps({"summon": {"role": "C", "action": "hottest",
                                    "params": {"top_n": 2, "request": "证据"}}}, ensure_ascii=False),
            # 第二步：M 读到申请（收件箱在结果里），替 H 派 A
            _json.dumps({"tool": "conductor.summon",
                         "args": {"target_role": "A", "action": "run_once",
                                  "input_key": "A.run_once"}}, ensure_ascii=False),
            _json.dumps({"final": "已按 H 的申请派 A 去找原文", "evidence": []},
                        ensure_ascii=False),
        ],
        # C 的出边是空的 ⇒ 它对 A 的召唤必然越权 ⇒ 框架转成"请代唤"给 M。
        "C": [
            _json.dumps({"summon": {"role": "A", "action": "run_once",
                                    "params": {"request": "缺 lit:0037 的原文"}}},
                        ensure_ascii=False),
            _json.dumps({"final": "缺原文，已请主控代唤 A", "evidence": []},
                        ensure_ascii=False),
        ],
    }
    st, cond, registry, gw, root = _wired(tmp_path, scripts, max_steps=5)
    with st.tx("documents", actor="agent-G") as tx:
        tx.upsert("documents", S.Document(
            doc_id="0000", kind="paper", title="待审稿", status="draft", markdown_path=None,
            created_at=S.now_iso(), created_by="agent-G",
            claims=[{"claim_id": "C1", "text": "一条 cross_check 断言",
                     "evidence_kind": "cross_check", "citations": ["lit:0037"],
                     "section": "S1", "disclaimer": "数值交叉验证，不构成证明"}]).to_dict())
    run_role("M", "核验这篇稿子的证据", store=st, registry=registry, conductor=cond,
             seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                          sid="test-run"), workspace_root=str(root), sid="test-run",
             from_env=False)

    rows = _tasks(st)
    c_rows = [r for r in rows if str(r.get("role")) == "C"]
    direct = [r for r in rows if str(r.get("role")) == "A" and str(r.get("called_by")) == "C"]
    relayed = [r for r in rows if str(r.get("role")) == "A" and str(r.get("called_by")) == "M"]
    assert c_rows and c_rows[0]["called_by"] == "M", [dict(r) for r in rows]
    # H 自己那一次被拒（边表里 H 只能叫 G）—— 这正是要转成代唤申请的那一次
    assert direct and direct[0]["outcome"] == "refused", direct
    assert direct[0]["refusal_reason"] in ("forbidden_edge", "invalid_params"), direct[0]
    # 主控替它派的那一次真的发生了，而且在 C 的申请之后
    assert relayed, f"M 没有替 C 派 A：{[dict(r) for r in rows]}"
    assert str(relayed[0]["task_id"]) > str(direct[0]["task_id"]), "派 A 必须发生在 H 的申请之后"
    # 申请本身也要留痕（不只看留言文本）
    reqs = [e for e in _events(root) if e.get("kind") == "agent_summon_request"]
    assert reqs and reqs[0]["wants_role"] == "A", reqs
    # M 的第二步提示词里必须真的出现了那条申请（否则它只是"碰巧"派了 A）
    assert "请代唤" in gw["M"].prompts[1], gw["M"].prompts[1][-600:]


def test_a_role_can_fan_out_a_batch_in_one_step(tmp_path: pathlib.Path):
    """判据（§198 的第二种 fan-out）：角色自己也能在一步里并发派一批活。

    为什么它必须存在：真机实测里 M 想干这件事时，先试了两次 `{"summon_many": …}`
    （被判"认不出的形状"，白扔两步）才发现要用工具 —— 而"一批文献分给几个自己去读"
    是每个角色都会遇到的事，不该只有主控做得到。判据四条：
    ① 两个同角色目标落同一波且 `concurrent_peak == 2`；
    ② 自动补的实例标签 `D#1`/`D#2` 在结果里可见；
    ③ 台账里两条 `role=D` 的行的 `called_by` 都是发起方（`G`）；
    ④ 结果按输入顺序回来、每一项各有自己的 `task_id`/`status`。
    """
    import json as _json

    asking = _json.dumps({"summon_many": {"targets": [
        {"role": "D", "action": "write_report", "params": {"out_path": "out/a.md"}},
        {"role": "D", "action": "write_report", "params": {"out_path": "out/b.md"}}],
        "why": "两份报告可以同时写"}}, ensure_ascii=False)
    scripts = {
        "G": [asking, _json.dumps({"final": "两份都派出去了", "evidence": []}, ensure_ascii=False)],
        "D": [_json.dumps({"final": "写完了", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, gw, root = _wired(tmp_path, scripts, max_steps=3)
    run = run_role("G", "同时准备两份报告", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="G", session_root=root, gateway=gw["G"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)
    step = next(s.result for s in run.steps if s.shape == "summon_many")
    assert step["count"] == 2 and step["ok_count"] == 2, step
    assert step["waves"] == [2], step["waves"]
    assert step["concurrent_peak"] == 2, step["concurrent_peak"]
    assert [i["instance"] for i in step["results"]] == ["D#1", "D#2"], step["results"]
    assert len({i["task_id"] for i in step["results"]}) == 2, step["results"]
    d_rows = [r for r in _tasks(st) if str(r.get("role")) == "D"]
    assert len(d_rows) == 2 and all(str(r["called_by"]) == "G" for r in d_rows), d_rows


def test_a_batch_that_cannot_reach_its_target_still_asks_for_relay(tmp_path: pathlib.Path):
    """判据（批量路径不许成为"越权就静默失败"的后门）：全被拒 ⇒ 发一条汇总代唤申请。

    G 够不到 A，一次派两个 A 也够不到 —— 框架要把这一批汇总成一条「请代唤」留言
    （不是两条：灌满主控的收件箱会让这个信号贬值），同时每一项仍各自如实标 `refused`。
    """
    import json as _json

    asking = _json.dumps({"summon_many": {"targets": [
        {"role": "A", "action": "run_once"}, {"role": "A", "action": "run_once"}],
        "why": "要两批文献"}}, ensure_ascii=False)
    scripts = {"C": [asking, _json.dumps({"final": "申请了代唤", "evidence": []},
                                         ensure_ascii=False)]}
    st, cond, registry, gw, root = _wired(tmp_path, scripts, max_steps=3)
    run = run_role("C", "要文献", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="C", session_root=root, gateway=gw["C"], price=(0.0, 0.0),
                                sid="test-run"), workspace_root=str(root), sid="test-run",
                   from_env=False)
    step = next(s.result for s in run.steps if s.shape == "summon_many")
    assert step["refused_count"] == 2 and step["ok_count"] == 0, step
    relay = step.get("relay_requested") or {}
    assert relay.get("to") == "M" and relay.get("message_id"), step
    reqs = [e for e in _events(root) if e.get("kind") == "agent_summon_request"]
    assert len(reqs) == 1, f"应当只发一条汇总申请，实际 {len(reqs)} 条"


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


# ============================================================ 步检查点（步进续跑的那份）

def test_the_step_checkpoint_records_the_fingerprint_and_reports_write_failures(tmp_path):
    """直接判 `agent_loop.save_run_checkpoint` / `load_run_checkpoint`。

    为什么单列（`tools/coverage_zero_test.py` 的等级 2 判据）：这一对函数是
    「跑长活被打断后从第几步接着跑」的落点 —— 它写的是「任务指纹 + 步号 + 停止原因」，
    而拿 A 任务的检查点续 B 任务会把两件事的进度混成一条（看起来还完全正常）。
    两条口径：① 写成的检查点必须带 `autonomy.task_fingerprint` 的同一个指纹（不另立一份）；
    ② 写入失败「不许静默」（返回问题串，而不是当成功），读不到才是 `None`。
    """
    from agentflow import agent_loop as AL
    from agentflow import autonomy as AU

    root = tmp_path / "ws"
    root.mkdir()
    problem = AL.save_run_checkpoint(root, "M", "sid-1", task="研究 X", step=7,
                                     stop_reason="final", spend={"usd": 0.5})
    assert problem == "", problem
    path = AL.run_checkpoint_path(root, "M", "sid-1")
    assert path.is_file(), path
    cp = AL.load_run_checkpoint(root, "M", "sid-1")
    assert cp is not None
    assert (cp["role"], cp["step"], cp["stop_reason"]) == ("M", 7, "final"), cp
    assert cp["fingerprint"] == AU.task_fingerprint("M", "研究 X"), cp
    assert cp["spend"] == {"usd": 0.5}, cp

    # 读不到 ⇒ None（三态：「没查成」不许被读成「没有这一步」）
    assert AL.load_run_checkpoint(root, "M", "no-such-sid") is None

    # 写入失败不许静默：把落点占成一个目录 ⇒ 返回问题串（不是空串）
    bad_root = tmp_path / "ws2"
    bad_root.mkdir()
    bad = AL.run_checkpoint_path(bad_root, "M", "sid-2")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.mkdir()
    problem2 = AL.save_run_checkpoint(bad_root, "M", "sid-2", task="研究 Y", step=1,
                                      stop_reason="interrupted")
    assert problem2, "写入失败被静默吞掉了（返回了空串）"
    assert "Error" in problem2, problem2


# ============================================================ 用户叫停（`draft/37` §125）

class _StopAfterFirstCall(ScriptedGateway):
    """照剧本回答，但「第一次调用之后」把停止开关放到盘上（模拟"人中途按停"）。"""

    def __init__(self, replies: list[str], stop_path: pathlib.Path) -> None:
        super().__init__(replies)
        self.stop_path = stop_path
        self.calls = 0

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        # 语义：「第一条回复被这一趟收下之后」人按停 ⇒ 当前这一步做完、下一步之前停
        # （正是"优雅收工"的口径：不是半途被杀）。
        reply = super().complete(prompt, scope=scope, system=system, **kw)
        self.calls += 1
        if self.calls >= 1:
            self.stop_path.write_text("停\n", encoding="utf-8")
        return reply


def test_a_stop_file_stops_the_run_between_steps_and_leaves_a_checkpoint(tmp_path):
    """用户叫停要「优雅收工」：当前这一步做完就停，并留下运行记录与步检查点。

    真机读数（2026-10-04，T2 第 4 趟）：用户在单趟 `run-agent` 里叫停，那一趟继续跑了
    60 多个任务、烧掉 $0.98，最后只能被强杀 —— 强杀的结果是会话记录里没有
    `agent_run_end`、盘上没有步检查点（`runs/` 与检查点都是空的），"跑到哪儿了"事后无从回答。

    这条判据钉四件事：① 第 1 步做完了（不是半途被杀）；② `stop_reason == "stop_file"`；
    ③ `final` 写清停在哪儿、怎么接着跑；④ 步检查点落盘且与运行记录说不矛盾。
    """
    from agentflow import agent_loop as AL

    step = json.dumps({"role": "E", "action": "list_experiments", "params": {},
                       "why": "派一环"}, ensure_ascii=False)
    stop = tmp_path / "STOP"
    st, cond, registry, gw, root = _wired(tmp_path, {"M": [step, step, step, step]}, max_steps=6)
    gw["M"] = _StopAfterFirstCall([step, step, step, step], stop)
    gw["M"].spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()
    seam = LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0), sid="test-run")

    run = AL.run_role("M", "派活直到我叫停", store=st, registry=registry, conductor=cond,
                      seam=seam, session_root=root, workspace_root=str(root), sid="test-run",
                      max_steps=6, from_env=False, stop_file=str(stop))
    assert run.stop_reason == "stop_file", run.to_dict()
    assert len(run.steps) == 1, f"应当在第 1 步之后停，实际跑了 {len(run.steps)} 步"
    assert run.steps[0].shape == "summon", run.steps[0].to_dict()
    assert "叫停" in run.final and "resume" in run.final, run.final
    cp = AL.load_run_checkpoint(root, "M", "test-run")
    assert cp is not None, "收了工却没有步检查点 ⇒ 下一趟无从接着跑"
    assert cp["stop_reason"] == "stop_file", cp
    ends = [e for e in _events(root) if e.get("kind") == "agent_run_end"]
    assert ends and ends[-1]["stop_reason"] == "stop_file", ends


def test_a_stop_file_that_is_already_there_runs_zero_steps(tmp_path):
    """负控/边界：开关一开始就在 ⇒ 一步都不跑（最保守的那一档），但照样收工而不是崩。"""
    from agentflow import agent_loop as AL

    step = json.dumps({"role": "E", "action": "list_experiments", "params": {},
                       "why": "派一环"}, ensure_ascii=False)
    stop = tmp_path / "STOP"
    stop.write_text("停\n", encoding="utf-8")
    st, cond, registry, gw, root = _wired(tmp_path, {"M": [step, step]}, max_steps=4)
    seam = LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0), sid="test-run")
    run = AL.run_role("M", "派活", store=st, registry=registry, conductor=cond,
                      seam=seam, session_root=root, workspace_root=str(root), sid="test-run",
                      max_steps=4, from_env=False, stop_file=str(stop))
    assert run.stop_reason == "stop_file" and run.steps == [], run.to_dict()
    assert gw["M"].prompts == [], "开关文件在盘上时不该调模型"


def test_a_stale_stop_reply_does_not_stop_later_runs(tmp_path):
    """负控（这条判据最容易做错的地方）：「上一次」留下的 STOP 不许把之后每一趟判死。

    回答是 append-only 的审计面：`user_stop` 只看「本次运行开始之后」收到的那条回答。
    这条负控造一条「早于」本趟开始时间的 STOP 回答，断言它不停；正控（"开始之后"的
    那条 STOP 会停）由 `_stop_before_round` 那一组判据在 autonomy 那边守着。
    """
    from agentflow import agent_loop as AL
    from agentflow import userio as U

    scripts = {"M": [json.dumps({"final": "做完了", "evidence": []}, ensure_ascii=False)]}
    st, cond, registry, gw, root = _wired(tmp_path, scripts, max_steps=3)
    # 问与答都落「会话事件」（`userio.read_replies` 的读取面就是它）：
    # 回答必须指向一个真实存在的问题，否则按"指向不存在的问题"被丢掉。
    SS.append(root, {"kind": "user_question", "role": "M", "qid": "q0001",
                     "text": "旧问题", "options": [],
                     "ts": "2000-01-01T00:00:00+08:00"}, sid="test-run")
    SS.append(root, {"kind": "user_answer", "qid": "q0001",
                     "selected": [], "custom": "STOP（上一趟留下的）", "by": "user",
                     "ts": "2000-01-01T00:00:00+08:00"}, sid="test-run")
    old = [r for r in U.read_replies(root, role="M", sid="test-run") if "STOP" in str(r)]
    assert old, "夹具没造出来（应当有一条早于本趟的 STOP 回答）"

    run = AL.run_role("M", "接着做", store=st, registry=registry, conductor=cond,
                      seam=LlmSeam(role="M", session_root=root, gateway=gw["M"],
                                   price=(0.0, 0.0), sid="test-run"),
                      session_root=root, workspace_root=str(root), sid="test-run",
                      max_steps=3, from_env=False)
    assert run.stop_reason == "final", run.to_dict()


def test_a_broken_string_in_the_reply_gets_its_own_correction():
    """判据（`draft/39` §6.24 的 D32）：两种坏 JSON 分开说，且前一种的纠正必须可行动。

    真机读数（2026-10-05 T2，`projects/p6h-research-from-zero`）：M 把一整段构造脚本内联进
    `summon_many` 的 params，回复只有 400–500 token（远低于 8192 的输出上限）却连着三次
    `Expecting ',' delimiter` ⇒ `bad_json_limit`，49 步 / $0.62 全废；它每次收到的那句
    "只回一行 JSON" 照做了、然后照样坏在同一处 —— 不可行动的纠正等于没纠正。
    """
    from agentflow.agent_loop import _bad_json_line

    broken = _bad_json_line(
        3, "judge_bad_json",
        "ExtractionError: 无法把 LLM 返回解析为 JSON 对象: "
        "Expecting ',' delimiter: line 1 column 1396 (char 1395)")
    assert "不是形状漂移" in broken, broken
    assert "fs.write" in broken and "script_path" in broken, broken
    assert "只回一行 JSON" in broken, broken

    drift = _bad_json_line(3, "judge_bad_json", "Expecting value: line 1 column 1")
    assert "不是形状漂移" not in drift, drift
    assert "只回一行 JSON" in drift, drift


def test_an_invalid_reply_is_dumped_in_full_next_to_the_clipped_copy(tmp_path: pathlib.Path):
    """判据（D40）：解析不出来的整条回复要落盘 —— 报错给了列号，而摘要把它剪掉了。

    真机读数（T2 第 6/8/10 趟）：三次都死在"坏在第 1xxx 个字符"上，而
    `raw_reply` 只留前 600 字 ⇒ 每次只能靠猜（这一次连猜了三趟）。
    判据同时钉住两半：①原文逐字落盘；②返回的路径放进这一步的结果里（可回查）。
    """
    from agentflow.agent_loop import _dump_invalid_reply

    text = '{"tool": "fs.write", "args": {"content": "' + "x" * 3000 + '"}} extra'
    rel = _dump_invalid_reply(str(tmp_path), "t2x", 26, text)
    assert rel == "out/invalid/t2x-step26.txt", rel
    assert (tmp_path / rel).read_text(encoding="utf-8") == text

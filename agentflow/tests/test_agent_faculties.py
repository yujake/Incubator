"""耳朵与草稿本：公共频道、私聊准入、运行中收信、只读角色的手。

## 为什么这几条单独成一组

`draft/28` §180 把"智能体面对的不该是一堆按钮"拆成十项官能。其中三项有结构性的一面，
不是改提示词就能有的，必须落到代码上并有判据：

- 耳朵：消息有频道（公共 / 私聊），私聊要有协作边才成立；
  而且运行中新到的消息必须在下一条 prompt 里出现（耳朵一直开着），不是"下次运行再说"。
- 手：只读角色（C / H）在数据面上被结构性禁止写，但草稿本要有（写思考不算写数据）。
- 脑子/讨论：讨论的产物必须落盘（草稿本或台账），否则"讨论过"无法事后核对。

替身模型与 `tests/test_agent_loop.py` 同款：`complete(prompt, *, scope, system)`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import capabilities as C
from agentflow import sessions as SS
from agentflow.agent_loop import (PUBLIC, LlmBackend, inbox_digest, note_path,
                                 notebook_digest, read_messages, run_role, send_message,
                                 write_note)
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

LOOPS: dict[tuple[str, str], dict[str, Any]] = {("D", "consider"): {}}


class ScriptedGateway:
    """照剧本回答的替身模型；可以在第 n 次调用时做一件"外部事件"（模拟运行中来信）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str], *, on_call: Any = None) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.on_call = on_call

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(len(self.prompts))
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 5, "tokens_out": 5,
                                  "error_detail": "", "error_kind": ""})()


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Any, Conductor, Any]:
    """造一个工作区 + 主控 + 工具层（角色对象不接线，模型驱动的动作走循环）。"""
    st = Store(tmp_path / "ws")
    st.init()
    backend = LlmBackend(inner=LocalBackend({}), loops=LOOPS, session_root=st.root,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=st.root,
                                                           gateway=None, sid="t"),
                         store=st, sid="t")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    registry = build_registry(store=st, conductor=cond, workspace_root=str(st.root)).registry
    backend.registry = registry
    return st, registry, cond, st.root


def _run(tmp_path: pathlib.Path, role: str, replies: list[str], *, on_call: Any = None,
         task: str = "干活", max_steps: int = 4) -> Any:
    st, registry, cond, root = _ws(tmp_path)
    gw = ScriptedGateway(replies, on_call=on_call)
    return run_role(role, task, store=st, registry=registry, conductor=cond,
                    seam=LlmSeam(role=role, session_root=root, gateway=gw, price=(0.0, 0.0),
                                 sid="t"), workspace_root=str(root), sid="t",
                    max_steps=max_steps, from_env=False)


def test_public_channel_reaches_everyone_except_the_speaker(tmp_path: pathlib.Path):
    """正控：公共频道的消息，除发信人以外每个角色都收得到。"""
    root = tmp_path / "ws"
    root.mkdir()
    msg_id, problem = send_message(root, sender="C", to=PUBLIC, subject="口径",
                                  body="我把'度数'定义成去重后的邻居数", sid="t")
    assert problem == "" and msg_id == "m0001"
    for role in ("A", "D", "H", "M"):
        msgs, problems = read_messages(root, role, sid="t")
        assert not problems and len(msgs) == 1 and msgs[0]["channel"] == "public", (role, msgs)
    mine, _ = read_messages(root, "C", sid="t")
    assert mine == [], "自己说的话不该回灌到自己的收件箱"


def test_private_message_needs_a_collaboration_edge(tmp_path: pathlib.Path):
    """负控（结构性）：没有协作边的两个角色不许私聊，理由要能读。"""
    st, registry, cond, root = _ws(tmp_path)
    gw = ScriptedGateway([json.dumps({"message": {"to": "H", "subject": "悄悄话",
                                                  "body": "私下说"}}, ensure_ascii=False),
                          json.dumps({"final": "知道了", "evidence": []}, ensure_ascii=False)])
    run = run_role("C", "试着私聊 H", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="C", session_root=root, gateway=gw, price=(0.0, 0.0),
                                sid="t"), workspace_root=str(root), sid="t", from_env=False)
    step = run.steps[0]
    assert step.shape == "message" and step.result.get("ok") is False, step.result
    assert "没有协作边" in str(step.result.get("error")), step.result
    events, _ = SS.read_session(root, sid="t")
    assert not [e for e in events if e.get("kind") == "agent_message"], "被拒的私聊不许留下消息"


def test_private_message_between_partners_is_allowed(tmp_path: pathlib.Path):
    """正控：有协作边的伙伴之间可以私聊（`密切配合` 的那一半）。"""
    st, registry, cond, root = _ws(tmp_path)
    assert "E" in C.ALLOWED_EDGES["D"] and "D" in C.ALLOWED_EDGES["E"]
    gw = ScriptedGateway([json.dumps({"message": {"to": "E", "subject": "约束",
                                                  "body": "只在 n<=5 时成立"}},
                                     ensure_ascii=False),
                          json.dumps({"final": "发好了", "evidence": []}, ensure_ascii=False)])
    run = run_role("D", "把约束告诉 E", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="D", session_root=root, gateway=gw, price=(0.0, 0.0),
                                sid="t"), workspace_root=str(root), sid="t", from_env=False)
    assert run.messages_sent == ["E"], run.to_dict()
    msgs, _ = read_messages(root, "E", sid="t")
    assert msgs and msgs[0]["channel"] == "private" and "n<=5" in msgs[0]["body"]


def test_a_message_arriving_mid_run_is_heard_in_the_next_step(tmp_path: pathlib.Path):
    """正控（耳朵一直开着）：运行中到的消息，必须在下一步的 prompt 里出现。"""
    st, registry, cond, root = _ws(tmp_path)

    def on_call(n: int) -> None:
        if n == 1:      # 第一次调用之后，别人才把消息发进来
            send_message(root, sender="E", to=PUBLIC, subject="反例",
                         body="n=6 时结论不成立，别写死", sid="t")

    gw = ScriptedGateway([json.dumps({"tool": "table.list", "args": {"table": "tasks"}},
                                     ensure_ascii=False),
                          json.dumps({"final": "收到反例，改口径", "evidence": []},
                                     ensure_ascii=False)], on_call=on_call)
    run = run_role("D", "被反驳后改做法", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="D", session_root=root, gateway=gw, price=(0.0, 0.0),
                                sid="t"), workspace_root=str(root), sid="t", max_steps=3,
                   from_env=False)
    assert run.stop_reason == "final"
    heard = run.steps[0].result.get("新消息") or []
    assert heard and "n=6" in str(heard[0].get("body")), run.steps[0].result
    assert "n=6" in gw.prompts[1], "第二步的 prompt 里必须带上新到的消息"
    msgs, _ = read_messages(root, "D", sid="t")
    assert msgs and msgs[0]["delivered"] is True, "听过之后要登记投递"


def test_the_notebook_works_even_for_read_only_roles(tmp_path: pathlib.Path):
    """正控（手）：只读角色也能写草稿本，而且写下的思考会进下一次的 prompt。"""
    st, registry, cond, root = _ws(tmp_path)
    gw = ScriptedGateway([json.dumps({"note": "我怀疑'度数'的定义与 C 的口径不一致"},
                                     ensure_ascii=False),
                          json.dumps({"final": "先记下", "evidence": []}, ensure_ascii=False)])
    run = run_role("C", "想清楚再说", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="C", session_root=root, gateway=gw, price=(0.0, 0.0),
                                sid="t"), workspace_root=str(root), sid="t", from_env=False)
    assert run.steps[0].shape == "note" and run.steps[0].result.get("ok") is True
    text = note_path(root, "C").read_text(encoding="utf-8")
    assert "度数" in text, text
    assert "度数" in notebook_digest(root, "C")
    assert "度数" in gw.prompts[1], "草稿本要出现在下一步的 prompt 里"
    events, _ = SS.read_session(root, sid="t")
    assert any(e.get("kind") == "agent_note" and e.get("role") == "C" for e in events)


def test_a_read_only_role_still_cannot_write_the_data_plane(tmp_path: pathlib.Path):
    """负控（不许顺手破坏只读不变式）：C 的数据面写操作必须被工具层拒。"""
    st, registry, cond, root = _ws(tmp_path)
    gw = ScriptedGateway([json.dumps({"tool": "table.delete",
                                      "args": {"table": "relations", "id": "0000"}},
                                     ensure_ascii=False),
                          json.dumps({"final": "被拒了", "evidence": []}, ensure_ascii=False)])
    run = run_role("C", "试着删一行", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="C", session_root=root, gateway=gw, price=(0.0, 0.0),
                                sid="t"), workspace_root=str(root), sid="t", from_env=False)
    assert run.steps[0].shape == "tool" and run.steps[0].result.get("ok") is False, run.steps[0]
    assert "role" in str(run.steps[0].result.get("error") or "").lower() or \
        run.steps[0].result.get("error"), run.steps[0].result


def test_the_notebook_digest_is_bounded_and_reports_an_empty_book(tmp_path: pathlib.Path):
    """负控（不许真空）：空草稿本要如实说空；写多了只取最近几条。"""
    root = tmp_path / "ws"
    root.mkdir()
    assert notebook_digest(root, "D") == "（草稿本还是空的）"
    for i in range(9):
        path, problem = write_note(root, "D", f"第 {i} 条判断")
        assert problem == "" and pathlib.Path(path).is_file()
    digest = notebook_digest(root, "D", limit=3)
    assert "第 8 条" in digest and "第 5 条" not in digest, digest
    assert len(digest.splitlines()) == 3


def test_a_child_run_leaves_its_full_output_on_disk_for_the_parent_to_read(tmp_path: pathlib.Path):
    """正控（眼睛的用武之地）：子循环的完整产出落盘，父拿到的是路径而不是被截断的摘要。

    真机实测（2026-09-29）：M 拿到的 D 的结论被摘要截断，只能发留言去问已经结束的 D。
    正确做法是把长产出放磁盘、把路径给上游 —— 上游有 fs.read 这只眼睛。
    """
    st, _registry, _cond, root = _ws(tmp_path)
    child_gw = ScriptedGateway([json.dumps({"final": "结论正文：这三条断言证据最弱",
                                            "evidence": ["k-0001"]}, ensure_ascii=False)])
    backend = LlmBackend(inner=LocalBackend({}), loops=LOOPS, session_root=root,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=root,
                                                           gateway=child_gw, price=(0.0, 0.0),
                                                           sid="t"),
                         store=st, sid="t")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    registry = build_registry(store=st, conductor=cond, workspace_root=str(root)).registry
    backend.registry = registry
    m_gw = ScriptedGateway([json.dumps({"summon": {"role": "D", "action": "consider",
                                                    "params": {"qid": "q-1"}}},
                                       ensure_ascii=False),
                            json.dumps({"final": "读到了", "evidence": []}, ensure_ascii=False)])
    run = run_role("M", "派 D 并读它的全文", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=m_gw, price=(0.0, 0.0),
                                sid="t"), workspace_root=str(root), sid="t", from_env=False)
    step = run.steps[0]
    path = str(step.result.get("llm_run_path") or "")
    assert path and pathlib.Path(path).is_file(), step.result
    body = pathlib.Path(path).read_text(encoding="utf-8")
    assert "结论正文" in body and "k-0001" in body, body[:400]
    assert "llm_run" not in step.result, "落盘成功时不该再内联整份记录（那正是截断的来源）"

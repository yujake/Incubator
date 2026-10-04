# -*- coding: utf-8 -*-
"""判据（`draft/37` §134）：交接手稿 —— 编号由脚本给、命名谁给谁、留言带编号 + 一句描述。

用户口径（逐字）：

> 我觉得各智能体在互相传递信息时可以借助手稿的方式，即建一个收集手稿的文件夹，
> 每个智能体要交接工作前写一份手稿放在里面，且有标号（这个标号靠脚本拿最新的，从 0000 开始顺次标），
> 传信息时就传手稿编号。这样的话派活也有依据，溯源也很清晰。
> 至于手稿的命名就是标号+谁to谁，特别地如果是给所有人就是谁toALL。手稿格式就用 LLM 最擅长的 markdown。
> 当然就传个编号感觉有点尬，可以再附一句简要描述

这一组钉六件事：
1. 编号从 `0000` 起顺次、「由脚本分配」（不靠模型记），并发写不撞号；
2. 文件名 `<编号>-<From>to<To>.md`，给所有人是 `toALL`；
3. 索引（`manuscripts/index.jsonl`）逐份一行，读得回来（正文 + 记录）；
4. `handoff` 这一循环形状：写手稿 「并」发出那条带编号 + 简要描述的留言；空手稿被拒（零写入）；
5. 坏收件人/不存在的 refs 被拒（溯源链不许断）；
6. 工具面：`manuscripts.read` / `.list` 对每个角色都可用。
"""
from __future__ import annotations

import json
import pathlib
import threading
from typing import Any

from agentflow import manuscripts as MS
from agentflow import schema as S
from agentflow.agent_loop import LlmBackend, read_messages, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry


def test_ids_start_at_zero_and_names_say_who_to_whom(tmp_path: pathlib.Path):
    """编号 `0000` 起顺次；命名 `<编号>-<From>to<To>.md`；给所有人写 `toALL`。"""
    root = tmp_path / "ws"
    root.mkdir()
    a = MS.write(root, sender="D", recipient="F", title="把猜想交给你", body="证明它。")
    b = MS.write(root, sender="F", recipient=MS.ALL, title="进展汇报", body="卡在第 3 步。")
    assert a["id"] == "0000" and b["id"] == "0001", (a, b)
    assert pathlib.Path(a["path"]).name == "0000-DtoF.md", a["path"]
    assert pathlib.Path(b["path"]).name == "0001-FtoALL.md", b["path"]
    # 索引逐份一行，且与读回一致
    idx = MS.read_index(root)
    assert [r["id"] for r in idx] == ["0000", "0001"], idx
    got = MS.read(root, "0001")
    assert got and "卡在第 3 步" in got["text"] and got["record"]["recipient"] == "ALL", got
    # 广播那份，G 也收得到
    assert [r["id"] for r in MS.list_all(root, to="G")] == ["0001"]


def test_concurrent_writers_do_not_collide(tmp_path: pathlib.Path):
    """并发写不撞号（`conductor.summon_many` 是并发的：撞号的表现是后者覆盖前者）。"""
    root = tmp_path / "ws"
    root.mkdir()
    got: list[str] = []
    lock = threading.Lock()

    def one(i: int) -> None:
        rec = MS.write(root, sender="C", recipient="D", title=f"第 {i} 份", body=f"内容 {i}")
        with lock:
            got.append(rec["id"])

    threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(got)) == 8, f"撞号了：{sorted(got)}"
    assert sorted(got) == [f"{i:04d}" for i in range(8)], sorted(got)
    assert len(list((root / MS.MANUSCRIPTS_DIR).glob("*.md"))) == 8


def test_empty_or_unknown_recipient_is_refused_with_zero_writes(tmp_path: pathlib.Path):
    """负控：空正文 / 坏收件人 / 不存在的 refs ⇒ 拒绝，且一份都不写。"""
    root = tmp_path / "ws"
    root.mkdir()
    for kwargs, why in (
        (dict(sender="D", recipient="F", title="空", body="   "), "空正文"),
        (dict(sender="D", recipient="Z", title="坏收件人", body="x"), "坏收件人"),
        (dict(sender="D", recipient="F", title="引不存在的", body="x", refs=["0099"]), "悬空 refs"),
        (dict(sender="Q", recipient="F", title="坏发件人", body="x"), "坏发件人"),
    ):
        try:
            MS.write(root, **kwargs)
            raise AssertionError(f"{why} 没有被拒")
        except ValueError:
            pass
    assert list((root / MS.MANUSCRIPTS_DIR).glob("*.md")) == [], "被拒的那几次不许留下手稿"


class _Scripted:
    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        got = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": json.dumps(got, ensure_ascii=False),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _run_loop(tmp_path: pathlib.Path, replies: list[dict[str, Any]], *, role: str = "D"):
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    gw = _Scripted(replies)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=ws,
                         seam_factory=lambda r: LlmSeam(role=r, session_root=ws, gateway=gw,
                                                        price=(0.0, 0.0), sid="h1"),
                         max_steps=4, store=st, sid="h1")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond).registry
    backend.registry = reg
    run = run_role(role, "交接", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role=role, session_root=ws, gateway=gw, price=(0.0, 0.0), sid="h1"),
                   session_root=ws, workspace_root=str(ws), sid="h1", max_steps=4, from_env=False)
    return ws, run, reg


def test_the_handoff_shape_writes_the_manuscript_and_sends_the_brief(tmp_path: pathlib.Path):
    """`handoff` 形状：写手稿 + 一条带「编号 + 简要描述」的留言（用户点名的"别只传编号"）。"""
    ws, run, _reg = _run_loop(tmp_path, [
        {"handoff": {"to": "F", "title": "猜想 0000 交给你攻坚",
                     "brief": "请判定它在 n≤12 上是否成立",
                     "body": "## 我做了什么\n立了三行问题。\n## 要你做什么\n攻它。",
                     "refs": [], "why": "你负责攻坚"}},
        {"final": "交接完了", "evidence": []},
    ])
    step = next(s for s in run.steps if s.shape == "handoff")
    res = step.result
    assert res.get("ok") is True, res
    assert res["id"] == "0000" and pathlib.Path(res["path"]).name == "0000-DtoF.md", res
    msgs, problems = read_messages(ws, "F", sid="h1")
    assert not problems, problems
    mine = [m for m in msgs if "手稿 0000" in str(m.get("body"))]
    assert mine, msgs
    assert "请判定它在 n≤12 上是否成立" in str(mine[0]["body"]), mine[0]
    assert "manuscripts.read" in str(mine[0]["body"]), mine[0]


def test_a_handoff_without_a_body_is_refused_as_an_invalid_step(tmp_path: pathlib.Path):
    """负控：空正文的 handoff 判 `invalid`（不是"写了一份空手稿"）。"""
    ws, run, _reg = _run_loop(tmp_path, [
        {"handoff": {"to": "F", "title": "空的", "body": "   "}},
        {"final": "改了", "evidence": []},
    ])
    bad = run.steps[0]
    assert bad.shape == "invalid" and "空手稿" in str(bad.result.get("problem", "")), bad.to_dict()
    assert list((ws / MS.MANUSCRIPTS_DIR).glob("*.md")) == []


def test_every_role_can_read_and_list_but_writing_is_a_loop_shape(tmp_path: pathlib.Path):
    """工具面：`read`/`list` 八个角色都有；「写」不在工具面上（它是 `handoff` 形状）。

    为什么写不做成工具（设计取舍，判据把两半都钉住）：文件名要写"谁给谁"，
    而工具层拿不到 per-call 的身份（注入的 deps 是装配期的）—— 在那里放一个 write
    只会产出"不知道谁写的交接手稿"。循环形状知道 `self.role`，所以写放在那里。

    主控 M 不在这张读面上（第二个断言）：M 的读面是"编排面 + `fs.*` 白名单"
    （`draft/37` §38/§57），而 `manuscripts/*.md` 就在工作区里 —— M 用 `fs.read`
    读同一批文件，不必为它扩这条边界（扩了要裁定，`tests/test_conductor_tools.py`
    的 `M_TOOL_FACE` 相等断言也会红）。
    """
    (tmp_path / "ws" / "data").mkdir(parents=True)
    st = Store(tmp_path / "ws")
    st.init()
    reg = build_registry(store=st, conductor=Conductor(st)).registry
    for role in sorted(S.ROLES):
        names = {t.name for t in reg.for_role(role)}
        assert {"manuscripts.read", "manuscripts.list"} <= names, (role, sorted(names))
        assert "manuscripts.write" not in names, (role, "写手稿不该在工具面上")
    m_names = {t.name for t in reg.for_role(S.CONDUCTOR_ROLE)}
    assert not ({"manuscripts.read", "manuscripts.list"} & m_names), sorted(m_names)

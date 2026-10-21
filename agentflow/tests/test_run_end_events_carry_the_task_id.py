"""判据：`agent_run_end`（收工那一行）必须带这一趟自己的绝对编号。

## 起因（业主 2026-10-21「全面接入」第二步）

第一步给对话线加了 `task_id` / `task_id_source`（见
`tests/test_chat_lines_carry_the_absolute_id.py`），真机读数立刻暴露一个写侧缺口：

    user | M | t-000001 | 起一趟
    team | A | missing  | A 交付      ← `agent_run_end` 事件里没有 task_id
    team | —  | t-000003 | E → D（private）
    team | E | missing  | E 交付      ← 同上

即 `agent_run_start` 带 `task_id`、`agent_message` 带 `from_task_id`，唯独收工那一行不带。
于是"哪个绝对编号的哪个角色在说话"这句话在交付那一行上答不出来 —— 而交付正是最该答得
出来的那一行。

## 这一组钉五件事

1. 写侧正控：真跑一趟（离线替身模型，花 0 元），盘上的 `agent_run_end` 必须带 `task_id`，
   且它的值等于这一趟 `tasks` 行的号、也等于 `agent_run_start` 那一条的号（三者同一份）；
2. 读侧正控（老数据回填）：同一岗在本段会话里唯一那一趟有编号 ⇒ 交付线的
   `task_id_source` 是 `inherited`，编号就是那一趟的号；
3. 读侧负控：同一岗跑过两趟（两个不同编号）⇒ 不许猜，仍是 `missing`；
   另一半负控：有一条 `agent_run_start` 自己没记编号 ⇒ 也不许猜（老的那一趟与新
   的那一趟分不开）；
4. 老数据：整段会话一条编号都没有 ⇒ `missing`，且 `task_id` 是空串（不是"空串冒充有编号"：
   判据看的是 `task_id_source`，页面上显示「（未记录编号）」）；
5. 端到端：把第 1 条产出的真实事件流喂给 `chat_face`，"某某交付"那条线的
   `task_id_source` 不是 `missing`。

改前红（实测 2026-10-21，把 `agent_loop.py` / `readers.py` 换回 HEAD 那一版、其余不变，
在临时目录里跑本文件）：`3 failed, 3 passed` —— 红的是第 1、2、5 条
（`agent_run_end` 的键集里没有 `task_id`；交付线的 `task_id_source` 读到 `missing`），
绿的是第 3 条那两条负控与第 4 条（它们本来就该判 `missing`，改前改后都必须是绿的：
回填不许把"拿不准"补成一个号）。补上写侧那一格与 `inherited` 回填之后：`6 passed`。
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import sessions as SS  # noqa: E402
from agentflow.agent_loop import LlmBackend, run_role  # noqa: E402
from agentflow.conductor import Conductor, LocalBackend  # noqa: E402
from agentflow.llmseam import LlmSeam  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402
from agentflow.webui import readers as R  # noqa: E402

#: 替身模型的花销口径：0 元（这一组判据不许花钱）。
FREE = (0.0, 0.0)


class _ScriptedGateway:
    """照剧本回答的替身模型（与 `tests/test_agent_loop.py` 里那只同形，接口与真模型一致）。"""

    spec = type("_Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        del scope, kw
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("_Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                   "tokens_out": 10, "error_detail": "",
                                   "error_kind": ""})()


def _run_a_real_loop(tmp_path: pathlib.Path, role: str = "A") -> tuple[Any, pathlib.Path, Any]:
    """离线真跑一趟（替身模型 + 0 元价），返回 `(run, 工作区根, store)`。

    为什么非要用真循环（而不是直接拼一条事件）：第 1 条判据要钉的正是"发事件那一侧"
    的形态 —— 手工拼一条带 `task_id` 的 dict 只能证明测试会写字，证明不了 `run_role`
    会把号写进去。这一趟的模型第一步就交 `final`，所以不派活、不调工具、不花钱。
    """
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    gw = _ScriptedGateway([json.dumps({"final": "这一趟的交付：做完了", "evidence": []},
                                      ensure_ascii=False)])

    def seam_factory(one: str) -> LlmSeam:
        return LlmSeam(role=one, session_root=root, gateway=gw, price=FREE, sid="test-run")

    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=root,
                         seam_factory=seam_factory, max_steps=2, store=st, sid="test-run")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond)
    backend.registry = built.registry
    run = run_role(role, "起一趟（判据）", store=st, registry=built.registry, conductor=cond,
                   seam=LlmSeam(role=role, session_root=root, gateway=gw, price=FREE,
                                sid="test-run"),
                   session_root=root, workspace_root=str(root), sid="test-run",
                   max_steps=2, from_env=False)
    return run, root, st


def _events(root: pathlib.Path) -> list[dict]:
    events, problems = SS.read_session(root, sid="test-run")
    assert not problems, problems
    return events


def _lines(events: list[dict], root: pathlib.Path | None = None,
           sid: str = "test-run") -> list[dict]:
    """事件流 → 对话线；给了 `root` 就走 `chat_face`（于是 `inherited` 也在），
    不给就只调 `_chat_line`（那一层永远只有 `event` / `missing`）。"""
    if root is not None:
        return list(R.chat_face(root, sid)["lines"])
    out = []
    for i, ev in enumerate(events):
        line = R._chat_line(i, ev)
        if line is not None:
            out.append(line)
    return out


def _worker(role: str, task_id: str, *, sid: str = "t") -> list[dict]:
    """一段会话的夹具：某一岗起一趟 + 收工，编号按参数给（空串 = 老事件没记）。"""
    start: dict[str, Any] = {"kind": "agent_run_start", "role": role, "task": "起一趟"}
    if task_id:
        start["task_id"] = task_id
    return [start, {"kind": "agent_run_end", "role": role, "final": f"{role} 交付"}]


def _store_with(tmp_path: pathlib.Path, events: list[dict]) -> pathlib.Path:
    root = tmp_path / "ws-fixture"
    Store(root).init()
    for ev in events:
        SS.append(root, ev, sid="t")
    return root


# ================================================================ 1 写侧正控
def test_the_run_end_event_carries_the_runs_own_task_id(tmp_path: pathlib.Path) -> None:
    """判据 1：真跑一趟，收工那一行必须带 `task_id`，且与台账行 / start 事件同一份。

    三处同号是这条判据的实体：`tasks` 那一行（台账身份）、`agent_run_start.task_id`
    （这一趟开始的读数）、`agent_run_end.task_id`（这一趟收工的读数）—— 改前第三处
    不存在，于是"这一条交付属于哪一趟"只能靠角色猜。
    """
    run, root, st = _run_a_real_loop(tmp_path, role="A")
    assert str(run.stop_reason) == "final", run.to_dict()
    events = _events(root)
    ends = [e for e in events if str(e.get("kind")) == "agent_run_end"]
    assert len(ends) == 1, f"这一段会话应当恰好一条收工事件：{[e.get('kind') for e in events]}"
    end = ends[0]
    end_id = str(end.get("task_id") or "")
    assert end_id, f"agent_run_end 没有 task_id（改前的形态）：{sorted(end)}"

    starts = [e for e in events if str(e.get("kind")) == "agent_run_start"]
    assert starts, "这一趟没有 start 事件 ⇒ 判据失去对照"
    assert str(starts[-1].get("task_id") or "") == end_id, (
        starts[-1].get("task_id"), end_id)

    rows = [r for r in st.rows("tasks")
            if str(r.get("role") or "") == "A" and not str(r.get("kind") or "")]
    assert [str(r.get("task_id") or "") for r in rows] == [end_id], (
        "收工事件上的号与台账这一趟那行的号不是同一个", rows)


# ================================================================ 2 读侧正控（回填）
def test_an_old_run_end_inherits_the_only_id_of_that_role(tmp_path: pathlib.Path) -> None:
    """判据 2：老事件没记编号，但同一岗在本段唯一那一趟有编号 ⇒ 回填成 `inherited`。

    为什么允许回填：同一个会话里"role=M 只起过一趟"是一个可以核的事实（`agent_run_start`
    那一条在盘上），而收工那一行没有编号只说明它落盘的时刻早于写侧补丁。回填要标出来的
    理由也在这里：它不是"事件里真有"，读的人有权知道这一格的来路。
    """
    root = _store_with(tmp_path, _worker("M", "t-000001"))
    lines = _lines([], root=root, sid="t")
    deliveries = [l for l in lines if str(l.get("kind")) == "agent_run_end"]
    assert len(deliveries) == 1, lines
    line = deliveries[0]
    assert line["task_id"] == "t-000001", line
    assert line["task_id_source"] == "inherited", line
    # 另一半：起趟那条线本来就有编号 ⇒ 它是 event，不许被回填规则改写
    starts = [l for l in lines if str(l.get("kind")) == "agent_run_start"]
    assert starts and starts[0]["task_id_source"] == "event", starts


# ================================================================ 3 读侧负控（不许猜）
def test_two_runs_of_the_same_role_leave_the_delivery_missing(tmp_path: pathlib.Path) -> None:
    """判据 3-a：同一岗跑过两趟（两个不同编号）⇒ 收工那条线仍是 `missing`。

    这一条是回填的负控：那一段会话里这一岗有两个号，而收工那一行没有编号 ⇒ 盘上没有
    任何证据说它属于哪一趟。猜一个就是给读的人一句假话，而假话在这一格上的形态是
    "它看起来有编号"。
    """
    events = [{"kind": "agent_run_start", "role": "M", "task": "第一趟", "task_id": "t-000001"},
              {"kind": "agent_run_start", "role": "M", "task": "第二趟", "task_id": "t-000009"},
              {"kind": "agent_run_end", "role": "M", "final": "第二趟的交付"}]
    root = _store_with(tmp_path, events)
    lines = _lines([], root=root, sid="t")
    deliveries = [l for l in lines if str(l.get("kind")) == "agent_run_end"]
    assert len(deliveries) == 1, lines
    assert deliveries[0]["task_id"] == "", deliveries[0]
    assert deliveries[0]["task_id_source"] == "missing", deliveries[0]


def test_a_start_without_an_id_also_blocks_the_backfill(tmp_path: pathlib.Path) -> None:
    """判据 3-b：同一岗有两条 start、其中一条自己没记编号 ⇒ 同样不许猜。

    为什么这也要红：两个号分不开是"有证据、但对不上"；这一个更糟 —— 老的那一趟与新
    的那一趟在盘上长得一样，把新号回填给老事件就是把两趟混成一条。三态纪律在这里的
    落地形态是照实标 `missing`，不是"尽量补一个"。
    """
    events = [{"kind": "agent_run_start", "role": "M", "task": "老的那一趟"},   # 没记编号
              {"kind": "agent_run_start", "role": "M", "task": "新的那一趟",
               "task_id": "t-000002"},
              {"kind": "agent_run_end", "role": "M", "final": "不知道属于哪一趟的交付"}]
    root = _store_with(tmp_path, events)
    lines = _lines([], root=root, sid="t")
    deliveries = [l for l in lines if str(l.get("kind")) == "agent_run_end"]
    assert len(deliveries) == 1, lines
    assert deliveries[0]["task_id"] == "", deliveries[0]
    assert deliveries[0]["task_id_source"] == "missing", deliveries[0]


# ================================================================ 4 老数据
def test_a_session_without_any_id_says_missing_not_an_empty_id(
        tmp_path: pathlib.Path) -> None:
    """判据 4：整段会话一条编号都没有 ⇒ `missing`，且 `task_id` 是空串。

    两档都要判：空串单独看没有意义（它既可能是"没记"也可能是"记了个空"），
    于是"这一格到底有没有编号"由 `task_id_source` 说话 —— 页面照它显示「（未记录编号）」。
    反过来，把 `missing` 写成空串混过去（`task_id_source` 也留空）必须红。
    """
    root = _store_with(tmp_path, _worker("A", ""))
    lines = _lines([], root=root, sid="t")
    deliveries = [l for l in lines if str(l.get("kind")) == "agent_run_end"]
    assert len(deliveries) == 1, lines
    assert deliveries[0]["task_id"] == "", deliveries[0]
    assert deliveries[0]["task_id_source"] == "missing", deliveries[0]
    # 每一条线都要有这两格，且来源值是三档里的一个（缺键 / 空串都不算"标了"）
    for line in lines:
        assert set(line) >= {"task_id", "task_id_source"}, line
        assert line["task_id_source"] in ("event", "inherited", "missing"), line


# ================================================================ 5 端到端
def test_the_delivery_line_of_a_real_run_is_never_missing(tmp_path: pathlib.Path) -> None:
    """判据 5：第 1 条那趟真跑出来的事件流喂给 `chat_face`，交付线的来源不是 missing。

    这一条是端到端的那一半：写侧（第 1 条）与读侧（第 2/3 条）在同一份盘上数据上
    接起来 —— 改前这里必红（收工事件没有编号，而这一段会话里 A 只起过一趟，回填规则
    还没落地时两档都救不了它：事件没有、同理也拿不到 inherited）。

    反负控：这条线必须是 `agent_run_end` 投出来的那条（不是随便哪条线有编号就算），
    且它的正文里带着这一趟的交付那句话。
    """
    run, root, _st = _run_a_real_loop(tmp_path, role="A")
    lines = _lines([], root=root, sid="test-run")
    deliveries = [l for l in lines
                  if str(l.get("kind")) == "agent_run_end" and str(l.get("who")) == "team"]
    assert len(deliveries) == 1, [l.get("kind") for l in lines]
    line = deliveries[0]
    assert line["title"] == "A 交付", line
    assert line["text"].startswith("这一趟的交付"), line
    assert line["task_id_source"] != "missing", line
    assert line["task_id"] != "", line
    # 编号指回台账那一行（同一个号在两条事件与台账三处一致，第 1 条已钉过一遍）
    starts = [e for e in _events(root) if str(e.get("kind")) == "agent_run_start"]
    assert starts and line["task_id"] == str(starts[-1].get("task_id") or ""), line

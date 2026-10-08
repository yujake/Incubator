# -*- coding: utf-8 -*-
"""父是谁、子有谁（业主 T21 附）+ 终态回报挂在父名下（D89）—— 2026-10-08 深夜，S1d。

业主的追问逐字：「不就应该是知道我的父代理是谁，子代理有谁，然后往它们按编号沟通吗」。
对着代码逐件核对，三件事里两件的渲染缺了：

| 要知道的 | 数据在不在 | 渲染 |
|---|---|---|
| 我是谁 | 在（`my_task_id`） | 在（`{{task_id}}`） |
| 我父是谁 | 在（我那一行的 `parent_task_id`） | 缺（提示词只给角色名 `{{summoned_by}}`） |
| 我子有谁 | 在（`_children_of(我的编号)`） | 缺 |

这一批补的就是"渲染"那一半：`AGENT_IDENTITY` 补 `{{parent_task_id}}` / `{{children}}`
两格（共享段 ⇒ `PROMPT_VERSION` p44 → p45，十格摘要一起动，那条判据在
`tests/test_agent_prompts.py`）。同一批修 D89：`_emit_settlement` 把终态通报挂在
自己名下（`parent_task_id=self.my_task_id`、`role=M`），而板项那一格的列义是
"收件人的编号" ⇒ 子报给父时必须写父的台账号，否则父的待办视图
（`in_flight_items(父的编号)`）里永远看不到"哪个子向我交差了"。

判据在这个文件里成对给：正控（渲染出来的提示词里读得到父/子的编号）+
负控（把那一格删掉/换成别人的编号 ⇒ 红）。所有替身都不联网。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import agent_prompts as AP
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "t21"


class _Gate:
    """照剧本回答的替身模型（只记 `system` 提示词，不联网）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        self.systems.append(system or "")
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _item(cond: Conductor, *, role: str, parent: str, depth: int, key: str) -> str:
    """开一条 `kind="delegation"` 的工作项行（派给 `role` 的一件活）。"""
    return cond.open_item(kind="delegation", role=role, expects="work", action="write_report",
                          summary=f"派给 {role} 的一件活（{key}）", called_by="M",
                          parent_task_id=parent, depth=depth, input_key=key)


def _child(cond: Conductor, *, role: str, parent: str, depth: int, key: str) -> str:
    """建一条子代理实例行（`kind == ""`）—— 与 `summon` 建的那种行同形。

    为什么不直接用 `open_item`：`open_item` 建的是工作项行（`kind` 非空），而
    "我的子代理是谁"问的是代理。`draft/88` 的状态机把两者分成两行
    （`queued → claimed`（接手、写 `running` 行）），这里直接造"已经接手"的那一行，
    不跑整条链、也不跑一整个子循环 —— 这一条判据问的只是"渲染出来的那一格写着谁"。

    实例行的建行点是 `summon`（走 `_write_new_row`，全仓唯一的新行临界区），
    测试里调它而不是自己拼一个 dict 落盘，是为了让"键集/键序只有一处口径"（I-9）
    这条约束在测试里也成立。
    """
    row = {"role": role, "action": "write_report", "called_by": "M", "parent_task_id": parent,
           "depth": depth, "input_key": key, "status": "running", "outcome": None,
           "refusal_reason": None, "instance": "", "detail": f"派给 {role} 的活（{key}）",
           "error": None, "started_at": "2026-10-08T22:00:00+08:00", "ended_at": None,
           "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": []}
    return cond._write_new_row(row, note="start:test")


def _tree(tmp_path: pathlib.Path, *, role: str = "D") -> tuple[Any, Conductor, Any, pathlib.Path,
                                                              str, tuple[str, str], str]:
    """造一棵三层树：顶层那一趟（父）→ 我 → 我名下的两个孩子；另加一个别人的孩子。

    返回 `(store, conductor, registry, ws, 我的编号, (我的两个孩子编号), 别人的编号)`。
    别人的那个孩子（同一个父、但父不是"我"）是负控的素材：它不许出现在我的
    `{{children}}` 里 —— 否则那一格会退化成"这一层所有实例"。
    """
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    parent = cond.open_top_level_run("M", "顶层那一趟的活")
    me = _item(cond, role=role, parent=parent, depth=2, key="me@1")
    # 我名下的两个子代理（实例行）与一个别人的孩子（兄弟）。
    # 注意：`me` 自己是工作项行（`kind="delegation"`，派给我的一件活）——
    # 这正是"我"在台账里的身份：一个被派了活的实例。
    kids = (_child(cond, role="B", parent=me, depth=3, key="kid1@1"),
            _child(cond, role="G", parent=me, depth=3, key="kid2@1"))
    other = _child(cond, role=role, parent=parent, depth=2, key="sibling@1")
    return st, cond, reg, ws, me, kids, other


def _loop(cond: Conductor, reg: Any, ws: pathlib.Path, st: Store, gate: _Gate,
          *, role: str = "D") -> AgentLoop:
    return AgentLoop(role=role, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=role, session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)


def _board(st: Store, kind: str = "") -> list[dict]:
    return [r for r in st.rows("tasks")
            if str(r.get("kind") or "") and (not kind or str(r.get("kind")) == kind)]


# ============================================================ 正控：两格真的渲染出来了

def test_the_prompt_tells_a_child_who_its_parent_is(tmp_path: pathlib.Path):
    """正控：子这一趟渲染出来的提示词里读得到父的台账号（改前一个字都没有）。

    改前必红：`AGENT_IDENTITY` 只有 `{{summoned_by}}`（角色名）与 `{{task_id}}`
    （自己的编号）⇒ 模型知道"我是被 M 唤起的"，但不知道"M 的哪一趟"，
    于是"往它按编号沟通"这件事在模型这一侧根本没有输入。
    """
    st, cond, reg, ws, me, _kids, _other = _tree(tmp_path)
    parent = str(next(r for r in st.rows("tasks") if str(r.get("task_id")) == me)["parent_task_id"])
    gate = _Gate([json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    run = _loop(cond, reg, ws, st, gate).run("把这一趟做完", summoned_by="M",
                                             my_task_id=me, depth=2)
    assert run.stop_reason == "final", run.to_dict()
    system = gate.systems[-1]
    assert f"你的父代理台账号：{parent}" in system, system[-800:]
    assert me not in system.split("你的父代理台账号：")[1].split("\n")[0], (
        "父那一格写的必须**不是**自己的编号（写自己的就是 D89 那个形态）：", system[-800:])


def test_the_prompt_tells_a_parent_which_children_it_has(tmp_path: pathlib.Path):
    """正控：`{{children}}` 列出此刻我名下的直接子代理，且不含别人的孩子。

    负控就在同一条里：`other` 与我是同一个父的兄弟 —— 它出现即红
    （那一格会退化成"这一层所有实例"，而"我子有谁"就答错了）。
    """
    st, cond, reg, ws, me, kids, other = _tree(tmp_path)
    gate = _Gate([json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    _loop(cond, reg, ws, st, gate).run("把这一趟做完", summoned_by="M", my_task_id=me, depth=2)
    system = gate.systems[-1]
    line = system.split("此刻你名下的子代理台账号：")[1].split("\n")[0]
    for kid in kids:
        assert kid in line, (line, system[-800:])
    assert other not in line, ("兄弟（同一个父、但父不是我）不许进我这一格：", line)


def test_a_work_item_addressed_to_me_is_not_reported_as_a_child_agent(
        tmp_path: pathlib.Path):
    """负控（两轴必须分开）：挂在我名下的工作项不许出现在 `{{children}}` 里。

    板项的 `parent_task_id` 口径是"收件人的编号"（T21 附二 / D89）⇒ 一条
    "某子代理已收工"的 `notice` 挂在我名下。若"我的子代理"按 `parent_task_id`
    数行而不看出身，这条通报就会被当成"我的一个子代理"；更糟的是它会永久占住
    扇出名额 —— 实测（`temp/_probe_board_vs_fanout_and_dispose.py`）：父名下 20 条
    `notice` ⇒ `_in_flight_children_of(父)` = 20 ⇒ 派活被 `fanout_exceeded` 拒掉，
    而那 20 条一个代理都不是。

    这一条同时钉住两轴各自的读数：工作项轴（`in_flight_items`）要看得到它，
    代理轴（`{{children}}`）不许看到它。
    """
    st, cond, reg, ws, me, kids, _other = _tree(tmp_path)
    notice = cond.open_item(kind="notice", role="D", expects="ack", summary="某个子代理已收工",
                            called_by="B", parent_task_id=me, depth=3, input_key="notice@B:1")
    gate = _Gate([json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    _loop(cond, reg, ws, st, gate).run("把这一趟做完", summoned_by="M", my_task_id=me, depth=2)
    line = gate.systems[-1].split("此刻你名下的子代理台账号：")[1].split("\n")[0]
    assert notice not in line, ("工作项不是子代理（两轴分开）：", line, notice)
    for kid in kids:
        assert kid in line, (line, kids)
    assert str(notice) in {str(r["task_id"]) for r in cond.in_flight_items(me)}, (
        "工作项轴必须看得到它（它是要我消的项）：", cond.in_flight_items(me))
    assert str(notice) not in cond._children_of(me), (
        "代理轴不许看到它：", cond._children_of(me))


def test_no_children_is_rendered_as_a_sentence_not_an_empty_cell(tmp_path: pathlib.Path):
    """负控（口径）：名下确实没有子代理时，那一格写的是一句人话，不是空串。

    为什么这条要有：留空与"没有"在模型眼里长得一样（T21 附逐字）。所以缺省值必须
    是一句能读的话；这一条把它钉住（谁哪天把缺省改成 `""`，严格插值会先红，
    但"渲染成空串"的另一条路（给了空串）在这里也会红）。
    """
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    parent = cond.open_top_level_run("M", "顶层那一趟的活")
    me = _item(cond, role="D", parent=parent, depth=2, key="me@1")
    gate = _Gate([json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    _loop(cond, reg, ws, st, gate).run("把这一趟做完", summoned_by="M", my_task_id=me, depth=2)
    system = gate.systems[-1]
    assert "此刻你名下的子代理台账号：（此刻名下没有子代理）" in system, system[-800:]


# ============================================================ 负控：删掉那一格 ⇒ 红

def test_the_two_cells_are_the_only_source_of_those_ids(tmp_path: pathlib.Path):
    """负控（反真空）：不喂这两格时，渲染出来的提示词里读不到父与子的编号。

    没有这一条，上面两条正控可能靠别处（任务原文、伙伴表、收件箱……）恰好出现的
    编号变绿 —— 那测的就不是"这两格渲染出来了"。这里用同一个注册表、同一个角色，
    只把 `parent_task_id` / `children` 留空，断言：① 两个编号都不出现；
    ② 两格的缺省句出现（= 那一格真的在渲染，只是内容是缺省）。
    """
    _st, cond, reg, ws, me, kids, _other = _tree(tmp_path)
    parent = str(cond._task(me)["parent_task_id"])          # 判据素材：真父编号
    text = AP.system_prompt("D", registry=reg, task="把这一趟做完", summoned_by="M",
                            task_id=me, depth=2, inbox="（没有收到留言）")
    assert parent not in text, ("没喂父编号却在提示词里读到了它 ⇒ "
                                "上面那条正控不是这两格给的：", text[-800:])
    for kid in kids:
        assert kid not in text, ("没喂子编号却在提示词里读到了它 ⇒ 同上的问题：", kid)
    assert "你的父代理台账号：（顶层发起：这一趟没有父代理的台账号）" in text, text[-800:]
    assert "此刻你名下的子代理台账号：（此刻名下没有子代理）" in text, text[-800:]


def test_an_unreadable_ledger_is_not_folded_into_having_no_parent(tmp_path: pathlib.Path):
    """负控（三态）：台账里没有我这一行 ⇒ 如实说"没读成"，不许当成"没有父"。

    "没有父"（顶层发起）与"父没读成"在盘上的后果不同（后者是回报挂错了名字），
    而它们长得一样时没人能事后分辨。所以读数必须写进 `run.notes`，提示词那一格
    落回缺省句（"顶层发起"）—— 两件事都断言，缺一条这条判据就只剩一半。
    """
    st, cond, reg, ws, _me, _kids, _other = _tree(tmp_path)
    gate = _Gate([json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    run = _loop(cond, reg, ws, st, gate).run("把这一趟做完", summoned_by="M",
                                             my_task_id="t-9999", depth=2)
    assert any("父代理没读成" in str(n) for n in run.notes), run.notes
    assert any("t-9999" in str(n) for n in run.notes), run.notes
    system = gate.systems[-1]
    assert "你的父代理台账号：（没读成：" in system, system[-800:]
    assert "你的父代理台账号：t-9999" not in system, (
        "拿自己的编号冒充父的编号是最坏的一种'看起来成功'（模型会照它去沟通）：",
        system[-800:])
    assert "你的父代理台账号：（顶层发起" not in system, (
        "读不成 ≠ 顶层发起（三态）：", system[-800:])


# ============================================================ D89：终态回报挂在父名下

def test_the_settlement_notice_hangs_under_the_parent_not_under_itself(tmp_path: pathlib.Path):
    """正控（D89）：子收工时框架补的那条 `notice`，`parent_task_id` = 父的台账号。

    改前必红的形态逐字：`parent_task_id=self.my_task_id`（挂在自己名下）、
    `role=S.CONDUCTOR_ROLE`。这一条同时判三样：
    ① 收件人是父的编号（不是自己的）；② 收件人的角色是父的角色（`called_by`）；
    ③ 父的待办视图 `in_flight_items(父的编号)` 里看得到它。
    负控在同一处：`in_flight_items(我自己的编号)` 里没有它 —— 那正是改前那个形态。
    """
    st, cond, reg, ws, me, _kids, _other = _tree(tmp_path)
    parent = str(cond._task(me)["parent_task_id"])
    parent_role = str(cond._task(parent)["role"])
    gate = _Gate([json.dumps({"final": "这一趟做完了", "evidence": []}, ensure_ascii=False)])
    run = _loop(cond, reg, ws, st, gate).run("把这一趟做完", summoned_by=parent_role,
                                             my_task_id=me, depth=2)
    assert run.stop_reason == "final", run.to_dict()
    notices = _board(st, "notice")
    assert len(notices) == 1, notices
    it = notices[0]
    assert it["parent_task_id"] == parent, ("终态通报必须挂在**父**的台账号下（D89）：", it)
    assert it["parent_task_id"] != me, it
    assert it["role"] == parent_role, it
    assert it["called_by"] == "D", ("这一项是我发出的 ⇒ 发信人是我的角色：", it)
    assert it["depth"] == 2, ("板项是父的子行 ⇒ 深度 = 父的深度 + 1 = 我的深度：", it)
    assert str(it["task_id"]) in {str(r["task_id"]) for r in cond.in_flight_items(parent)}, (
        "父的待办视图里必须看得到「哪个子向我交差了」：", cond.in_flight_items(parent))
    assert str(it["task_id"]) not in {str(r["task_id"]) for r in cond.in_flight_items(me)}, (
        "挂在**自己**名下就是改前那个形态（负控）：", cond.in_flight_items(me))

# -*- coding: utf-8 -*-
"""秘书的发出口：这一份内容与它的收件面相符吗（业主 2026-10-26）。

## 业主原话（逐字）
「秘书处理将发出的信息时，要看内容是否与接受面相符，这条显然该拆两条单独派活，这是秘书没有
意识，未向 M 提醒」

## 现场（`projects/mp3-r3` 的真机手稿 000000，还在盘上）
一条 `handoff(to=ALL)` 的正文里装着两件派活（给 A、给 D），秘书照发。同一段内容若走
`message`，会被 `public_is_not_a_conversation` 拒（公告栏里点名 + 指令语气，见
`tests/test_only_the_roster_can_talk.py`）—— 而 `handoff` 那条路不过那道判据
⇒ 同一件事换个通道就绕过去了。

## 这一组守五件事
1. 真机那一条（`to=ALL` + 正文「A（派活：…），D（派活：…）」）⇒ 秘书拒 + 盘上 0 条手稿
   （改前红：秘书照发，手稿 000000 就是那么落盘的）；
1b. `to=ALL` 里点名某个名册成员并下指令 ⇒ 拒 `public_is_not_a_conversation`
   （这一档原先只在 `message` 那条路上有，`handoff` 不过它）；
2. 单收件人的派活 ⇒ 照发（正控：别把正常的派活一起堵死；另核"同一件事写两遍"仍算一件）；
3. 真公告（`to=ALL`、不点名、无指令语气）⇒ 照发（正控：别把公告也堵死）；
4. 反真空：把秘书那一处判断打桩成恒放行 ⇒ 第 1 条必红。

零模型：替身网关照剧本回答，价格 0。装配（树 + 名册 + 循环）引
`test_children_and_parent_are_visible` 的 `_item` / `_child` / `_loop`，
不另造一套父子夹具、不新造通道。

## 这一组不测什么（如实写清边界）
- 不测"秘书要不要给 M 落一条通知"：这一版按主控裁定走既有的回流（拒信回给本体那一步 +
  `secretary_decision` 台账），没有新开 notice / 板项；
- 不测提示词：`PROMPT_VERSION` 与提示词正文一个字都没动（这一条判据是"看内容"，
  不是"教模型怎么写"）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import test_children_and_parent_are_visible as TCP

from agentflow import manuscripts as MS
from agentflow import secretary as SEC
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.tools import build_registry

#: 真机那一份手稿（`projects/mp3-r3/manuscripts/handoffs.jsonl` 的 000000）的正文与一句话。
#: 刻意逐字节抄下来：这条判据量的就是"真机上那一条进来会发生什么"。
REAL_SUMMARY = "派活：A（派活：检索这两个英文主题的文献），D（派活：研究问题）"
REAL_BODY = (
    "# M → ALL｜派活：A（派活：检索这两个英文主题的文献：(1) 'noetherian universal enveloping "
    "algebra infinite dimensional Lie algebra'；(2) 'universal enveloping algebra of the Witt "
    "algebra is not noetherian'。逐条报 outcome 与 result_lit_ids；检索不到就如实报 "
    "no_results，并换规范术语再查一次。不要做概念抽取（那是 B 的活）。）, "
    "D（派活：研究问题：char 0 域 k 上李代数 g，其泛包络代数 U(g) 诺特是否迫使 dim g < ∞。"
    "先读 out/review/PLAN.md，只当建议、对错你自己复核。要做：(1) 立研究问题；"
    "(2) 把主分析写清楚并落 reports/<qid>-research.md；(3) 登记可判定猜想；(4) 明确写出"
    "哪些结论属已知文献、哪些是我们自己给的、哪些是开放缺口。）"
)

#: 名册（真机 `projects/mp3-r3/out/roster/t-000001.jsonl` 同形）：名册名 `A1`/`D1`，
#: 角色 `A`/`D` —— 真机正文里写的是角色代号，所以这两格都必须在名册上。
ROSTER: tuple[tuple[str, str, str], ...] = (("A1", "A", "检索这两个英文主题的文献"),
                                            ("D1", "D", "U(g) 诺特是否迫使有限维：主分析"))


def _say(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _tree(tmp_path: pathlib.Path) -> tuple[Store, Conductor, Any, pathlib.Path, str,
                                           dict[str, str]]:
    """造"我这一趟 + 名下两个子代理（A1 / D1）"：返回 `(store, conductor, registry, ws,
    我的台账号, {名册名: 台账号})`。

    行与行之间的关系用 `test_children_and_parent_are_visible` 的两个建行点
    （`_item` / `_child`）造 —— 那是全仓唯一的新行临界区的测试侧入口，不自己拼 dict 落盘。
    """
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run("M", "顶层那一趟的活")
    me = TCP._item(cond, role="M", parent=top, depth=2, key="me@1")
    kids = {name: TCP._child(cond, role=role, parent=me, depth=3, key=f"{name}@1")
            for name, role, _brief in ROSTER}
    return st, cond, reg, ws, me, kids


def _loop(cond: Conductor, reg: Any, ws: pathlib.Path, st: Store,
          replies: list[dict[str, Any]]) -> AgentLoop:
    """跑一趟 `M` 的循环（`max_steps=2`：一条 handoff + 收工）。"""
    return TCP._loop(cond, reg, ws, st, TCP._Gate([_say(x) for x in replies]), role="M")


def _register(loop: AgentLoop, me: str, kids: dict[str, str]) -> None:
    """把两个子代理登记进我的名册（这是"我能不能叫到它"的唯一来源）。"""
    for name, role, brief in ROSTER:
        got = loop.secretary.roster_add(owner=me, role=role, task_id=kids[name], brief=brief)
        assert got.get("problem") == "", got


# ============================================================ 判据 1：真机那一条被拒

def test_the_real_machine_handoff_is_refused_and_writes_nothing(tmp_path: pathlib.Path):
    """真机那一条（`handoff(to=ALL)` + 正文里两件派活）⇒ 秘书拒，盘上 0 条手稿。

    改前必红：秘书照发 —— `projects/mp3-r3/manuscripts/handoffs.jsonl` 的 000000 就是那么
    落盘的，`to=ALL` 而正文里写着给 A 与给 D 两件活。

    拒信必须逐字给出拆分方案（"给 A 一条、给 D 一条"），理由码是既有的 `invalid_params`
    （"这次调用本身不成立"）—— 这一版不新造理由码。
    """
    st, cond, reg, ws, me, kids = _tree(tmp_path)
    loop = _loop(cond, reg, ws, st, [
        {"handoff": {"to": "ALL", "summary": REAL_SUMMARY, "body": REAL_BODY}},
        {"final": "知道了"},
    ])
    _register(loop, me, kids)
    run = loop.run("派活", summoned_by="M", my_task_id=me, depth=2)
    step = run.steps[0]
    assert step.shape == "handoff", step.to_dict()
    res = step.result

    assert res.get("ok") is False, res
    assert res.get("outcome") == "refused", res
    assert res.get("refused") == "invalid_params", res
    assert res.get("refusal_reason") == "invalid_params", res
    # 盘上 0 条：手稿一行没写（"这一条没发出去"必须是盘上的事实，不是一句声明）
    assert MS.rows(ws) == [], ("被拒的那一条不许留手稿：", MS.rows(ws))

    err = str(res.get("error") or "")
    assert "这一条里有 2 件派活" in err, err
    assert "给 A" in err and "给 D" in err, err
    assert "拆成 2 条" in err, err
    assert "`handoff(to=A)`" in err and "`handoff(to=D)`" in err, err

    # ---- 秘书台账（"未向 M 提醒"那一半的既有回流）：那一行带着它的判断与理由。
    rows = [r for r in loop.secretary.decisions()
            if (r.get("judge") or {}).get("targets") or "拆成" in str(r.get("reason") or "")]
    assert rows, ("秘书发出口没有留下判断：", loop.secretary.decisions())
    last = rows[-1]
    assert last.get("decision") == "建议重排", last
    assert last.get("judge", {}).get("fits") is False, last
    assert list(last["judge"].get("targets") or []) == ["A", "D"], last
    assert "拆成 2 条" in str(last.get("reason") or ""), last


# ============================================================ 判据 1b：公告栏里点名下指令

def test_a_directive_in_the_bulletin_is_refused_on_the_handoff_path(tmp_path: pathlib.Path):
    """`handoff(to=ALL)` 里点名某个名册成员并下指令 ⇒ 拒 `public_is_not_a_conversation` + 0 条。

    这一档原先只在 `message` 那条路上有（`_message_by_channel` 的投递闸）；`handoff` 写的是
    同一份内容、进的是同一个公共频道，却不过那道判据 —— 同一件事换个通道就绕过去了。
    现在两条通道共用同一份判据（`_public_face_refusal`：码与措辞都只有一处），
    这一条量的是 handoff 这一侧真的接上了它。
    """
    st, cond, reg, ws, me, kids = _tree(tmp_path)
    loop = _loop(cond, reg, ws, st, [
        {"handoff": {"to": "ALL", "summary": "安排",
                     "body": "A1 请立刻把实验跑完，然后把结果回我"}},
        {"final": "知道了"},
    ])
    _register(loop, me, kids)
    run = loop.run("公告", summoned_by="M", my_task_id=me, depth=2)
    res = run.steps[0].result
    assert res.get("ok") is False, res
    assert res.get("refused") == "public_is_not_a_conversation", res
    assert res.get("named") == "A1", res
    assert "公告栏" in str(res.get("error") or ""), res.get("error")
    assert MS.rows(ws) == [], ("被拒的那一条不许留手稿：", MS.rows(ws))
    assert loop.secretary.decisions()[-1].get("decision") == "建议改派", loop.secretary.decisions()


# ============================================================ 判据 2：单收件人照发（正控）

def test_one_dispatch_to_one_recipient_still_goes_out(tmp_path: pathlib.Path):
    """正控：单收件人的派活 ⇒ 照发（手稿真的写进去），同一件事写两遍也不算两件。

    为什么这条必须有：收紧"一份稿子几件活"最容易顺手把正常的派活一起堵死 ——
    而"一条 `handoff(to=A)` 里只有给 A 的活"是这条通道上最常见的形态。
    """
    members = [{"kind": "child", "name": name, "task_id": kids, "role": role}
               for (name, role, _b), kids in zip(ROSTER, ("t-a", "t-d"))]
    # 同一件事写两遍（名册名一次、角色代号一次）⇒ 仍然只有一个派活对象。
    twice = SEC.dispatch_targets("派活：A1（检索这两个英文主题的文献）。再说一遍：派活：A（检索文献）。",
                                 members)
    assert len(twice) == 1, ("同一件事写了两遍被数成两件派活：", twice)

    st, cond, reg, ws, me, kids_ = _tree(tmp_path)
    loop = _loop(cond, reg, ws, st, [
        {"handoff": {"to": "A", "summary": "派活：A1（检索这两个英文主题的文献）",
                     "body": "派活：A1（检索这两个英文主题的文献，逐条报 outcome 与 "
                             "result_lit_ids）。"}},
        {"final": "派完了"},
    ])
    _register(loop, me, kids_)
    run = loop.run("派活", summoned_by="M", my_task_id=me, depth=2)
    res = run.steps[0].result
    assert res.get("ok") is True, res
    rows = MS.rows(ws)
    assert len(rows) == 1, rows
    assert rows[0]["to"] == "A", rows[0]


# ============================================================ 判据 3：真公告照发（正控）

def test_a_real_bulletin_still_goes_out(tmp_path: pathlib.Path):
    """正控：`to=ALL`、不点名、不带指令语气的公告 ⇒ 照发（别把公告也堵死）。

    "公告"与"对话"的分界就是 `message` 那条路一直在用的同一份判据
    （点名 + 指令语气才拒）；这里量的是：同一份判据在 `handoff` 上也不误伤公告。
    """
    st, cond, reg, ws, me, kids = _tree(tmp_path)
    loop = _loop(cond, reg, ws, st, [
        {"handoff": {"to": "ALL", "summary": "这一轮我改了计划，知悉",
                     "body": "这一轮我改了计划，知悉。原来的第二轮并到下一轮一起做，"
                             "具体等实验读数回来再动。"}},
        {"final": "说完了"},
    ])
    _register(loop, me, kids)
    run = loop.run("公告", summoned_by="M", my_task_id=me, depth=2)
    res = run.steps[0].result
    assert res.get("ok") is True, res
    rows = MS.rows(ws)
    assert len(rows) == 1 and rows[0]["to"] == MS.ALL, rows


# ============================================================ 判据 4：反真空

def test_the_content_face_check_is_not_vacuous(tmp_path: pathlib.Path,
                                               monkeypatch: Any):
    """反真空：把秘书那一处判断打桩成恒放行 ⇒ 判据 1 当场红。

    打的是 `Secretary.judge_recipient_face`（秘书发出口那一处判断的唯一入口）：
    它恒返回"相符"之后，真机那一条会照发、盘上会多一行 —— 那正是改前的形态。
    所以判据 1 量的确实是这一处判断，不是别的东西。
    """
    monkeypatch.setattr(SEC.Secretary, "judge_recipient_face",
                        lambda self, shape, payload, *, face=None: {
                            "checked": True, "fits": True, "refused": "",
                            "refusal_reason": "", "reason": "打桩：恒放行",
                            "targets": [], "named": "", "shape": shape, "to": "",
                            "decision": ""})
    st, cond, reg, ws, me, kids = _tree(tmp_path)
    loop = _loop(cond, reg, ws, st, [
        {"handoff": {"to": "ALL", "summary": REAL_SUMMARY, "body": REAL_BODY}},
        {"final": "知道了"},
    ])
    _register(loop, me, kids)
    run = loop.run("派活", summoned_by="M", my_task_id=me, depth=2)
    res = run.steps[0].result
    assert res.get("ok") is True, ("坏实现应当把这一条发出去：", res)
    assert len(MS.rows(ws)) == 1, ("坏实现下盘上必须多一行 —— 否则判据 1 不是在测这一处判断：",
                                   MS.rows(ws))

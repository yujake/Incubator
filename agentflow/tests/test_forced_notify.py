# -*- coding: utf-8 -*-
"""强制 `notify` 表（`draft/39` §3.2/§3.3，用户 2026-10-05 裁）—— 这也是 E4 演练。

用户口径（逐字）：

> 由于每个除主控外的 Agent 干完活后都会有明确的"把成果通知给谁"的步骤作为结束，我们就让它每次
> 要结束时强制填一个参数表，说明它要通知谁，通知什么信息，然后在知道这些后用脚本生成这个交接
> 文件，并同样用脚本把这个交接文件信息发给目标 Agent，即 Agent 互相之间的通信通过脚本强制留痕
> 并代为转发。
> ……若 Agent 不会填参数表，但凡填错格式就打回充填再发一条带有对格式详细说明的警告给 Agent 看。
> ……连续打回两次接收方也要反思自己的问题。

E4 的三条演练（本文件逐条落地）：

| # | 场景 | 期望 |
|---|---|---|
| 1 | 收工带 `notify` | 账本多一行、编号 0000、收件人留言里带 `[手稿 0000]` |
| 2 | 收工不带 `notify` | 打回重填（不是代填）：这一步是 `invalid`，警告里有四件事；连续 3 次 ⇒ `no_notify` |
| 3 | 收工带错字段 | 打回并点名那个字段；连续两次的警告里多一句"先说明你上一次为什么没按格式填" |

## 2026-10-26（D-68）：主控的 `final` 现在要过结构完整性闸

业主逐字：「最终 final 时应该是 M 下整棵树都已销号，否则不记 final」。于是本文件里
凡是"主控派完活 ⇒ final"的判据都两向都测：

| 方向 | 脚本 | 期望 |
|---|---|---|
| 不做（树没清就收工） | 派活之后直接 `final` | 不记 final（`final_refused`），拒信点名还在册的编号与处置路径 |
| 做了（先销号再收工） | 派活 → `conductor.retire_child` → `final` | 记 final，留痕照旧 |

Q12 之后被拒还有三个补救拍（`AgentLoop.max_final_refused`），所以"不记 final"那一向
读到的是停止理由 `final_refused` —— 它绝不是成功：`run.final` 是空串、没有手稿，
收尾那句还要点名"补救了 N 拍仍不完整"。

夹具里那一支没有未消项（D-68 起派活通知不落收件人的板），所以这棵树是
"`conductor.retire_child` 一销就清"；`conductor.ack` 那条路在没有未消项时没有对象。
"""
from __future__ import annotations

import json
from typing import Any

from agentflow import schema as S
from agentflow import manuscripts as MS
from agentflow.agent_loop import (
    AgentLoop, LlmBackend, notify_shape_problem, read_messages, run_role,
)
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

#: `_run` 交给角色的那件事名：脚本靠它认"这一步是主控还是子代理"。
M_TASK = "收工演练"


class _Scripted:
    """一份"会照着 replies 说"的假模型（每一步一句 JSON）。

    `replies` 的项可以是 dict（按序号取，取完就停在最后一项），也可以是
    `(prompt, store) -> dict` 的函数。为什么要把这一档留出来：派活会把子代理也叫起来，
    而它用的是同一个替身网关 —— 主控与子代理的每一步混在同一条流里，按序号喂一定会
    喂错人（实测：主控第 2 步想让它销号，那条 JSON 被喂给了子代理那一趟）。
    """

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.prompts: list[str] = []
        #: `_run` 填进来：脚本要按盘上的台账决定下一步（销干净才收工）。
        self.store: Store | None = None

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        got = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        if callable(got):
            got = got(prompt, self.store)
        return type("Reply", (), {"ok": True, "text": json.dumps(got, ensure_ascii=False),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _retire_then_final(dispatch: dict[str, Any], final: dict[str, Any], *,
                       retire: bool = True) -> list[Any]:
    """脚本：先派活，再把名下的子代理逐个销号，销干净才发 `final`（D-68 的两向）。

    `retire=True` 是"先销号再收工"（应记 final），`retire=False` 是"树没清就收工"
    （应被拒并点名）。两向共用同一份派活与同一句 final，差别只在那一只手上 ——
    否则"被拒"那一向证不了"拒的是收工这件事"，它可能只是脚本写错了。

    为什么不是一份逐步写死的列表：见 `_Scripted` 的 docstring（子代理与主控共用这个网关）。
    销号按台账里的绝对编号点（`task_id` 是 `conductor.retire_child` 收的兼容写法）：
    名册名要另读一份文件，而这一趟只有一个父，编号就在 `tasks` 那一行上。
    """
    named: list[str] = []

    def _step(prompt: str, store: Store | None) -> dict[str, Any]:
        if not prompt.startswith(f"你的任务：{M_TASK}"):
            # 子代理那一趟：它自己收工（D-68 管的是主控名下那一棵树，不是它）。
            return {"final": "子代理：这一趟的活做完了"}
        rows = [dict(r) for r in (store.rows("tasks") if store is not None else [])]
        agents = [r for r in rows if not str(r.get("kind") or "")]
        mine = next((r for r in agents if not str(r.get("parent_task_id") or "")), None)
        kids = ([] if mine is None else
                [r for r in agents
                 if str(r.get("parent_task_id") or "") == str(mine.get("task_id"))])
        if not kids:
            return dict(dispatch)                      # 第一步：派活（此刻名下还没有子）
        pending = [k for k in kids if str(k.get("task_id")) not in named]
        if retire and pending:
            task_id = str(pending[0].get("task_id"))
            named.append(task_id)
            return {"tool": "conductor.retire_child",
                    "args": {"task_id": task_id, "reason": "板清了，收工前销号"},
                    "why": "收工前把名下已经落定的子代理逐个销号（结构完整性闸）"}
        return dict(final)

    return [_step]


def _run(tmp_path, replies, *, role: str = "D", max_steps: int = 6,
         task: str = M_TASK):
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    gw = _Scripted(replies)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=ws,
                         seam_factory=lambda r: LlmSeam(role=r, session_root=ws, gateway=gw,
                                                        price=(0.0, 0.0), sid="n1"),
                         max_steps=max_steps, store=st, sid="n1")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    gw.store = st
    reg = build_registry(store=st, conductor=cond).registry
    backend.registry = reg
    run = run_role(role, task, store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role=role, session_root=ws, gateway=gw, price=(0.0, 0.0), sid="n1"),
                   session_root=ws, workspace_root=str(ws), sid="n1",
                   max_steps=max_steps, from_env=False)
    return ws, run


# ============================================================ 演练 1：带 notify ⇒ 留痕 + 转发

def test_e4_1_a_final_with_notify_writes_the_handoff_and_forwards_it(tmp_path):
    ws, run = _run(tmp_path, [
        {"final": "本轮把 X 推到了 Y",
         "notify": {"to": "F", "summary": "交给 F：X 的族构造证据",
                    "body": "## 我做了什么\n扫了 n≤12。\n## 依据\nexp:0002\n## 要你做什么\n"
                            "判定 n=14。\n## 我卡在哪\n界推不动。",
                    "refs": []}},
    ])
    assert run.stop_reason == "final", run.to_dict()
    assert run.notify_rejections == 0, run.to_dict()
    assert run.handoffs == [S.format_id(0)], run.to_dict()
    rows = MS.rows(ws)
    assert [r["id"] for r in rows] == [S.format_id(0)], rows
    assert rows[0]["to"] == "F" and rows[0]["summary"] == "交给 F：X 的族构造证据", rows[0]
    # 脚本代为转发：收件人收件箱里有那条带编号 + 一句话的留言
    msgs, problems = read_messages(ws, "F", sid="n1")
    assert not problems, problems
    body = "\n".join(str(m.get("body") or "") for m in msgs)
    assert f"[手稿 {S.format_id(0)}]" in body and "交给 F：X 的族构造证据" in body, msgs
    # 读数落在这一趟的记录里（谁交给了谁、哪一份）
    assert run.steps[-1].result.get("notify_handoff", {}).get("id") == S.format_id(0), run.steps[-1]


def test_the_conductor_is_exempt_because_its_final_goes_to_the_user(tmp_path):
    """边界：主控 M 的 `final` 是给用户的回复 ⇒ 免填（用户原话"向用户回复不搞这种操作"）。"""
    ws, run = _run(tmp_path, [{"final": "给用户的汇报：本轮做完三件事"}], role="M")
    assert run.stop_reason == "final", run.to_dict()
    assert run.notify_rejections == 0 and run.handoffs == [], run.to_dict()
    assert MS.rows(ws) == [], MS.rows(ws)


# ============================================================ 演练 2：不带 notify ⇒ 只留读数


def test_e4_2_a_final_without_notify_just_has_no_handoff(tmp_path):
    """L-05e 的新口径：不带 `notify` ⇒ 不打回，这一趟照常收工、只是没有手稿。

    改前必红：旧实现把这一步记成 `shape="invalid"`、打回重填（`notify_rejections=1`），
    再把下一条回复喂进来。现在 `final` 就是收工（一步结束），没填就没有手稿，
    而"为什么没有"如实落进这一步的读数。

    裁定（`draft/52` F 组 / P-10）只留一条："要交接就写手稿"。
    真机依据：5269 个 `agent_step` 里 shape 无 `final`、`no_notify` 收场 0 次
    ⇒ 那道闸门一次都没触发过。
    """
    ws, run = _run(tmp_path, [{"final": "我做完了"}])
    assert run.stop_reason == "final", run.to_dict()
    assert run.notify_rejections == 0, run.to_dict()
    assert [s.shape for s in run.steps] == ["final"], [s.shape for s in run.steps]
    assert run.steps[0].result.get("notify_problem"), run.steps[0].to_dict()
    assert run.steps[0].result.get("notify_handoff") is None, run.steps[0].to_dict()
    assert MS.rows(ws) == [], "没填就没有手稿（不代填）"
    assert "我做完了" in run.final, run.final
    # 填了就由本角色的秘书执笔一行（写权已移交；`sender` 仍是被服务的角色）
    ws2, run2 = _run(tmp_path / "b", [{"final": "我做完了",
                                       "notify": {"to": "D", "summary": "交给 D",
                                                  "body": "正文"}}])
    assert run2.stop_reason == "final" and run2.handoffs == [S.format_id(0)], run2.to_dict()
    assert MS.rows(ws2)[0]["sender"] == "D", MS.rows(ws2)


def test_a_run_that_never_fills_notify_still_finishes(tmp_path):
    """`no_notify` 这个停止理由在 L-05e 之后不可达：第一次 `final` 就收工。

    改前必红：`stop_reason == "no_notify"`、`notify_rejections == 3`、
    `run.steps` 是 3 个 `invalid`。改后：一步收工，账本 0 行（没填就是没交接，如实），
    结论照原样留着。
    """
    ws, run = _run(tmp_path, [{"final": "我第一次收工"}, {"final": "我第二次收工"}])
    assert run.stop_reason == "final", run.to_dict()
    assert run.notify_rejections == 0, run.to_dict()
    assert MS.rows(ws) == [], "不代填：账本里一份都不许凭空出现"
    assert "我第一次收工" in run.final, run.final
    assert [s.shape for s in run.steps] == ["final"], [s.shape for s in run.steps]
    assert "没有留下交接手稿" not in run.final, run.final


def test_the_missing_notify_is_visible_in_the_run_record(tmp_path):
    """读数可见（闸门降级成读数之后，这件事仍然要看得见）。"""
    _ws, run = _run(tmp_path, [{"final": "没填"}])
    assert run.notify_rejections == 0, run.to_dict()
    assert run.to_dict()["notify_rejections"] == 0, run.to_dict()
    assert run.steps[0].result.get("notify_problem"), run.steps[0].to_dict()
    assert any("没有交接手稿" in n for n in run.notes), run.notes
    assert run.handoffs == [], run.to_dict()


# ============================================================ 演练 3：带错字段 ⇒ 点名（读数）


def test_e4_3_a_wrong_field_is_named_in_the_reading(tmp_path):
    """带错字段：点名那个字段，但不打回（`final` 照样收工，账本不留半成品）。

    改前必红：两步都被记成 `invalid` 且警告里带"四件事"的模板。
    改后：形状问题落进 `result.notify_problem`（点名 `notify.summary` / `notify.to`），
    这一步仍是 `final`；账本 0 行（形状不对就没手稿）。
    """
    ws, run = _run(tmp_path, [{"final": "做完了",
                               "notify": {"to": "D", "body": "缺 summary"}}])
    first = run.steps[0].result.get("notify_problem") or ""
    assert "notify.summary" in first, first
    assert run.steps[0].shape == "final", run.steps[0].to_dict()
    assert run.stop_reason == "final" and MS.rows(ws) == [], (run.to_dict(), MS.rows(ws))
    # 坏收件人是另一条独立的读法（各跑一趟，因为 `final` 一步就结束）
    ws2, run2 = _run(tmp_path / "b", [{"final": "做完了",
                                       "notify": {"to": "Z", "summary": "s", "body": "b"}}])
    second = run2.steps[0].result.get("notify_problem") or ""
    assert "notify.to" in second, second
    assert MS.rows(ws2) == [], MS.rows(ws2)


def test_an_unknown_field_in_notify_is_named():
    """拼错的字段要当场点名（静默忽略会让它与"没填"长得一样）。"""
    problem = notify_shape_problem({"to": "D", "summry": "拼错了", "body": "b"})
    assert "不认识的字段" in problem and "summry" in problem, problem


def test_a_dangling_ref_is_named_and_no_half_written_row_lands(tmp_path):
    """`refs` 悬空 ⇒ 点名（写入期同一份判据），账本不许留下半成品。

    D10 之后 `manuscripts.write` 不再因悬空引用拒写，但这一层仍然不进账本：
    `notify.refs` 是"这一行手稿的依据"，依据立不住时这一行由框架派生那一份顶上
    （它只写框架手上已有的事实），而不是把一条带悬空引用的行塞进交接账本。
    """
    ws, run = _run(tmp_path, [{"final": "做完了",
                               "notify": {"to": "D", "summary": "引了 0009", "body": "b",
                                          "refs": ["0009"]}}])
    assert any("0009" in n or "悬空" in n for n in run.notes), run.notes
    # 收工侧的悬空 refs ⇒ 没有手稿（读数里点名），而不是把带悬空引用的行塞进账本
    assert MS.rows(ws) == [], MS.rows(ws)
    assert run.steps[0].result.get("notify_problem"), run.steps[0].to_dict()


def test_the_shape_decoder_passes_notify_through_and_the_gate_validates_it():
    """解码层只认形状（`final` 认出来了就把 notify 原样带过）；校验在 `notify_reading` 一处。

    为什么校验不放解码层：打回要附"四件事"的警告，而警告只在"被打回"这个上下文里生成
    （它需要角色与"连续第几次"）。两份措辞必然分家 —— 分家之后模型看到的警告就取决于
    它是被哪一层拒的（同一个错误两种说法）。
    """
    from agentflow.agent_loop import _shape_of

    shape, payload, problem = _shape_of({
        "final": "结论", "evidence": ["exp:0002"],
        "notify": {"to": "all", "summary": "广播一句", "body": "正文", "refs": ["0000"]}})
    assert (shape, problem) == ("final", ""), (shape, problem)
    assert payload["notify"]["to"] == "all", payload          # 原样带过（归一在写入时做）
    from agentflow.agent_loop import clean_notify
    assert clean_notify(payload["notify"])["to"] == "ALL", clean_notify(payload["notify"])
    shape, _p, problem = _shape_of({"final": "结论", "notify": {"to": "D"}})
    assert (shape, problem) == ("final", ""), (shape, problem)  # 形状对（缺字段由闸门判）


def test_the_forced_table_is_retired_in_code_and_the_prompt_half_is_bs():
    """L-05e 的代码半（提示词半归 B）：判据只钉代码侧，不再钉提示词的措辞。

    改前必红：`AgentLoop.run` 里还调着 `_notify_bounce(` 且写着 `no_notify` —— 那是"收工不带 notify 就打回"的两处痕迹。

    这一条钉的是退场之后的契约：① 收工侧的打回没了（源码里不再调 `_notify_bounce`）；② `no_notify` 这个停止理由没了（不可达的停止理由留着只会误导读的人）；③
    读数还在（`notify_problem`）：退场 ≠ 沉默 —— 有没有留痕仍然看得见（这是"闸门降级成读数"的全部意义）。

    为什么不在这里断言 `agent_prompts.LOOP_PROTOCOL` 的文字：那是 B 的广告面，而 `draft/45 §2` 的硬约束是"代码先接住、提示词后撤" ——
    若继续钉提示词的"强制/不代填"，
    B 撤广告的那一刻这里会红，而红的原因是分工不是回归。"""
    import inspect

    from agentflow.agent_loop import AgentLoop

    src = inspect.getsource(AgentLoop.run)
    # 只看代码行：注释里解释"为什么退了"是应该的（判据要判的是行为，
    # 不是"这两句话能不能被提到"）。
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "_notify_bounce(" not in code, "收工侧还在打回（L-05e 的代码半没落）"
    assert "no_notify" not in code, "`no_notify` 这个停止理由还在（退场不彻底）"
    assert "notify_problem" in code, "读数那一格不见了（退场 ≠ 沉默）"
    assert AgentLoop.max_notify_rejections == 3, "常量仍在（退场的是它的**用法**）"


# ============================================================ 主控派活侧（draft/39 §6.4 四.1）

def _ws_rows(ws, table: str) -> list[dict]:
    """读工作区里某张台账表的行（"派活有没有真的发生"看这张表最准）。"""
    import pathlib as _pathlib

    p = _pathlib.Path(ws) / "data" / f"{table}.json"
    if not p.is_file():
        return []
    return list(json.loads(p.read_text(encoding="utf-8")).get("rows") or [])


def test_the_conductor_must_leave_a_trail_when_it_dispatches(tmp_path):
    """M 派活必须留痕：`summon` 带 `notify` ⇒ 账本一行、收件人是被派的那个角色。

    `to` 缺省 = 被派的角色（"给谁派了活"与"手稿发给谁"不许因为要填两遍而分家）。

    D-68（业主 2026-10-26）之后这一条两向都测，因为"记 final"的门槛变了：

    - 树没清就收工：同一份脚本只把那只手关掉 ⇒ 不记 final（`stop_reason` 是
      `final_refused`、`run.final` 是空串），拒信点名还在册的编号与处置路径。
      改前这一向读到的是 `final` —— 现在它读到拒绝，而且是点名的那种拒绝；
    - 先销号再收工：派完活用 `conductor.retire_child` 把那棵树清掉再 final ⇒ 记 final，
      留痕（账本一行 + 收件箱 + 这一步的读数）一处不少。

    两向共用同一份派活与同一句 final：差别只在"有没有销号"，于是"被拒"证得了
    "拒的是收工那件事"，而不是"脚本写错了"。
    """
    dispatch = {"summon": {"role": "D", "task": "派活：把这条猜想立起来并登记",
                           "params": {"statement": "n≥3 时……", "testable": "n≤12 枚举"},
                           "why": "把猜想立起来",
                           "notify": {"summary": "派 D 登记这条猜想",
                                      "body": "## 派什么活\n登记猜想。\n## 依据\nlit:0000\n"}}}
    final = {"final": "派完了"}

    # ---- 不做：树没清就 final ⇒ 不记 final（这不是成功，下面是把它钉成拒绝的四处读数）
    cap = int(AgentLoop.max_final_refused)
    refused_ws, refused_run = _run(tmp_path / "refused",
                                   _retire_then_final(dispatch, final, retire=False),
                                   role="M", max_steps=cap + 3)
    assert refused_run.stop_reason == "final_refused", refused_run.to_dict()
    assert refused_run.final == "", refused_run.to_dict()
    assert refused_run.final_refused_beats == cap, refused_run.to_dict()
    why = "\n".join(str(n) for n in refused_run.notes)
    kids = [str(r.get("task_id")) for r in _ws_rows(refused_ws, "tasks")
            if str(r.get("parent_task_id") or "") and not str(r.get("kind") or "")]
    assert kids and all(k in why for k in kids), (kids, refused_run.notes)
    assert "还没销号" in why and "conductor.retire_child" in why, refused_run.notes
    assert "不记 final" in why, refused_run.notes
    # 被拒的那几步真的带着拒信（不是"没记 final 但什么都没说"）：
    # 补救窗口是 cap 拍，加上最后那一拍收尾 ⇒ 一共 cap + 1 次被拒的 final。
    assert [s.shape for s in refused_run.steps] == ["summon"] + ["final"] * (cap + 1), \
        [s.shape for s in refused_run.steps]
    assert all("final_refused" in (s.result or {}) for s in refused_run.steps[1:]), \
        [s.result for s in refused_run.steps[1:]]
    # 派活那一刻的留痕不受这道闸影响（它管的是收工，不是派活与手稿）
    assert [r["to"] for r in MS.rows(refused_ws)] == ["D"], MS.rows(refused_ws)
    assert refused_run.handoffs == [S.format_id(0)], refused_run.to_dict()

    # ---- 做了：先销号再 final ⇒ 照常收工，留痕在三处都在
    ws, run = _run(tmp_path / "retired", _retire_then_final(dispatch, final), role="M")
    assert run.stop_reason == "final", run.to_dict()
    assert run.final == "派完了", run.final
    assert run.final_refused_beats == 0, run.to_dict()
    assert run.notify_rejections == 0, run.to_dict()
    assert run.handoffs == [S.format_id(0)], run.to_dict()
    rows = MS.rows(ws)
    assert rows[0]["to"] == "D", rows[0]
    assert "登记这条猜想" in rows[0]["summary"], rows[0]
    assert run.steps[0].result.get("dispatch_handoff", {}).get("ok") is True, run.steps[0]
    # 销号真的发生过（不是只在 final 里说了一句）：那一步的形状是工具、结果是 retired
    assert [s.shape for s in run.steps] == ["summon", "tool", "final"], \
        [s.shape for s in run.steps]
    assert run.steps[1].payload.get("name") == "conductor.retire_child", run.steps[1].payload
    assert run.steps[1].result.get("ok") is True, run.steps[1].result
    assert (run.steps[1].result.get("data") or {}).get("state") == "retired", \
        run.steps[1].result


def test_a_dispatch_without_notify_still_leaves_a_framework_derived_row(tmp_path):
    """没填 `notify` 的派活：框架据派活本身派生一行留痕（派活照常发生）。

    为什么这里不打回、收工侧却打回：用户要的是"派活强制留痕" —— 派生比"打回三次、
    什么都不留"更接近那个目标；而派生行写的是框架手上已有的事实（谁派了谁做什么、参数、
    为什么），不是替模型编它想说的话。收工侧仍然是"打回重填、不代填"（用户在那里的原话）。

    D-68 之后收工那一步要先销号（见 `_retire_then_final`）：`final_refused_beats == 0`
    在这一条里是反真空的一格 —— 树没清的话它会等于 `AgentLoop.max_final_refused`，
    收工也就不是 final 了。
    """
    ws, run = _run(tmp_path, _retire_then_final(
        {"summon": {"role": "D", "task": "派活：把这条猜想立起来并登记",
                    "params": {"statement": "n≥3 时……", "testable": "n≤12 枚举"},
                    "why": "把猜想立起来"}},
        {"final": "派完了"}), role="M")
    assert run.stop_reason == "final", run.to_dict()
    assert run.final_refused_beats == 0, run.to_dict()
    assert run.notify_rejections == 0, ("派生不是打回", run.to_dict())
    rows = MS.rows(ws)
    assert [r["to"] for r in rows] == ["D"], rows
    assert "框架据派活派生" in rows[0]["note"], rows[0]
    # 2026-10-16（口径 S2）：派生手稿的"一句话"现在是那件活（"派活：…"），
    # 不再是动作名（派活不带动作）。
    assert "派活" in rows[0]["summary"] and "猜想" in rows[0]["summary"], rows[0]
    assert "n≥3 时" in rows[0]["body"] and "把猜想立起来" in rows[0]["body"], rows[0]
    # 派活本身照常发生
    # 同上：按角色数那一行（`action` 那格现在恒为 `""`）。
    #
    # 2026-10-21：这里只数派活那一行，`action == "message"` 的行要摘掉 ——
    # 它 2026-10-19 起是该有的：`_handoff_address` 把 `to="D"` 解析成名册上的
    # 那个子实例（`how="child"`）之后，`_do_handoff` 的通知那一半走
    # `_message_to_member` ⇒ `open_item(kind="message", action="message")` 在那个实例
    # 名下开一条 ack 板项（实测：`t-000004`，`parent_task_id=t-000002`，
    # `detail="手稿 000000：…"`，`dispatch_handoff.notified == "t-000004"`）。
    # 它是通知（同一件事的第二半），不是第二次派活；判据要的"派活只发生一次"
    # 由派活那一行（`action=""`、`parent_task_id` = 本趟那一行）回答。
    # 同一口径的先例：`tests/test_the_wash_is_proposed_not_applied.py` 里
    # "受控拒绝/请示没有派活"那一条也是按 `action != "message"` 数的。
    assert len([r for r in _ws_rows(ws, "tasks")
                if str(r.get("role")) == "D"
                and str(r.get("action") or "") != "message"]) == 1, \
        _ws_rows(ws, "tasks")
    assert run.steps[0].result.get("dispatch_handoff", {}).get("ok") is True, run.steps[0]


def test_a_malformed_dispatch_notify_still_dispatches_and_falls_back(tmp_path):
    """填错 ⇒ 照常派活，留痕退回框架派生那一份（L-05e 之后不再打回）。

    改前必红：这一步是 `shape="invalid"`、`tasks` 里 0 行（那一次派活没发生）、
    `MS.rows(ws)[0]["summary"] == "补上留痕再派"`（第二次才成）。
    改后：派活真的发生（`tasks` 1 行），手稿来自框架据派活派生（note 里写明），
    形状问题落进 `run.notes` —— 而"谁是派生、谁是执笔"两个标记仍然分得开。

    步骤序列里多出来的那一步是 D-68 的销号（`"tool"`）：收工之前那棵树要清掉，
    而"派活 → 销号 → 收工"三步各是各的证据，不许并成一步。
    """
    ws, run = _run(tmp_path, _retire_then_final(
        {"summon": {"role": "D", "task": "派活：把这条猜想立起来并登记",
                    "params": {"statement": "n≥3 时……", "testable": "n≤12 枚举"},
                    "why": "把猜想立起来",
                    "notify": {"to": "D"}}},          # 缺 summary / body
        {"final": "派完了"}), role="M")
    assert [s.shape for s in run.steps] == ["summon", "tool", "final"], \
        [s.shape for s in run.steps]
    # 只数派活那一行：`action == "message"` 那一行是通知投到那个实例板上的 ack 项
    # （该有的第二半，理由与上一处逐字相同）。
    assert len([r for r in _ws_rows(ws, "tasks")
                if str(r.get("role")) == "D"
                and str(r.get("action") or "") != "message"]) == 1, _ws_rows(ws, "tasks")
    rows = MS.rows(ws)
    assert len(rows) == 1, rows
    assert "框架据派活派生" in rows[0]["note"], rows[0]["note"]
    assert "执笔" in rows[0]["note"] or "秘书" in rows[0]["note"], rows[0]["note"]
    assert any("notify" in n for n in run.notes), run.notes
    assert run.stop_reason == "final", run.to_dict()
    assert run.final_refused_beats == 0, run.to_dict()


def test_a_multi_target_dispatch_defaults_the_handoff_to_the_public_channel(tmp_path):
    """`summon_many` 一波算一次派活、写一行；`to` 缺省 ⇒ `ALL`（多目标）。

    D-68 之后这一趟要两个子代理都销掉才收得了工：脚本按台账逐个销，
    所以"两步销号 + 一步收工"在这里同时是"整棵树都清过"的证据。
    """
    ws, run = _run(tmp_path, _retire_then_final(
        {"summon_many": {"targets": [
            {"role": "D", "task": "派活：把这条猜想立起来并登记",
             "params": {"statement": "甲", "testable": "n≤3"}, "instance": "a"},
            {"role": "E", "task": "派活：跑一次实验",
             "params": {"claim": "乙", "method": "numeric", "code": "print(1)"},
             "instance": "b"}],
            "why": "两条并行",
            "notify": {"summary": "派两条活", "body": "## 派什么活\n甲 + 乙。\n"}}},
        {"final": "派完了"}), role="M")
    assert run.stop_reason == "final", run.to_dict()
    assert run.final_refused_beats == 0, run.to_dict()
    retires = [s for s in run.steps if s.shape == "tool"]
    assert len(retires) == 2, [s.shape for s in run.steps]
    assert [s.shape for s in run.steps] == ["summon_many", "tool", "tool", "final"], \
        [s.shape for s in run.steps]
    rows = MS.rows(ws)
    assert len(rows) == 1, rows
    assert rows[0]["to"] == "ALL", rows[0]


def test_a_plain_role_does_not_need_a_notify_on_its_dispatches(tmp_path):
    """边界：非主控角色派活不要求 notify（它们只在收工那一刻留痕）。"""
    ws, run = _run(tmp_path, [
        {"summon": {"role": "E", "task": "派活：跑一次实验",
                    "params": {"claim": "甲", "method": "numeric", "code": "print(1)"},
                    "why": "算一遍"}},
        {"final": "算完了", "notify": {"to": "M", "summary": "收工", "body": "完。"}},
    ], role="D")
    assert run.stop_reason == "final", run.to_dict()
    assert run.notify_rejections == 0, run.to_dict()
    assert run.steps[0].shape == "summon", run.steps[0].to_dict()
    assert "dispatch_handoff" not in run.steps[0].result, run.steps[0].result
    # 命题是"非主控派活不产生框架派生的留痕"（它只在收工那一刻留痕）。
    # 原来写成"手稿恰好只有一条、且 to == M"—— 那把手稿的条数也钉住了，
    # 而条数会随别的合理行为变（例如收工那条与派活那条的合并方式）。
    assert not any("框架据派活派生" in str(r.get("note") or "") for r in MS.rows(ws)), MS.rows(ws)


# ============================================================ 动作驱动的一趟也留痕（§6.6 F1）

class _Stub:
    """一个最小的角色替身：只实现被测的那个读动作。"""

    def list_experiments(self, **_kw: Any) -> dict[str, Any]:
        return {"ok": True, "experiments": [], "note": "（替身）"}


def _action_ws(tmp_path):
    """造一个工作区 + 只接了 E 的 conductor（够跑一条动作驱动的召唤）。"""
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, backend=LocalBackend({"E": ("object", _Stub())}))
    return ws, st, cond


def _seed_task(cond, task_id: str, *, role: str = "E", status: str = "running") -> None:
    with cond.store.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {"task_id": task_id, "role": role, "action": "list_experiments",
                            "params": {}, "status": status, "outcome": None,
                            "called_by": "M", "depth": 1, "input_key": "k",
                            "started_at": "2026-10-05T00:00:00+08:00", "artifacts": []})


def test_a_finished_action_no_longer_gets_a_derived_handoff_row(tmp_path):
    """口径反转（`draft/39` §6.49 的 D64，用户 2026-10-06 裁）：动作驱动的一趟不代写交接。

    原来（`draft/39` §6.6 F1）框架会按动作结果派生一行，理由是"动作驱动的趟没有 final 可填"。
    真机把那个取舍证伪了：T1–T5 五趟的账本 92 / 96 / 118 / 62 / 94 行里 100% 是这种模板，
    `refs` 逐行全空、正文是"从/到/一句话/时间/引用"的填空 —— 用户原话
    「handoffs 里面没有几条有效信息全在强调纪律」。
    同样的事实已经在 `tasks` 与 `out/tasks/<id>.json` 里 ⇒ 交接账本只装模型自己写的、带编号的。
    """
    ws, _st, cond = _action_ws(tmp_path)
    res = cond.summon("E", "list_experiments", {}, by="M")
    assert res.outcome == "ok", (res.status, res.outcome, res.error)
    assert MS.rows(ws) == [], MS.rows(ws)
    # 事实没丢：任务行与产物仍在盘上（那才是这类信息的落点）
    assert any(a.endswith(f"{res.task_id}.json") for a in res.artifacts), res.artifacts


def test_an_action_that_refuses_after_starting_carries_the_reason_in_the_task_row(tmp_path):
    """跑起来之后被拒的动作：不写交接，但"为什么没成"要落在任务行上（不静默）。"""
    from agentflow.tools import ToolError

    class _Refuser(_Stub):
        def list_experiments(self, **_kw: Any) -> dict[str, Any]:
            raise ToolError("台账读不到（替身故意拒一次）")

    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, backend=LocalBackend({"E": ("object", _Refuser())}))
    res = cond.summon("E", "list_experiments", {}, by="M")
    assert res.outcome == "refused", (res.status, res.outcome, res.refusal_reason)
    assert MS.rows(ws) == [], MS.rows(ws)
    task = [r for r in st.rows("tasks") if str(r.get("task_id")) == res.task_id]
    assert task and str(res.refusal_reason) in json.dumps(task[0], ensure_ascii=False), task


def test_a_refusal_before_the_task_starts_leaves_no_row(tmp_path):
    """边界（三态）：开工前就被拒的召唤（`invalid_params`）没有"干完活"这回事 ⇒ 不留行。

    这一条与上一条的分界是"任务行有没有真的 `running` 过"：开工前的拒绝由 `_refuse` 直接写
    台账（不经过 `finish`），而"我干完了/我试过了"这句话在那时无话可说 ——
    派活侧那一行（M 的留痕）已经记下了"我派了这个活"，理由在 `tasks.refusal_reason` 上。
    """
    ws, _st, cond = _action_ws(tmp_path)
    res = cond.summon("E", "run_experiment", {"claim": "缺参数"}, by="M")
    assert res.outcome == "refused" and res.refusal_reason == "invalid_params", \
        (res.outcome, res.refusal_reason)
    assert MS.rows(ws) == [], MS.rows(ws)


def test_a_cancelled_task_leaves_no_completion_manuscript(tmp_path):
    """取消不算"干完活"：`cancelled` 的任务不许留一行"我交接了"。"""
    ws, _st, cond = _action_ws(tmp_path)
    _seed_task(cond, "t-9001")
    cond.finish("t-9001", status="cancelled", outcome="cancelled", detail="人叫停了")
    assert MS.rows(ws) == [], MS.rows(ws)


def test_the_roles_own_notify_row_is_the_only_row_now(tmp_path):
    """模型自己填的 `notify`（收工那一句）是唯一会进账本的那种行 —— 框架不再补、也不覆盖。"""
    ws, _st, cond = _action_ws(tmp_path)
    MS.write(ws, sender="E", recipient="M", summary="我自己写的收工交接", body="正文。\n",
             task_id="t-9002", note="留痕来源：模型填的 notify")
    _seed_task(cond, "t-9002")
    cond.finish("t-9002", status="done", outcome="ok", detail="执行完成")
    rows = MS.rows(ws)
    assert len(rows) == 1 and rows[0]["summary"] == "我自己写的收工交接", rows


def test_the_conductor_itself_never_gets_a_completion_row(tmp_path):
    """边界：主控自己的任务行不留"完成交接"（它的派活侧已经有另一套留痕）。"""
    ws, _st, cond = _action_ws(tmp_path)
    _seed_task(cond, "t-9003", role="M")
    cond.finish("t-9003", status="done", outcome="ok", detail="执行完成")
    assert MS.rows(ws) == [], MS.rows(ws)


def test_the_run_end_event_carries_the_handoff_readings(tmp_path):
    """E5 的 F3：`agent_run_end` 必须带 `handoffs` / `notify_rejections`（设计里点名的读数）。"""
    from agentflow import sessions as SS

    ws, run = _run(tmp_path, [
        {"final": "收工了", "notify": {"to": "M", "summary": "交给 M", "body": "正文。"}},
    ])
    assert run.handoffs == [S.format_id(0)], run.to_dict()
    events, problems = SS.read_session(ws, sid="n1")
    assert not problems, problems
    end = [e for e in events if e.get("kind") == "agent_run_end"]
    assert end, [e.get("kind") for e in events]
    assert end[-1].get("handoffs") == [S.format_id(0)], end[-1]
    assert end[-1].get("notify_rejections") == 0, end[-1]

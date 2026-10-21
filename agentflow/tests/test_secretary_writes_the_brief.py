# -*- coding: utf-8 -*-
"""两条业主裁定（2026-10-20）的判据：秘书代写简介 + 研究侧由 D 主导、M 只统筹搭桥。
## 裁定一逐字（业主）
> 「简介没写，则秘书帮忙写，秘书的重要职责就是辅助通讯」
改前的读数：`agent_loop.py` 把 `brief_arg` 直接传死，而 `Secretary.roster_add` 在 `brief`为空时拒绝登记（"没给一句任务简介"）—— 真机 100 次失败里 75 次是这一条。
所以现在：`brief` 缺失（空 / 纯空白）而 `task` 非空 ⇒ 秘书从任务原文派生一句（`secretary.brief_from_task`：确定性、不调模型、不花钱、≤60 字、单行），登记行里多一格`brief_source="secretary"`、返回值
`brief_written=True`；父给的那一句记`brief_source="parent"`、`brief_written=False` —— 不许静默冒充"父给的"。`brief` 与 `task` 都空 ⇒ 照旧拒收（不许编造）。
`agent_loop` 那两侧只把 `task` 传下去，刻意不写 `brief or task`：业主选的是"秘书写"，不是"拿任务原文顶替"。判据 ①b / ①c 守在 loop 那一层，正是为了钉住"代写发生在秘书那里、留痕也在那里"。
## 裁定二逐字（业主）
> 「F 和 E 都是 D 的研究侧直属，M 的职责是统筹协调，D 是真正主导研究……请加强 D 侧
> 研究的积极性，压低 M 自主操纵研究的积极性，M 的重要职责是规划方案以及在特殊情况
> 作为代理间的桥梁」
两处都只是提示词文本（不加减任何边）：`specs/d.py` 加一条"你主导研究"，`specs/m.py` 把"自己下场操纵研究"的措辞压下去（并确保 `policy[20]/[21]` 那两条"派 V"的义务已改成"派 D 去办"）。
## 判据（五条，每条都带负控）
① 不给 `brief`、给 `task` ⇒ 登记成功、`brief` 是秘书派生的一句（≤60 字、无换行）、`brief_source=="secretary"`、返回 `brief_written=True`；负控：把代写关掉（派生函数恒返回 `""`）⇒
回到"没给一句任务简介"拒收。①b / ①c：`_do_summon` 与 `_do_summon_many` 这两条生产路走同一口径（代写 + 留痕）。② `brief` 与 `task` 都空 ⇒ 仍然拒收（不许编造）；负控：改成放行（派生函数恒返回一句）⇒ 判据必红。③
代写的 `brief` 不许超过 60 字或含换行（否则会撞上 `roster_add` 自己的内容闸，形成"没给简介 ⇒ 永远登记不上"的死角）；超长 `task` 必须读出被截断而不是被拒。负控：把截断关掉（派生函数原样返回）⇒ 同一调用被内容闸拒。④
`specs/d.py` 的 policy 里有"研究侧由你主导"＋ C/E/F/让 F 带 V 的列举，且那条 ≤90 字；负控：删掉 ⇒ 红。⑤ `specs/m.py` 的 policy 里有"不自己派 E 做实验"这类压低措辞，且不再出现"派 V /
`verify_proof`"这类义务句；负控：把那两句加回 ⇒ 红。
"""
from __future__ import annotations

import json
import pathlib
import re
from types import SimpleNamespace
from typing import Any

import pytest

from agentflow import secretary as SEC
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.specs import builtin_specs
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s-brief-by-secretary"
ROLE = "M"
CHILD = "E"

#: 一条"有第一句"的任务原文：第一句以 `。` 收尾 ⇒ 简介就是它（不含第二句）。
TASK_TWO_SENTENCES = "把 X 的族构造证据补齐。然后再看 Y 那一条。"


# ============================================================ 夹具

def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 + 一个父调用行 + 秘书（名册要真的写盘，所以用真 `Store`）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    sec = SEC.Secretary(ROLE, root=ws, store=st)
    owner = cond.open_top_level_run(ROLE, "父那一趟")
    return {"st": st, "ws": ws, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, parent: str, *, key: str) -> str:
    return cond._write_new_row({
        "task_id": "", "role": CHILD, "action": "run_once", "called_by": ROLE,
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": "done",
        "outcome": "ok", "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-20T10:00:00+08:00",
        "ended_at": "2026-10-20T10:05:00+08:00", "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="start:E.run_once")


def _adds(ws: pathlib.Path, owner: str) -> list[dict[str, Any]]:
    """盘上那一份名册的 `add` 行（读文件，不读视图 —— 判据要的就是"写没写进去"）。"""
    path = SEC.roster_path(ws, owner)
    if not path.is_file():
        return []
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if str(r.get("kind")) == "add"]


# ============================================================ ① 秘书代写 + 留痕

def _brief_written_by_secretary(got: dict[str, Any], rows: list[dict[str, Any]],
                                task: str) -> None:
    """判据①：登记成功、简介是秘书派生的一句、留痕记在登记行上、返回值说清了。"""
    assert got.get("problem") == "", got
    brief = str(got.get("brief") or "")
    assert got.get("brief_written") is True, (
        "返回值没给 `brief_written=True` ⇒ 调用方分不出「这句是秘书写的」还是「父给的」", got)
    assert brief, ("代写完 return 里要带那段文字", got)
    assert len(brief) <= SEC.BRIEF_MAX, (f"代写的简介 {len(brief)} 字，超过内容闸的 "
                                         f"{SEC.BRIEF_MAX} 字", brief)
    assert "\n" not in brief and "\r" not in brief, ("代写的简介必须是单行", brief)
    # 派生规则：取第一句（到第一个句末标点，含它）—— 这里逐字核一个可复算的样例
    assert brief == SEC.brief_from_task(task), (brief, SEC.brief_from_task(task))
    assert len(rows) == 1, ("该登记的那一条没落盘（或落了两条）", rows)
    row = rows[0]
    assert str(row.get("brief") or "") == brief, (row, brief)
    assert str(row.get("brief_source") or "") == "secretary", (
        "登记行没写 `brief_source=\"secretary\"` ⇒ 秘书代写的这件事在盘上读不出来"
        "（等于静默冒充父给的）", row)


def test_the_secretary_writes_the_brief_from_the_task(tmp_path: pathlib.Path):
    """① 正控：不给 `brief`、给 `task` ⇒ 登记成功，简介由秘书派生并留痕。

    细则：只取第一句（第二句 "然后再看 Y 那一条。" 不该进来），且单行。
    """
    env = _env(tmp_path)
    tid = _child(env["cond"], env["owner"], key="brief@a")
    got = env["sec"].roster_add(owner=env["owner"], role=CHILD, task_id=tid,
                                brief="", task=TASK_TWO_SENTENCES)
    _brief_written_by_secretary(got, _adds(env["ws"], env["owner"]), TASK_TWO_SENTENCES)
    assert got["brief"] == "把 X 的族构造证据补齐。", got["brief"]
    assert "然后再看" not in got["brief"], ("只取第一句：第二句不该进名册", got["brief"])
    # 视图里也读得到那一格（"谁写的"不必去翻盘上的 JSON）
    view = env["sec"].roster_view(owner=env["owner"])
    assert view["checked"] is True, view
    assert view["rows"][0]["brief_source"] == "secretary", view["rows"]


def test_the_parent_brief_is_still_recorded_as_the_parents(tmp_path: pathlib.Path):
    """① 另一半（反真空）：父给了简介 ⇒ 原话进名册、`brief_source="parent"`、不改一个字。"""
    env = _env(tmp_path)
    tid = _child(env["cond"], env["owner"], key="brief@b")
    got = env["sec"].roster_add(owner=env["owner"], role=CHILD, task_id=tid,
                                brief="父给的那一句", task=TASK_TWO_SENTENCES)
    assert got.get("problem") == "" and got["brief_written"] is False, got
    row = _adds(env["ws"], env["owner"])[0]
    assert row["brief"] == "父给的那一句" and row["brief_source"] == "parent", row


def test_negctl_turning_the_derivation_off_is_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """① 负控：把代写关掉（派生函数恒返回 `""`）⇒ 回到"没给一句任务简介"拒收。

    这就是改前那一版的形态：`brief` 空 ⇒ `roster_add` 当场拒，名册一行都没有。
    """
    env = _env(tmp_path)
    tid = _child(env["cond"], env["owner"], key="brief@c")
    monkeypatch.setattr(SEC, "brief_from_task", lambda *a, **k: "")
    got = env["sec"].roster_add(owner=env["owner"], role=CHILD, task_id=tid,
                                brief="", task=TASK_TWO_SENTENCES)
    assert got.get("problem") and "简介" in got["problem"], got
    assert got.get("brief_written") is False, got
    assert _adds(env["ws"], env["owner"]) == [], ("拒了就不许留半份", got)


# ============================================================ ② 都空 ⇒ 不许编

def _empty_both_is_refused(got: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """判据②：`brief` 与 `task` 都空 ⇒ 拒收（没有可派生的原料，秘书不许编）。"""
    assert str(got.get("problem") or ""), ("简介与任务都空却登记成功了 ⇒ 那句简介是编的", got)
    assert "简介" in str(got.get("problem") or ""), got
    assert rows == [], ("拒了就不许留半份", rows)


def test_no_brief_and_no_task_is_still_refused(tmp_path: pathlib.Path):
    """② 正控：`brief` 与 `task` 都空 ⇒ 仍然拒收（这一档刻意保留）。"""
    env = _env(tmp_path)
    tid = _child(env["cond"], env["owner"], key="brief@d")
    got = env["sec"].roster_add(owner=env["owner"], role=CHILD, task_id=tid,
                                brief="   ", task="  \n\t ")
    _empty_both_is_refused(got, _adds(env["ws"], env["owner"]))


def test_negctl_letting_it_through_is_red(tmp_path: pathlib.Path,
                                          monkeypatch: pytest.MonkeyPatch):
    """② 负控：改成放行（派生函数对着空任务也吐一句"编的"）⇒ 判据必红。"""
    env = _env(tmp_path)
    tid = _child(env["cond"], env["owner"], key="brief@e")
    monkeypatch.setattr(SEC, "brief_from_task", lambda *a, **k: "一句编出来的简介")
    got = env["sec"].roster_add(owner=env["owner"], role=CHILD, task_id=tid,
                               brief="", task="")
    with pytest.raises(AssertionError):
        _empty_both_is_refused(got, _adds(env["ws"], env["owner"]))
    # 收尾（负控的负控）：把派生函数换回来之后，同一条判据仍然成立（一行都不许再留）
    polluted = _adds(env["ws"], env["owner"])
    monkeypatch.undo()
    again = env["sec"].roster_add(owner=env["owner"], role=CHILD,
                                 task_id=_child(env["cond"], env["owner"], key="brief@e2"),
                                 brief="", task="")
    assert str(again.get("problem") or "") and "简介" in str(again.get("problem") or ""), again
    assert _adds(env["ws"], env["owner"]) == polluted, ("拒了就不许留半份", again)


# ============================================================ ③ 代写的内容闸：截断不是拒

#: 一条超长、多行的任务原文（= 必须被截断 + 折平的那一档）。
LONG_TASK = ("把第 7 节那个族构造的每一层都重算一遍：\n"
             "先按 girth 分档，再按度数分档，逐层核对界是否与文献里的写法一致，"
             "并把每层的结果登记成一条可复算的读数（含参数与命令）。")


def _clipped_not_refused(got: dict[str, Any], rows: list[dict[str, Any]],
                         task: str) -> None:
    """判据③：超长 `task` ⇒ 被截断（≤60、单行、是原文前缀），而不是被内容闸拒。"""
    assert got.get("problem") == "", ("代写没有截断 ⇒ 撞上内容闸被拒，于是「没给简介」变成"
                                      "「永远登记不上」（死角）", got)
    brief = str(got.get("brief") or "")
    flat = " ".join(task.split())
    assert len(brief) == SEC.BRIEF_MAX, (
        f"截断的长度应当是内容闸的上限 {SEC.BRIEF_MAX}，读到 {len(brief)} 字", brief)
    assert len(flat) > SEC.BRIEF_MAX, ("夹具前提：原文要比上限长", len(flat))
    assert flat.startswith(brief), ("截断只能从头截（不许改写原文）", brief, flat)
    assert "\n" not in brief and "\r" not in brief, ("折平之后不许留换行", brief)
    assert len(rows) == 1 and rows[0]["brief"] == brief, rows
    assert rows[0]["brief_source"] == "secretary", rows


def test_a_long_task_is_clipped_not_refused(tmp_path: pathlib.Path):
    """③ 正控：超长、多行的 `task` ⇒ 代写的简介被截到 60 字、折成一行、照常登记。"""
    env = _env(tmp_path)
    tid = _child(env["cond"], env["owner"], key="brief@f")
    got = env["sec"].roster_add(owner=env["owner"], role=CHILD, task_id=tid,
                                brief="", task=LONG_TASK)
    _clipped_not_refused(got, _adds(env["ws"], env["owner"]), LONG_TASK)


def test_negctl_without_the_clip_it_hits_the_content_gate(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """③ 负控：把截断/折平关掉（原样返回）⇒ 同一调用被内容闸拒（"死角"真的存在）。

    这一条证明"代写必须自己截到 60 字以内"不是格式洁癖：不截就登记不上，
    而"登记不上"与"没给简介"在读数上长得一模一样。
    """
    env = _env(tmp_path)
    tid = _child(env["cond"], env["owner"], key="brief@g")
    monkeypatch.setattr(SEC, "brief_from_task", lambda task, **k: str(task))
    got = env["sec"].roster_add(owner=env["owner"], role=CHILD, task_id=tid,
                                brief="", task=LONG_TASK)
    assert got.get("problem") and "60" in got["problem"], got
    assert _adds(env["ws"], env["owner"]) == [], got


# ============================================================ ①b / ①c 生产路：同一口径

class _Gate:
    """seam 的替身：这一组判据不碰模型。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        return type("Reply", (), {"ok": True, "text": "{}", "tool_calls": (),
                                  "tokens_in": 1, "tokens_out": 1,
                                  "error_detail": "", "error_kind": ""})()


def _loop(tmp_path: pathlib.Path) -> dict[str, Any]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run(ROLE, "顶层这一趟")
    loop = AgentLoop(role=ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=ROLE, session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.my_task_id = top
    assert loop.secretary is not None, "这一组判据要的是'名册在手上'那一档"
    return {"ws": ws, "cond": cond, "loop": loop, "me": top}


def test_summon_without_brief_is_registered_by_the_secretary(tmp_path: pathlib.Path,
                                                             monkeypatch: pytest.MonkeyPatch):
    """①b `_do_summon`：只给 `task`、不给 `brief` ⇒ 名册照样登记，简介由秘书代写。"""
    env = _loop(tmp_path)

    def _done(*a, **kw):
        return SimpleNamespace(ok=True, task_id="t-000009", status="done", outcome="ok",
                               refusal_reason="", detail="跑完了", children=[], payload={})

    monkeypatch.setattr(env["cond"], "summon", _done)
    out = env["loop"]._do_summon({"role": CHILD, "task": TASK_TWO_SENTENCES})
    assert out.get("ok") is True, out
    assert not out.get("roster_problem"), (
        "名册没登记上 ⇒ 那句话又被「没给简介」拒了", out)
    assert out.get("roster_name"), out
    _brief_written_by_secretary(
        {"problem": "", "brief": _adds(env["ws"], env["me"])[0]["brief"], "brief_written": True},
        _adds(env["ws"], env["me"]), TASK_TWO_SENTENCES)


def test_summon_many_without_brief_is_registered_by_the_secretary(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """①c `_do_summon_many`：一批里每一项都只给 `task` ⇒ 逐项由秘书代写（同一口径）。"""
    env = _loop(tmp_path)
    n = {"i": 0}

    def run_plan(calls, token=None):
        got = []
        for call in calls:
            n["i"] += 1
            tid = _child(env["cond"], env["me"], key=f"sm@{n['i']}")
            got.append(SimpleNamespace(task_id=tid, status="done", outcome="ok",
                                       refusal_reason="", detail="跑完了"))
        return got

    monkeypatch.setattr(env["cond"], "run_plan", run_plan)
    tasks = ["把第 1 件的证据补齐。", "把第 2 件的证据补齐。"]
    targets = [{"role": CHILD, "task": t} for t in tasks]
    out = env["loop"]._do_summon_many({"targets": targets})
    assert out.get("ok") is True and out.get("count") == 2, out
    assert "roster_problems" not in out, ("批量那一路还有没登记上的", out)
    rows = _adds(env["ws"], env["me"])
    assert [str(r["brief"]) for r in rows] == [SEC.brief_from_task(t) for t in tasks], rows
    assert {str(r["brief_source"]) for r in rows} == {"secretary"}, rows


def test_negctl_agent_loop_substituting_the_task_for_the_brief_is_red(tmp_path: pathlib.Path):
    """① 负控（口径那一半）：业主选的是"秘书写"，不是"拿任务原文顶替"。

    改前别的实现在 loop 那一层写 `brief=brief_arg or task_arg` —— 那样盘上没有
    `brief_source`（那句话被当成父给的），判据要能读出这个差别。这里直接构造那一份
    "顶替出来的"登记行：`brief` 与 `task` 逐字相同、却没有 `brief_source`，
    于是 `_brief_written_by_secretary` 必红。
    """
    env = _env(tmp_path)
    tid = _child(env["cond"], env["owner"], key="brief@h")
    row = {"kind": "add", "owner": env["owner"], "name": "E1", "role": CHILD,
           "task_id": tid, "first_task_id": tid, "brief": TASK_TWO_SENTENCES,
           "surface": "S01", "at": "2026-10-20T10:00:00+08:00"}
    with pytest.raises(AssertionError):
        _brief_written_by_secretary(
            {"problem": "", "brief": TASK_TWO_SENTENCES, "brief_written": True}, [row],
            TASK_TWO_SENTENCES)


# ============================================================ ④ D：研究侧由你主导

#: 那条政策要列举的四个能力锚点（业主给的口径：C 要候选路径 / E 写脚本玩具例子 /
#: F 攻坚 / 让 F 带 V 的签字）。
D_MUST_LIST = ("研究侧由你主导", "派 C", "派 E", "派 F", "让 F 带 V 的签字")

#: 业主给的长度上限（「都 ≤90 字」）。
MAX_POLICY_ITEM = 90


def _d_lead_problems(policy) -> list[str]:
    """D 的 policy 里"你主导研究"那一条的全部问题（空列表 = 全对）。"""
    items = [str(x) for x in policy]
    hit = [x for x in items if "研究侧由你主导" in x]
    if not hit:
        return [f"D 的 policy 里读不到「研究侧由你主导」这一条（共 {len(items)} 条）"]
    text = hit[0]
    out = [f"缺「{needle}」" for needle in D_MUST_LIST if needle not in text]
    if len(text) > MAX_POLICY_ITEM:
        out.append(f"那一条 {len(text)} 字，超过业主给的上限 {MAX_POLICY_ITEM} 字")
    return out


def test_d_owns_the_research_side() -> None:
    """④ 正控：D 的 policy 第一条就是"你主导研究"，四件事逐条列出来，且 ≤90 字。"""
    policy = builtin_specs()["D"].brief.policy
    bad = _d_lead_problems(policy)
    assert bad == [], "D 的 policy 与 2026-10-20 的裁定不一致：\n  - " + "\n  - ".join(bad)
    assert "研究侧由你主导" in str(policy[0]), (
        "那一条要在 policy 的**最前面**（越靠后越会被读成补充说明）", policy[0])


def test_negctl_dropping_the_d_lead_item_is_red() -> None:
    """④ 负控：把那一条删掉 ⇒ 判据必红（删掉不等于"这条授权仍然在"）。"""
    policy = builtin_specs()["D"].brief.policy
    dropped = tuple(x for x in policy if "研究侧由你主导" not in str(x))
    assert dropped != tuple(policy), "夹具前提：D 的 policy 里真有一条写着「研究侧由你主导」"
    assert _d_lead_problems(dropped) != []
    # 收尾（负控的负控）：真身仍然成立
    assert _d_lead_problems(policy) == []


# ============================================================ ⑤ M：压低自主操纵研究

#: 义务词：一句话里出现这些，才算它"在要求谁去做"（史实说明不在此列）。
_OBLIGATION = re.compile(r"(必须|应当|需要|要|不许|不要|派)")

#: "派 V" / "派 `V`"（含反引号那种写法）。
_DISPATCH_V = re.compile(r"派\s*`?V`?")

#: 压低措辞必须真的写在那里（业主原话的骨架）。
M_LOW_KEY = "不自己派 E 做实验"

#: 业主给的长度上限（「都 ≤90 字」）。
M_LOW_MAX = MAX_POLICY_ITEM


def _m_low_key_ok(policy) -> str:
    """M 的 policy 里"压低自主操纵研究"那一条的原文（读不到 ⇒ 空字符串）。"""
    return next((str(x) for x in policy if M_LOW_KEY in str(x)), "")


def _m_obligations(policy) -> list[str]:
    """M 的 policy 里"派 V 走查证明"这一类义务句（空列表 = 一句都没有）。

    两个分量：点名 `verify_proof`（V 的主动作）；或义务词 + "派 V"（同一个意思的另一种写法）。
    只看声明、不看注释：传进来的只有 `policy` 这个元组，而 `specs/m.py` 里那些
    2026-10-20 的裁定注释必须写（"这条边还在但不由你派"也是要留的话）。
    """
    out: list[str] = []
    for i, item in enumerate(policy):
        text = str(item)
        reasons: list[str] = []
        if "verify_proof" in text:
            reasons.append("点名了 `verify_proof`（V 的主动作）")
        if _OBLIGATION.search(text) and _DISPATCH_V.search(text):
            reasons.append("有义务词、且写着「派 V」")
        if reasons:
            out.append(f"policy[{i}]：" + "；".join(reasons) + f"\n      原文：{text[:160]}")
    return out


def test_m_steps_back_from_running_the_research() -> None:
    """⑤ 正控：M 的 policy 有压低措辞、且不再有"派 V/`verify_proof`"的义务句，且 ≤90 字。"""
    policy = builtin_specs()["M"].brief.policy
    item = _m_low_key_ok(policy)
    assert item, f"M 的 policy 里读不到「{M_LOW_KEY}」这一类压低措辞"
    assert "研究侧的执行由 D 主导" in item, item
    assert "不自己驱动攻坚" in item and "不替 D 决定下一步" in item, item
    assert "派 D" in item, ("要把「派 D」写出来 —— 压低了却不给出口，M 只会愣住", item)
    assert len(item) <= M_LOW_MAX, (f"那一条 {len(item)} 字，超过业主给的上限 "
                                    f"{M_LOW_MAX} 字", item)
    bad = _m_obligations(policy)
    assert bad == [], ("M 的 policy 里还有『派 V 走查』的义务句（模型会照着派，而 V 的签字"
                       "只由 F / B 发起）：\n  - " + "\n  - ".join(bad))
    # 反真空：两句"转交"必须真的写在那里 —— 否则"没有义务句"可以用"整条删掉"来满足
    text = "\n".join(str(x) for x in policy)
    for marker in ("要有人走查就派 D 去办", "就当场交给 D 去核签"):
        assert marker in text, (f"M 的 policy 里读不到转交后的那句「{marker}」⇒ 这条义务没落点",
                                text[:200])


def test_negctl_putting_the_dispatch_v_obligations_back_is_red() -> None:
    """⑤ 负控：把那两条"派 V"的义务句各自加回 M ⇒ 判据必红（每条都要单独咬得住）。"""
    policy = builtin_specs()["M"].brief.policy
    removed = (
        "**要 V 走查就直接派 V**：正文或 `statements` 里存在**证明级断言**（`proof_review` / "
        "`proof`）而 `reviewed_proof_rows` 记 0 时，要么派 `V` 走查（`verify.verify_proof`，"
        "逐条签名落 `verifications`），要么在验收表那一行写清为什么没有 V 的签名。",
        "**「攻」里出现 `statement_id` 就当场派 V 去走查那一条**：看到它就在同一轮里派 "
        "`V.verify_proof(statement_id=<那个命题号>)`，不要等收工再想起来。",
        "缺签的活必须派 V 去做。",
    )
    for extra in removed:
        assert _m_obligations((*policy, extra)), f"这句加回 M 之后判据居然绿了：{extra!r}"
    # 压低措辞也照样能咬：换成"自己派 E 做实验"那一档（把"不"删掉）
    lowered = tuple(str(x).replace(M_LOW_KEY, "自己派 E 做实验") for x in policy)
    assert _m_low_key_ok(lowered) == "", ("把「不」删掉之后仍能读回那一条 ⇒ 判据认不出"
                                          "口径被反过来")
    # 收尾（负控的负控）：原样的 policy 必须重新成立
    assert _m_obligations(policy) == []
    assert _m_low_key_ok(policy)

# -*- coding: utf-8 -*-
"""D 的秘书审 D 的派活：这一条是不是一个研究方向（业主 2026-11-13，R2）。

业主原话（逐字）：

> 「plan由F自己决定，所以D不可能做出按plan个数派F，于是D只能按研究方向开多个F而非把
>   一堆方向委托给一个F（这里D秘书要审D的派活，不合适需要给出提醒，我们就做提示词侧和
>   流程侧的工作，不再用一个比如说研究方向列表来一对一绑定）。」

## 这一份钉的五条

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a | 模型判「不合适」⇒ 建议变成「建议重排」且提醒正文带上"该怎么拆"；台账一行 `verdict=不合适` | 改前没有 `dispatch_fit` 这一轴（`judge("dispatch_fit")` 直接回"不认识的判断类别"） |
| b | 模型判「合适」⇒ 结论不动（可派）；台账一行 `verdict=合适` | 同上 |
| c | 判不了（没有缝）⇒ `checked=False` + 台账 `decision=没查成`，而派活照发（只提醒不拦） | 同上 |
| d | 反真空：把内核打桩成恒「合适」⇒ a 的红必须变绿（证明 a 的红来自判定） | —— |
| e | 端到端：D 的循环里这一步的 `秘书.assessment` 带上提醒，而 `attack_plans` 真的多了一行（没被拦） | 同上 |

零网络：模型缝是替身（`ask_json` 直接回写死的 JSON）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_loop as AL
from agentflow import agent_f as AF
from agentflow import secretary as SEC
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.tools import build_registry

UNSUITABLE_WHY = "这条派活里捆了两个方向（甲、乙）⇒ 建议拆成两条：各派一个 F"
SUITABLE_WHY = "只写了一个方向与可试的两条路"


class FakeSeam:
    """替身判断面：`ask_json` 直接回写死的 JSON（不发请求、不花钱）。"""

    def __init__(self, data: dict) -> None:
        self.data = dict(data)
        self.calls: list[dict] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        self.calls.append({"prompt": prompt, "system": system, "note": note})
        call = type("Call", (), {"ok": True, "problem": "", "detail": ""})()
        return dict(self.data), call


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _sec(store: Store, seam) -> SEC.Secretary:
    return SEC.Secretary("D", root=store.root, store=store, seam=seam,
                         enable_model=True, sid="t")


BUNDLED = {
    "decision": "不是一个方向",
    "reason": UNSUITABLE_WHY,
    "basis": ["task 里同时出现『方向甲』与『方向乙』两件事"],
}
ONE_DIRECTION = {"decision": "是一个方向", "reason": SUITABLE_WHY,
                 "basis": ["task 只写了一个方向"]}


# ============================================================ a：不合适 ⇒ 提醒
def test_a_an_unsuitable_dispatch_gets_a_reminder_that_says_how_to_split(
        tmp_path: pathlib.Path) -> None:
    """a 判据：判「不合适」⇒ 建议变「建议重排」、提醒正文带拆法、台账一行。

    改前红：改前 `JUDGE_VERDICTS` 里没有 `dispatch_fit`，`judge("dispatch_fit")`
    直接回 `checked=False`（"不认识的判断类别"）⇒ 提醒永远不会出现。
    """
    store = _ws(tmp_path)
    seam = FakeSeam(BUNDLED)
    sec = _sec(store, seam)
    out = sec.assess_delegation(to="F", action="", params={},
                                task="方向甲：把界算出来；方向乙：把同构类数出来")
    assert out["decision"] == "建议重排", out
    assert UNSUITABLE_WHY in str(out.get("reason") or ""), out
    rows = SEC.dispatch_fit_rows(store.root)
    assert len(rows) == 1, rows
    assert rows[0]["checked"] is True and rows[0]["verdict"] == "不是一个方向", rows
    assert rows[0]["task"].startswith("方向甲"), rows
    assert "方向甲" in str(rows[0]["basis"]), rows
    assert seam.calls and "dispatch_fit" in seam.calls[0]["system"], seam.calls


# ============================================================ b：合适 ⇒ 不动
def test_b_a_single_direction_leaves_the_conclusion_alone(tmp_path: pathlib.Path) -> None:
    """b 判据：判「合适」⇒ 结论仍是「可派」，台账一行 `verdict=合适`。

    改前红：同 a（这一轴不存在，`checked=False` ⇒ 台账根本不会有一行）。
    """
    store = _ws(tmp_path)
    sec = _sec(store, FakeSeam(ONE_DIRECTION))
    out = sec.assess_delegation(to="F", action="", params={},
                                task="弄清这一族在 n≤20 的界；可以试母函数与 Fourier 两条路")
    assert out["decision"] == "可派", out
    rows = SEC.dispatch_fit_rows(store.root)
    assert len(rows) == 1 and rows[0]["verdict"] == "是一个方向", rows
    assert rows[0]["decision"] == "是一个方向", rows


# ============================================================ c：判不了只提醒不拦
def test_c_without_a_seam_the_reading_is_unchecked_and_the_dispatch_is_not_blocked(
        tmp_path: pathlib.Path) -> None:
    """c 判据：没有判断面 ⇒ `checked=False` + `没查成`，而派活的结论不被改写。

    改前红：同 a。三态纪律：`没查成` 不许写成"是一个方向"（那会把"没审"读成"审过了"）。
    """
    store = _ws(tmp_path)
    sec = SEC.Secretary("D", root=store.root, store=store, seam=None, enable_model=True)
    out = sec.assess_delegation(to="F", action="", params={},
                                task="方向甲与方向乙一起做")
    assert out["decision"] == "可派", out  # 没判成 ⇒ 不改结论（只提醒不拦）
    rows = SEC.dispatch_fit_rows(store.root)
    assert len(rows) == 1, rows
    assert rows[0]["checked"] is False, rows
    assert rows[0]["decision"] == SEC.JUDGE_UNCHECKED, rows
    assert rows[0]["verdict"] == "", rows
    assert "没" in str(rows[0]["why"]), rows


# ============================================================ d：反真空
def test_d_stubbing_the_core_to_say_always_suitable_turns_a_green(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d 判据（反真空）：把判定内核打桩成恒「合适」⇒ a 的红必须变绿。

    证明 a 的红来自"模型判了不合适"，而不是来自"派活本身一定会被改结论"。
    """
    store = _ws(tmp_path)
    sec = _sec(store, FakeSeam(BUNDLED))
    monkeypatch.setattr(
        SEC.Secretary, "_judge_core",
        lambda self, kind, context, **kw: {"checked": True, "decision": "是一个方向",
                                           "reason": SUITABLE_WHY, "basis": []})
    out = sec.assess_delegation(to="F", action="", params={}, task="方向甲与方向乙一起做")
    assert out["decision"] == "可派", out


# ============================================================ e：端到端
class _Scripted:
    """照剧本回答的替身模型（D 的循环用）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None, **kw):
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


def test_e_the_reminder_reaches_the_step_and_the_dispatch_still_runs(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e 判据（端到端）：D 的这一步结果里有那条提醒，而派活没有被它挡住。

    「提醒」不是「拒收」：派活照发（`tasks` 里有一行 `role=F`），只是
    `秘书.assessment` 的结论变成「建议重排」并带上该怎么拆。

    可抢占派活在这一条里关掉（`PREEMPTIBLE_DISPATCH=False`）：那一档派完就返回、
    子代理在后台线程里跑，断言"计划行已经落盘"会变成一次竞态 —— 本用例判的是
    "提醒不拦派活"，不是"可抢占的时序"。挂机判定也不参与（`_park_gate` 打桩成
    "照常问模型"）：这一条判的是"秘书的意见有没有挡住派活"，不是"无事可做时该不该挂机"
    —— 让 D 照常跑一步收工，本判据的对象（派活那一步的结果）一个字不受影响。
    """
    monkeypatch.setattr(AL, "PREEMPTIBLE_DISPATCH", False)
    monkeypatch.setattr(
        AL.AgentLoop, "_park_gate",
        lambda self, *, step, run, mailbox: {
            "decision": "run", "skip_model": False,
            "reason": "夹具：挂机判定不是本判据的对象"})
    store = _ws(tmp_path)
    fake_f = AF.AgentF(store, config={"workspace_root": store.root}, actor="agent-F-F1")
    gw = _Scripted([
        json.dumps({"summon": {
            "role": "F", "action": "create_plan",
            "params": {"problem": "两个方向一起攻", "problem_key": "PK-DISPATCH-FIT"},
            "task": "方向甲：把界算出来；方向乙：把同构类数出来"}}, ensure_ascii=False),
        json.dumps({"final": "这一步试过了，见读数", "evidence": [],
                    "notify": {"to": "M", "summary": "派活已完成",
                               "body": "把两个方向交给 F 的那一步已经发出。",
                               "refs": [], "why": "按循环协议收工"}},
                   ensure_ascii=False),
    ])
    # 这一条要的是"F.create_plan 真的被执行"：确定性后端直接调注册表里的 F，
    # 不经过 `LlmBackend`（那一层要 seam_factory，判的是另一件事）。
    cond_loop = Conductor(store, policy=None,
                          backend=LocalBackend({"F": ("object", fake_f)}))
    reg = build_registry(store=store, conductor=cond_loop).registry
    sec = _sec(store, FakeSeam(BUNDLED))

    run = AL.run_role("D", "派活：一个研究方向交给 F", store=store, registry=reg,
                      conductor=cond_loop, gateway=gw, session_root=store.root,
                      sid="t", from_env=False, max_steps=1, secretary=sec)

    step = next((s for s in run.steps if s.shape == "summon"), None)
    assert step is not None, [s.shape for s in run.steps]
    note = dict(step.result.get("秘书") or {})
    assessment = dict(note.get("assessment") or {})
    assert assessment.get("decision") == "建议重排", (note, step.result)
    assert UNSUITABLE_WHY in str(assessment.get("reason") or ""), assessment
    # 只提醒不拦：这一步的结果里没有因为派活审阅而拒收的痕迹，而且派活真的发出去了
    # （`tasks` 里有一行 `role=F`）。这一行的终态在本夹具里是 `not_wired` —— 这条夹具没有
    # 给 F 配循环，那是"F 自己怎么执行"的另一件事；本判据要证的是"秘书的意见没有挡住它"，
    # 落点是 `_execute` 真的跑了（有台账行），不是 F 跑成了。
    assert step.result.get("refused") not in ("dispatch_fit", "not_recommended"), step.result
    f_rows = [r for r in store.rows("tasks") if str(r.get("role") or "") == "F"]
    assert f_rows, store.rows("tasks")
    # 台账那一行也在（派活审阅的唯一落点）
    rows = SEC.dispatch_fit_rows(store.root)
    assert rows and rows[0]["verdict"] == "不是一个方向", rows


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

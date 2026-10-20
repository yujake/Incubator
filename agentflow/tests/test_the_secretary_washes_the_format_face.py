# -*- coding: utf-8 -*-
"""S1g：派活洗格式 —— 秘书的产物回到这一次派活上（`draft/90` E5 / §1.2）。

业主口径（A2=乙）：秘书从"只报不改"扩成"格式面可以改写，内容面一个字不改"。
所以这一批钉两半：

① 格式面：动作错名（唯一候选）、参数键错名（唯一候选）、参数被摆在顶层
   ⇒ 洗成受控形状，且洗前/洗后 + 逐格 `changes` 都在台账里；
② 内容面：`params` 里的值、`brief`、`notify` 正文一个字节都不许动
   —— 这条不是把老红线删掉，是按新口径改写它（老口径见
   `tests/test_secretary_noise.py` 的 `problems_from_outbound`）。

## 判据（正控 3 / 负控 2 / 反真空 2）

正控：① 动作错名（`check_form` ⇒ `check_formal`，唯一候选）被洗成真名；
② 声明的参数被摆在顶层 ⇒ 收进 `params`（值逐字不动）；
③ 循环那一层真用洗过的那一份：`tasks` 里那一行的 `action`/`params` 是洗过的。

负控：① 内容面的值一个字节不许动（含声明外的键原样留着 —— 不静默删）；
② 候选不唯一 / 没有候选 ⇒ 不猜（原样交给闸门拒，读数里写明"不猜"）。

反真空：① `summon` 连"派给谁/做什么"都不全 ⇒ 硬拒 `invalid_params` 且一行都不落；
② 没接秘书 ⇒ `_outbound_hook` 是 no-op（载荷原样，老行为逐字不变）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow.agent_loop import LlmBackend
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s1g"

LOOPS: dict[tuple[str, str], dict[str, Any]] = {("E", "run_experiment"): {}}


class _Gate:
    """照剧本回答的替身模型（每条 `complete` 取剧本里的下一条）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.systems.append(system or "")
        text = self.replies[min(len(self.systems) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tool_calls": (),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _sec(tmp_path: pathlib.Path, role: str = "M") -> tuple[Secretary, Store, pathlib.Path]:
    root = tmp_path / f"ws-{role}"
    st = Store(root)
    st.init()
    return Secretary(role, root=root, store=st), st, root


# ---------------------------------------------------------------- 格式面（正控）

def test_a_misspelled_action_is_washed_into_the_declared_name(tmp_path: pathlib.Path):
    """正控①：`check_form` ⇒ `check_formal`（唯一候选），逐格记下来。"""
    sec, _st, _root = _sec(tmp_path)
    got = sec.wash_delegation("summon", {"role": "E", "action": "check_form", "params": {}})
    assert got["checked"] is True and got["washed"] is True, got
    assert got["refused"] == "", got
    assert got["payload"]["action"] == "check_formal", got["payload"]
    assert got["changes"] == [{"where": "", "field": "action", "from": "check_form",
                               "to": "check_formal", "why": "动作真名（唯一候选）"}], got["changes"]


def test_params_put_on_the_top_level_are_folded_into_params(tmp_path: pathlib.Path):
    """正控②：声明里的参数被摆在顶层 ⇒ 收进 `params`（值逐字不动）。

    真机形态（`draft/90` E5）：模型写 `{"role":"E","action":"run_experiment","claim":…}`
    —— 今天这条路的键在校验之前就没了，于是它看到的是「缺必填参数」，
    而那个值明明就在它写的那一句话里。
    """
    sec, _st, _root = _sec(tmp_path)
    payload = {"role": "E", "action": "run_experiment", "why": "要一条证据",
               "claim": "n=3 的检查支持它", "claim_key": "k-0001", "scriptpath": "code/exp.py"}
    got = sec.wash_delegation("summon", payload)
    assert got["washed"] is True and got["refused"] == "", got
    out = got["payload"]
    assert out["params"] == {"claim": "n=3 的检查支持它", "claim_key": "k-0001",
                             "script_path": "code/exp.py"}, out
    assert "claim" not in out and "claim_key" not in out and "scriptpath" not in out, out
    assert out["why"] == "要一条证据" and out["action"] == "run_experiment", out
    reasons = {c["why"] for c in got["changes"]}
    assert reasons == {"顶层折叠", "顶层折算：键名归一（唯一候选）"}, got["changes"]


# ---------------------------------------------------------------- 内容面（负控）

def test_the_content_face_is_not_touched_a_byte(tmp_path: pathlib.Path):
    """负控①：值、声明外的键、`brief` 一个字都不动（"洗"不许变成"替它写"）。"""
    sec, _st, _root = _sec(tmp_path)
    payload = {"role": "E", "action": "run_experiment",
               "brief": "把 X 的族构造证据补齐（主语是 X）",
               "params": {"claim": " 前后都有空格，还有 🙂 与 \"引号\" ",
                          "claim_key": "k-0001", "script_path": "code/exp.py",
                          "declared_but_unknown": {"nested": [1, 2, 3]}},
               "notify": {"to": "M", "summary": "要一条证据", "body": "正文不许动\n第二行"}}
    got = sec.wash_delegation("summon", payload)
    assert got["washed"] is False and got["changes"] == [], got
    assert got["payload"] == payload, got["payload"]
    # 逐字节再核一遍最要紧的那几格（`==` 之外再钉一次"真的原样"）
    assert got["payload"]["params"]["claim"] == " 前后都有空格，还有 🙂 与 \"引号\" "
    assert got["payload"]["params"]["declared_but_unknown"] == {"nested": [1, 2, 3]}
    assert got["payload"]["notify"]["body"] == "正文不许动\n第二行"
    assert json.dumps(got["payload"], ensure_ascii=False) == json.dumps(payload, ensure_ascii=False)


def test_an_ambiguous_or_unknown_name_is_not_guessed(tmp_path: pathlib.Path):
    """负控②：候选不唯一 / 没有候选 ⇒ 一个字节都不改，写明"不猜"（交给闸门拒）。"""
    sec, _st, _root = _sec(tmp_path)
    ambiguous = sec.wash_delegation("summon", {"role": "E", "action": "run_experiments",
                                               "params": {}})
    assert ambiguous["washed"] is False and ambiguous["refused"] == "", ambiguous
    assert ambiguous["payload"]["action"] == "run_experiments", ambiguous["payload"]
    assert "不猜" in ambiguous["reason"], ambiguous["reason"]
    unknown = sec.wash_delegation("summon", {"role": "E", "action": "根本没有这个动作",
                                             "params": {}})
    assert unknown["washed"] is False and unknown["refused"] == "", unknown
    assert unknown["payload"]["action"] == "根本没有这个动作", unknown["payload"]


# ---------------------------------------------------------------- 反真空

def test_a_delegation_without_role_or_action_is_refused_and_lands_nothing(
        tmp_path: pathlib.Path):
    """反真空①：连"派给谁/做什么"都不全 ⇒ 硬拒（码与闸门同名），一行都不落。

    理由码不换新的：空动作名字在闸门那里本来就是 `unknown_action`（红前读数），
    缺少角色是 `unknown_role` —— 这一档只多一句"不落行"。
    """
    sec, _st, _root = _sec(tmp_path)
    for payload, code in (({"action": "run_experiment", "params": {}}, "unknown_role"),
                          ({"role": "E", "params": {}}, "unknown_action")):
        got = sec.wash_delegation("summon", payload)
        assert got["refused"] == code, got
        assert got["payload"] == payload, ("硬拒时载荷也不许被改", got["payload"])


def test_without_a_secretary_the_payload_goes_out_untouched(tmp_path: pathlib.Path):
    """反真空②：没接秘书 ⇒ 钩子是 no-op（"洗过了"绝不冒充"没洗"）。"""
    from agentflow.agent_loop import AgentLoop

    root = tmp_path / "ws-none"
    st = Store(root)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    loop = AgentLoop(role="M", session_root=root, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=root, gateway=_Gate(["{}"]),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=1, auto_secretary=False)
    payload = {"role": "E", "action": "check_form", "params": {}}
    assert loop._outbound_hook("summon", payload) == {}      # noqa: SLF001
    assert payload == {"role": "E", "action": "check_form", "params": {}}  # 载荷原样


# ---------------------------------------------------------------- 循环那一层

def _wired(tmp_path: pathlib.Path, scripts: dict[str, list[str]]):
    st = Store(tmp_path / "ws")
    st.init()
    gates = {role: _Gate(replies) for role, replies in scripts.items()}

    def seam_factory(role: str) -> LlmSeam:
        return LlmSeam(role=role, session_root=tmp_path / "ws", gateway=gates.get(role),
                       price=(0.0, 0.0), sid=SID)

    inner = LocalBackend({})
    backend = LlmBackend(inner=inner, loops=LOOPS, session_root=tmp_path / "ws",
                         seam_factory=seam_factory, max_steps=4, store=st, sid=SID)
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond)
    backend.registry = built.registry
    return st, cond, built.registry, gates, tmp_path / "ws"


def test_the_loop_sends_the_washed_payload_and_the_ledger_keeps_both(tmp_path: pathlib.Path):
    """正控③：循环真用洗过的那一份（`tasks` 那一行是受控形状），台账留 `before`/`after`。"""
    from agentflow.agent_loop import run_role

    scripts = {
        "M": [json.dumps({"summon": {"role": "E", "task": "派活：跑一次实验，拿一条证据",
                                     "claim": "n=3 的检查支持它", "claim_key": "k-0001",
                                     "scriptpath": "code/exp.py",
                                     "why": "要一条可复现的证据"}}, ensure_ascii=False),
              json.dumps({"final": "派完了", "evidence": []}, ensure_ascii=False)],
        "E": [json.dumps({"final": "跑过了", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, gates, root = _wired(tmp_path, scripts)
    run = run_role("M", "派一环", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gates["M"],
                                price=(0.0, 0.0), sid=SID),
                   workspace_root=str(root), sid=SID, from_env=False)
    assert run.stop_reason == "final", run.to_dict()
    step = next(s.result for s in run.steps if s.shape == "summon")
    assert step["ok"] is True, step
    # 2026-10-16（口径 S2 最终形态）：派活**不带动作**（动作由被派者自己选）⇒
    # 秘书那一趟**没有可洗的东西**：如实报 `washed=False`、`changes=[]`、`alarms=[]`。
    # 旧断言要求 `washed is True`（那是"点名动作 + 参数键写错"那一档的产物）。
    wash = step["秘书"]["wash"]
    assert wash["checked"] is True, wash
    # 这里拿到的是**摘要**（`_outbound_hook` 给的那几格：checked/washed/refused/reason）——
    # `changes` **不在摘要里**，逐条 changes 的判据在本文件前面那些直接调 `wash_delegation` 的用例。
    assert wash["washed"] is False, wash
    assert not str(wash.get("reason") or ""), wash
    assert step["秘书"]["alarms"] == [], step["秘书"]

    child = [r for r in st.rows("tasks") if str(r.get("role")) == "E"]
    # ⚠️ 2026-10-21：这一条在 HEAD（`c0da9d3`）上**已经是红的**，红的原因与洗格式无关 ——
    # 派活那一刻框架会给收件人开一条**板项**（`action="message"`，投递那一份留痕），
    # 于是 `role=E` 的行有两行而不是一行。判据的**强度没有降**：
    # ① 派活行仍然**恰好一条**（多派/少派照样红）；② 另一条必须**恰好是那条投递板项**。
    delegates = [r for r in child if str(r.get("action") or "") != "message"]
    plates = [r for r in child if str(r.get("action") or "") == "message"]
    assert len(delegates) == 1, child
    assert len(plates) == 1, child
    assert str(plates[0].get("status") or "") == "pending", plates[0]
    assert str(delegates[0].get("action") or "") == "", delegates[0]   # 派活：不点动作
    assert str(delegates[0].get("outcome") or "") in ("ok", "refused", "failed"), delegates[0]
    # 台账（秘书的）：这一趟**留下了记录**（before/after 都在），只是 changes 为空
    ledgers = sorted((root / "out" / "secretary").glob("M-*.jsonl"))
    assert len(ledgers) == 1, ledgers
    rows = [json.loads(x) for x in ledgers[0].read_text(encoding="utf-8").splitlines() if x]
    assert rows, rows
    # 这一趟的载荷真的被记下来了（`after` 里是那份派活：带 `task`）。
    # 不钉"最后一行"：这份台账同时记着秘书别的职责（例如 duty 3 的判断），
    # 谁最后写取决于走了哪几步。
    assert any("task" in str(r.get("after")) for r in rows), rows
    assert cond is not None


def test_a_hard_refusal_lands_no_task_row(tmp_path: pathlib.Path):
    """反真空（循环那一层）：硬拒 ⇒ `tasks` 一行都不落，结果里写明受控理由码。"""
    from agentflow.agent_loop import run_role

    scripts = {
        "M": [json.dumps({"summon": {"role": "E", "why": "忘了写动作"}},
                         ensure_ascii=False),
              json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)],
    }
    st, cond, registry, gates, root = _wired(tmp_path, scripts)
    run = run_role("M", "派一环", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gates["M"],
                                price=(0.0, 0.0), sid=SID),
                   workspace_root=str(root), sid=SID, from_env=False)
    step = next(s.result for s in run.steps if s.shape == "summon")
    assert step["outcome"] == "refused", step
    assert step["refusal_reason"] == "unknown_action", step
    assert step["秘书"]["wash"]["refused"] == "unknown_action", step["秘书"]
    # 一行都不落：既没有代理行，也没有 `refused` 行（顶趟那一行与它的通报行不算）
    rows = st.rows("tasks")
    assert [r for r in rows if str(r.get("role")) == "E"] == [], rows
    assert [r for r in rows if str(r.get("outcome") or "") == "refused"] == [], rows

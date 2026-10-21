# -*- coding: utf-8 -*-
"""两段式：秘书洗格式 → 父确认 → 才执行（不是"直接应用"，也不是"永远只建议"）。业主裁定（2026-10-21）：派活时"委托秘书洗一遍格式"是两段。第一段（洗 + 请示）：`washed == original` ⇒
直接执行（不为"没差异"多花一轮）；`washed != original` ⇒ 不执行，返回受控读数`outcome="wash_proposed"` + `proposal_id` + 逐字段 diff。第二段（确认）
：父带 `accept_proposal=<id>` ⇒ 用 `washed` 执行；带 `reject_proposal=<id>` ⇒ 用 `original` 执行并留痕"拒绝了格式洗"。为什么必须是两段：一段（直接应用）
等于秘书替本体表态（`draft/53` §2 的两条红线：不替它承诺、不改结论）；而零段（永远只建议，S1g 之前的形态）让"洗一遍格式"变成摆设 ——派活实际发出去的仍是错名原稿，继续撞闸门（`draft/90` E5
的实测读数）。

## 判据（五条，每条带负控；负控 = 把那一格改回坏形态 ⇒ 同一个判据体必须变红）

| # | 绿（本文件的正控） | 红（负控：故意改坏一处） |
|---|---|---|
| ① | 有差异 ⇒ 不执行：`wash_proposed` + 编号 + diff，0 行新任务 / 0 次后端调用 | 改成"自动接受、直接执行 washed" ⇒ ① 报"派了子任务 / 没有 wash_proposed"
|
| ② | 接受 ⇒ 用 washed 执行：后端收到的那份 == washed，`accepted=true` | 接受后仍发 original（读数还谎称 washed）⇒ ② 报"发出去的是原稿" |
| ③ | 拒绝 ⇒ 用 original 执行：后端收到的那份 == original，`accepted=false` | 拒绝后仍发 washed ⇒ ③ 报"发出去的是洗过的那份" |
| ④ | 不越界：值逐字不变、不增删参数、`task`/`brief`/`notify` 正文逐字不变 | 把"改值"混进洗函数 ⇒ ④ 报"值被改了" |
| ⑤ | 无差异 ⇒ 直接执行、不产生 `wash_proposed` | 无差异也请示 ⇒ ⑤ 报"为没差异多花了一轮" |

判据体是函数（`_proposal_problems` / `_boundary_problems` / …），不是断言串 ——于是"绿"与"红"是同一个函数在两份代码上的两次调用（这就是负控的可演示形态）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.secretary import (
    ACCEPT_PROPOSAL,
    OUTCOME_WASH_PROPOSED,
    PROPOSAL_KEYS,
    REJECT_PROPOSAL,
    Secretary,
)
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "wash2"

#: 被派的角色/动作：`B.register_statement` 是唯一候选能接住 `own.register_statement` 的那一格
#: （`declarations_candidates` 的唯一命中；判据 ④ 要"动作名写错"这个前提）。
LOOPS: dict[tuple[str, str], dict[str, Any]] = {("B", "register_statement"): {},
                                                ("B", ""): {}}

#: 秘书自己的判断面（职责 2 的 `judge`）：桩。不桩的话它会吃掉剧本里的一步
#: —— 而这一条与"洗格式"是两件事（`_outbound_hook` 里两段各调一次模型）。
JUDGE_REPLY = json.dumps({"decision": "可派", "reason": "桩：不判", "basis": []},
                         ensure_ascii=False)

#: 必须洗格式的那份派活（判据 ④ 的现场）：
#: - 动作名写错：`own.register_statement`（唯一候选 `register_statement`）；
#: - `params` 用别名键：`stmt_text` ⇒ `statement_text`（唯一候选）。
#: 判别"唯一候选"靠的是 `declarations_candidates`：`stmt_text` 只命中 `statement_text`
#: 一个（`statementtext` 会同时命中 `statement_full` / `statement_text` ⇒ 不猜、不洗）。
#: 值故意带首尾空白：洗格式一个字都不许动它 —— 那条正是负控"改值"要咬的地方。
#:
#: 第三条（"必填字段被摆在顶层"）不放在这一份里：派活形状的解码是白名单，
#: 而它按写对了的动作去查声明（`_carried_top_level_params`），所以"动作名同时写错"的
#: 那份载荷根本走不到秘书面前（顶层那一格在解码时就被丢了，与洗格式无关）。
#: 那一格由 `test_the_wash_moves_keys_and_never_touches_a_value` 的第二段直接打秘书的 API。
BODY: dict[str, Any] = {
    "role": "B",
    "action": "own.register_statement",
    "task": "把这条命题入库（主语是 n=3 的那个族）",
    "params": {"stmt_text": " 一个短名 "},
    "why": "要一条能引的命题",
}

#: `_content_values` 与判据 ④ 的口径：这些是协议/格式键（可以换位置、换真名），
#: 其余顶层键（含 `task`！）是内容面 —— 值一个字节都不许变。
_PROTOCOL_KEYS: frozenset[str] = frozenset({
    "role", "action", "params", "why", "notify", "brief", "name", "reuse",
    "input_key", "instance", "targets", "shape_alias", "tool", "args",
    *PROPOSAL_KEYS,
})


# --------------------------------------------------------------------------------------
# 夹具：一趟真的循环（剧本：派活 → 表态 → 收工）
# --------------------------------------------------------------------------------------

class _Gate:
    """照剧本回答的替身模型；秘书判断面单独用桩回答。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        if "你是「秘书」的判断面" in prompt:
            text = JUDGE_REPLY
        else:
            i = min(self.calls, len(self.replies) - 1)
            self.calls += 1
            text = self.replies[i]
        if callable(text):
            text = text()
        return type("Reply", (), {"ok": True, "text": text, "tool_calls": (),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _proposal_id_in(root: pathlib.Path) -> str:
    """从秘书台账里读回那条请示的编号（父"读到请示读数之后再派一次"的那一步）。"""
    for path in sorted((root / "out" / "secretary").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("proposal_id") and row.get("proposal_fingerprint"):
                return str(row["proposal_id"])
    return ""


def _run(tmp_path: pathlib.Path, *, key: str | None = None, body: Mapping[str, Any] | None = None,
         secretary: Any = None, shape: str = "summon",
         children: tuple[str, ...] = ("B",),
         loops: Mapping[tuple[str, str], dict] | None = None) -> dict[str, Any]:
    """跑一趟 M：第 1 步派活，第 2 步按 `key` 表态（None = 再派一次原稿），第 3 步收工。

    `shape` 只影响"这一步说的是哪一件事"（`summon` / `summon_many`）——
    两段式的判据对两者是同一份（`wash_delegation` 的两个形状）。
    """
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    payload = dict(body if body is not None else BODY)

    def say(body_out: Mapping[str, Any]) -> str:
        return json.dumps({shape: dict(body_out)}, ensure_ascii=False)

    def second() -> str:
        if key is None:
            return say(payload)
        return say({**payload, key: _proposal_id_in(root)})

    scripts: dict[str, list[Any]] = {
        "M": [say(payload), second,
              json.dumps({"final": "派完了", "evidence": []}, ensure_ascii=False)]}
    for role in children:
        scripts[role] = [json.dumps({"final": "干完了", "evidence": []}, ensure_ascii=False)]
    gates = {role: _Gate(replies) for role, replies in scripts.items()}

    def seam_factory(role: str) -> LlmSeam:
        return LlmSeam(role=role, session_root=root, gateway=gates.get(role),
                       price=(0.0, 0.0), sid=SID)

    inner = LocalBackend({})
    backend = LlmBackend(inner=inner, loops=dict(loops or LOOPS), session_root=root,
                         seam_factory=seam_factory, max_steps=6, store=st, sid=SID)
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond)
    backend.registry = built.registry
    #: 真正到主控（= 后端）那一侧的每一次召唤：判据 ②③ 看的是这一份，不是读数自报。
    seen: list[dict[str, Any]] = []
    original_summon = cond.summon

    def spy(role: str, action: str, params: Mapping[str, Any], **kw: Any) -> Any:
        seen.append({"role": role, "action": action, "params": dict(params or {}),
                     "input_key": str(kw.get("input_key") or "")})
        return original_summon(role, action, params, **kw)

    cond.summon = spy          # type: ignore[method-assign]
    # 批量那一支走 `run_plan`，而它内部逐个调 `summon` ⇒ 同一个 spy 同时覆盖两条路
    # （再包一次 `run_plan` 会把每一项记两遍：实测 2 个 target 读成 4 次）。
    run = run_role("M", "派一环", store=st, registry=built.registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gates["M"],
                                price=(0.0, 0.0), sid=SID),
                   workspace_root=str(root), sid=SID, from_env=False, secretary=secretary)
    return {"run": run, "store": st, "root": root,
            "steps": [s.result for s in run.steps if s.shape == shape],
            "seen": seen, "secretary": secretary, "shape": shape}


# --------------------------------------------------------------------------------------
# 判据体（绿/红共用；每条只吃读数，不自己造事实）
# --------------------------------------------------------------------------------------

def _same(a: Any, b: Any) -> bool:
    if a is b:
        return True
    try:
        return bool(a == b)
    except Exception:  # noqa: BLE001 —— 比不了就按"不同"（宁可多报一处）
        return False


def _content_values(payload: Mapping[str, Any]) -> list[Any]:
    """一份载荷里的内容值（`params` 里的值 + 顶层非协议键值；`task` 也算内容）。"""
    out: list[Any] = []
    for key, value in dict(payload or {}).items():
        if key == "params":
            if isinstance(value, Mapping):
                out.extend(value.values())
        elif key not in _PROTOCOL_KEYS:
            out.append(value)
    return out


def _boundary_problems(original: Mapping[str, Any],
                       washed: Mapping[str, Any]) -> list[str]:
    """判据 ④：洗格式没有越界（`draft/90` §1.2 + `draft/53` §2 的两条红线）。

    四条，逐条对着"可以洗什么 / 一个字不许动什么"：值逐字相同：内容值的多重集不变 —— 不许多出一个（"不静默补默认值"）、
    不许少一个（"不替它删"）、不许改一个（"不改结论/证据"）；
    2. 不增删参数：由第 1 条保证（`params` 的值一个不多一个不少 ⇒ 键也没被增删，
    只允许"同名换位置/换真名"）；
    3. 正文逐字相同：`task` / `brief` / `notify.body`（"派什么""怎么说"是内容面）；
    4. 不新造顶层键：洗只许搬、只许改真名，不许无中生有。

    为什么不写成"只允许这几个键变"的白名单：那是把今天的格式面钉死；这一条判的是方向（内容面一个字节都没动），格式面变多少格另由 `changes` 逐条报。
    """
    probs: list[str] = []
    before, after = _content_values(original), _content_values(washed)
    remaining = list(after)
    for value in before:
        hit = next((x for x in remaining if _same(value, x)), None)
        if hit is None:
            probs.append(f"洗过之后原稿的值不见了或被改了：{value!r}")
        else:
            remaining.remove(hit)
    for value in remaining:
        probs.append(f"洗过之后多出一个原稿里没有的值：{value!r}")
    for field in ("task", "brief"):
        if not _same(original.get(field), washed.get(field)):
            probs.append(f"`{field}` 正文被改了（内容面）")
    old_notify = original.get("notify") if isinstance(original.get("notify"), Mapping) else {}
    new_notify = washed.get("notify") if isinstance(washed.get("notify"), Mapping) else {}
    if not _same(str((old_notify or {}).get("body") or ""),
                 str((new_notify or {}).get("body") or "")):
        probs.append("`notify` 正文被改了（内容面）")
    extra = set(dict(washed or {})) - set(dict(original or {}))
    if extra:
        probs.append(f"洗过之后多出了顶层键 {sorted(extra)}（洗格式不该新造键）")
    return probs


def _proposal_problems(step: Mapping[str, Any], seen: list[dict[str, Any]],
                       store: Any) -> list[str]:
    """判据 ①：有差异 ⇒ 不执行（这一条只看事实：行数与后端调用次数）。"""
    probs: list[str] = []
    if str(step.get("outcome") or "") != OUTCOME_WASH_PROPOSED:
        probs.append(f"没有返回受控的请示读数（outcome={step.get('outcome')!r}）")
    if not str(step.get("proposal_id") or ""):
        probs.append("请示没有 proposal_id（编号由秘书发，父没法表态）")
    if not step.get("changes"):
        probs.append("请示没有逐条 changes（父看不出改了哪几处）")
    for key in ("original", "washed", "diff", "changed_keys"):
        if key not in step:
            probs.append(f"请示缺 `{key}`（逐字段 diff 要能逐格读）")
    if step.get("executed") is not False:
        probs.append("这一步没有明确写 `executed=False`")
    kids = [r for r in store.rows("tasks") if str(r.get("role")) == "B"]
    if kids:
        probs.append(f"有差异却真的派了子任务（台账多了 {len(kids)} 行）")
    if seen:
        probs.append(f"有差异却真的调了后端（{len(seen)} 次）")
    return probs


def _accept_problems(step: Mapping[str, Any], seen: list[dict[str, Any]],
                     proposal: Mapping[str, Any]) -> list[str]:
    """判据 ②：接受 ⇒ 用 washed 执行（看后端收到的那一份，不看读数自报）。"""
    probs: list[str] = []
    audit = step.get("wash") if isinstance(step.get("wash"), Mapping) else {}
    if not audit:
        probs.append("执行那一刻没有把 original/washed/accepted/proposal_id 记进结果")
        return probs
    if audit.get("accepted") is not True:
        probs.append(f"`accepted` 不是 true（读到 {audit.get('accepted')!r}）")
    if str(audit.get("proposal_id") or "") != str(proposal.get("proposal_id") or ""):
        probs.append("结果里的 proposal_id 与请示那一次不是同一个")
    if str(audit.get("executed_with") or "") != "washed":
        probs.append(f"`executed_with` 不是 washed（读到 {audit.get('executed_with')!r}）")
    if not _same(audit.get("washed"), proposal.get("washed")):
        probs.append("结果里记的 washed 与请示时那一份不一致（两段对不上同一件事）")
    if len(seen) != 1:
        probs.append(f"接受之后应当恰好派出一次（实际 {len(seen)} 次）")
        return probs
    got = dict(seen[0].get("params") or {})
    want = dict((proposal.get("washed") or {}).get("params") or {})
    # `task` 是 `_do_summon` 按形状并进去的那一格（不是参数），比对前先摘掉。
    got.pop("task", None)
    if not _same(got, want):
        probs.append(f"后端收到的参数不是 washed（收到 {got!r}，wash 过的是 {want!r}）")
    return probs


def _reject_problems(step: Mapping[str, Any], seen: list[dict[str, Any]],
                     proposal: Mapping[str, Any]) -> list[str]:
    """判据 ③：拒绝 ⇒ 用 original 执行（原稿里那几处格式错的键原样留着）。"""
    probs: list[str] = []
    audit = step.get("wash") if isinstance(step.get("wash"), Mapping) else {}
    if not audit:
        probs.append("执行那一刻没有把 original/washed/accepted/proposal_id 记进结果")
        return probs
    if audit.get("accepted") is not False:
        probs.append(f"`accepted` 不是 false（读到 {audit.get('accepted')!r}）")
    if str(audit.get("executed_with") or "") != "original":
        probs.append(f"`executed_with` 不是 original（读到 {audit.get('executed_with')!r}）")
    if len(seen) != 1:
        probs.append(f"拒绝之后应当恰好派出一次（实际 {len(seen)} 次）")
        return probs
    got = dict(seen[0].get("params") or {})
    got.pop("task", None)
    if not _same(got, dict((proposal.get("original") or {}).get("params") or {})):
        probs.append(f"后端收到的参数不是原稿（收到 {got!r}）")
    if "statement_text" in got:
        probs.append("拒绝之后仍然发的是洗过的那份（别名键被折算成真名了）")
    return probs

def _no_diff_problems(step: Mapping[str, Any], store: Any) -> list[str]:
    """判据 ⑤：无差异 ⇒ 直接执行、不产生请示（不为"没差异"多花一轮）。"""
    probs: list[str] = []
    if str(step.get("outcome") or "") == OUTCOME_WASH_PROPOSED or "proposal_id" in step:
        probs.append("无差异也请示了（多花了一轮）")
    if "wash_proposal" in json.dumps(step, ensure_ascii=False, default=str):
        probs.append("无差异也产生了 wash_proposal 读数")
    kids = [r for r in store.rows("tasks") if str(r.get("role")) == "B"]
    if not kids:
        probs.append("无差异却没有真的派活（这条判据要的是'直接执行'）")
    return probs


# --------------------------------------------------------------------------------------
# 负控用的坏秘书：每一只只改坏一处（判据本体一个字不动）
# --------------------------------------------------------------------------------------

class _AutoAccept(Secretary):
    """① 的负控：把"直接执行 washed"接回来（自动接受，不问父）。"""

    def plan_wash(self, *, original: Mapping[str, Any], wash: Mapping[str, Any],
                  accept: str = "", reject: str = "") -> dict[str, Any]:
        plan = super().plan_wash(original=original, wash=wash,
                                 accept=accept, reject=reject)
        if plan.get("issue"):
            plan.update(accepted=True, execute=dict(plan.get("washed") or {}),
                        executed_with="washed", proposal_id="auto", issue=False,
                        outcome="")
        return plan


class _AcceptStillOriginal(Secretary):
    """② 的负控：接受之后仍发 original —— 而且读数还谎称 washed。"""

    def plan_wash(self, *, original: Mapping[str, Any], wash: Mapping[str, Any],
                  accept: str = "", reject: str = "") -> dict[str, Any]:
        plan = super().plan_wash(original=original, wash=wash,
                                 accept=accept, reject=reject)
        if plan.get("accepted") is True:
            plan["execute"] = dict(plan.get("original") or {})
        return plan


class _RejectStillWashed(Secretary):
    """③ 的负控：拒绝之后仍发 washed（读数是 original）。"""

    def plan_wash(self, *, original: Mapping[str, Any], wash: Mapping[str, Any],
                  accept: str = "", reject: str = "") -> dict[str, Any]:
        plan = super().plan_wash(original=original, wash=wash,
                                 accept=accept, reject=reject)
        if plan.get("accepted") is False:
            plan["execute"] = dict(plan.get("washed") or {})
        return plan


class _ValueScrubber(Secretary):
    """④ 的负控：把"改值"混进洗函数（顺手把参数值去首尾空白）。"""

    def wash_delegation(self, shape: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        got = super().wash_delegation(shape, payload)
        out = dict(got.get("payload") or {})
        params = out.get("params")
        if isinstance(params, Mapping):
            fixed = {k: (v.strip() if isinstance(v, str) else v) for k, v in params.items()}
            if fixed != dict(params):
                out["params"] = fixed
                got = dict(got)
                got["payload"] = out
                got["washed"] = True
                got["changes"] = [*list(got.get("changes") or ()),
                                  {"where": "", "field": "params.statement_full",
                                   "why": "顺手去空白"}]
        return got

class _AlwaysProposes(Secretary):
    """⑤ 的负控：无差异也请示（多花一轮）。"""

    def plan_wash(self, *, original: Mapping[str, Any], wash: Mapping[str, Any],
                  accept: str = "", reject: str = "") -> dict[str, Any]:
        plan = super().plan_wash(original=original, wash=wash,
                                 accept=accept, reject=reject)
        if not plan.get("outcome") and plan.get("accepted") is None:
            plan.update(outcome=OUTCOME_WASH_PROPOSED, issue=True, proposal_id="W-fake-0001")
        return plan


def _secretary(tmp_path: pathlib.Path, cls: Any = Secretary) -> Any:
    """一只（可能是坏的）秘书：与生产同一套装配，只换类。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    st = Store(root)
    st.init()
    return cls("M", root=root, store=st, enable_model=False, sid=SID)


# --------------------------------------------------------------------------------------
# ① 有差异 ⇒ 不执行
# --------------------------------------------------------------------------------------

def test_a_wash_with_a_diff_does_not_dispatch_anything(tmp_path: pathlib.Path):
    """正控①：`washed != original` ⇒ 请示 + 编号 + diff，台账 0 行新任务、后端 0 次调用。"""
    got = _run(tmp_path)
    step = got["steps"][0]
    assert _proposal_problems(step, got["seen"], got["store"]) == []
    assert step["outcome"] == OUTCOME_WASH_PROPOSED, step
    # 编号由秘书发：形状是 `W-<role>-<实例>-<seq>`，不是模型/父能拼出来的
    assert step["proposal_id"].startswith("W-M-"), step["proposal_id"]
    # diff 只列改了哪几个键，且值一个都没变（这一条是 ④ 在请示读数上的同一件事）
    assert step["changed_keys"], step
    lines = [str(x) for x in step["changes"]]
    assert any("动作名 own.register_statement → register_statement" == x for x in lines), lines
    for line in step["diff"].values():
        if str(line.get("why") or "") in ("顶层折叠", "键名归一（唯一候选）",
                                          "顶层折算：键名归一（唯一候选）"):
            assert line.get("value_changed") is False, line


def test_negative_control_auto_accepting_the_wash_is_red(tmp_path: pathlib.Path):
    """负控①：改成"直接执行 washed" ⇒ 判据 ① 变红（证明它不是一条永远为真的断言）。"""
    got = _run(tmp_path, secretary=_secretary(tmp_path, _AutoAccept))
    step = got["steps"][0]
    probs = _proposal_problems(step, got["seen"], got["store"])
    assert probs, "自动接受也判绿 ⇒ ① 没有牙"
    assert any("真的派了子任务" in p or "真的调了后端" in p
               or "没有返回受控的请示读数" in p for p in probs), probs


# --------------------------------------------------------------------------------------
# ② 接受 ⇒ 用 washed 执行
# --------------------------------------------------------------------------------------

def test_accepting_the_proposal_dispatches_the_washed_payload(tmp_path: pathlib.Path):
    """正控②：`accept_proposal=<id>` ⇒ 子任务真的派出，且后端收到的那份就是 washed。"""
    got = _run(tmp_path, key=ACCEPT_PROPOSAL)
    proposal, step = got["steps"][0], got["steps"][1]
    assert _accept_problems(step, got["seen"], proposal) == []
    assert got["seen"][0]["params"]["statement_text"] == " 一个短名 ", got["seen"]
    assert "stmt_text" not in got["seen"][0]["params"], got["seen"]


def test_negative_control_accepting_but_sending_the_original_is_red(tmp_path: pathlib.Path):
    """负控②：接受后仍用 original ⇒ 判据 ② 变红（读数自报"用 washed"也救不了它）。"""
    got = _run(tmp_path, key=ACCEPT_PROPOSAL,
               secretary=_secretary(tmp_path, _AcceptStillOriginal))
    probs = _accept_problems(got["steps"][1], got["seen"], got["steps"][0])
    assert probs, "接受后发原稿也判绿 ⇒ ② 没有牙"
    assert any("不是 washed" in p for p in probs), probs


# --------------------------------------------------------------------------------------
# ③ 拒绝 ⇒ 用 original 执行
# --------------------------------------------------------------------------------------

def test_rejecting_the_proposal_dispatches_the_original(tmp_path: pathlib.Path):
    """正控③：`reject_proposal=<id>` ⇒ 实际参数等于 original、`accepted=false`、留痕。"""
    got = _run(tmp_path, key=REJECT_PROPOSAL)
    proposal, step = got["steps"][0], got["steps"][1]
    assert _reject_problems(step, got["seen"], proposal) == []
    # 原稿里那几处格式错的键原样留着（别名没被折算）—— 这就是"按原稿派出"的实证
    assert got["seen"][0]["params"].get("stmt_text") == " 一个短名 ", got["seen"]
    assert "statement_text" not in got["seen"][0]["params"], got["seen"]
    rows = [r for r in got["store"].rows("tasks") if str(r.get("role")) == "B"]
    assert [r for r in rows if str(r.get("action") or "") != "message"], rows
    # 留痕：台账里那一行逐字写着"拒绝了秘书的格式洗"，且带着同一个编号
    ledger = sorted((got["root"] / "out" / "secretary").glob("M-*.jsonl"))
    assert ledger, "秘书台账没落盘"
    lines = [json.loads(x) for p in ledger
             for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    rejected = [r for r in lines if str(r.get("decision") or "") == "拒绝了秘书的格式洗"]
    assert rejected, [r.get("decision") for r in lines]
    assert str(rejected[-1].get("proposal_id") or "") == str(proposal.get("proposal_id") or "")


def test_negative_control_rejecting_but_sending_the_washed_is_red(tmp_path: pathlib.Path):
    """负控③：拒绝后仍用 washed ⇒ 判据 ③ 变红。"""
    got = _run(tmp_path, key=REJECT_PROPOSAL,
               secretary=_secretary(tmp_path, _RejectStillWashed))
    probs = _reject_problems(got["steps"][1], got["seen"], got["steps"][0])
    assert probs, "拒绝后发洗过的那份也判绿 ⇒ ③ 没有牙"
    assert any("不是原稿" in p or "仍然发的是洗过的那份" in p for p in probs), probs


# --------------------------------------------------------------------------------------
# ④ 不越界（最要紧）
# --------------------------------------------------------------------------------------

def test_the_wash_moves_keys_and_never_touches_a_value(tmp_path: pathlib.Path):
    """正控④：洗出来的 `washed` 与 `original` 只有那几处格式差异，逐条断言。"""
    got = _run(tmp_path)
    plan = got["steps"][0]
    original, washed = dict(plan["original"]), dict(plan["washed"])
    assert _boundary_problems(original, washed) == [], plan["diff"]
    # 逐条：动作名被映成真名、别名键被折算
    assert original["action"] == "own.register_statement", original
    assert washed["action"] == "register_statement", washed
    assert original["params"] == {"stmt_text": " 一个短名 "}, original
    assert washed["params"] == {"statement_text": " 一个短名 "}, washed
    assert "stmt_text" not in washed["params"], washed
    # 没有增删参数：值的多重集合逐字相同（首尾空白也算逐字的一部分）
    assert sorted(map(str, _content_values(original))) == sorted(
        map(str, _content_values(washed))), (original, washed)
    # 正文逐字相同
    assert original["task"] == washed["task"] == BODY["task"], (original, washed)
    # `changed_keys` 只有那两处（动作名 + 别名键）
    assert sorted(plan["changed_keys"]) == sorted(
        ["action", "params.stmt_text"]), plan["changed_keys"]

    # ---- 第二段：顶层折叠（必填字段被摆在顶层）—— 直接打秘书的 API。
    # 为什么不走循环：派活形状的解码按"写对了的动作"查声明，而这一份的动作名是错的
    # ⇒ 顶层那一格在解码时就被丢掉（那是解码面的既有口径，与洗格式无关）。
    root = tmp_path / "fold"
    root.mkdir(parents=True, exist_ok=True)
    st = Store(root)
    st.init()
    sec = Secretary("M", root=root, store=st, sid=SID)
    hoisted = {**BODY, "statement_full": " 若 n=3 则 p "}
    wash = sec.wash_delegation("summon", dict(hoisted))
    assert wash["checked"] is True and wash["washed"] is True, wash
    folded = dict(wash.get("payload") or {})
    assert "statement_full" not in folded, folded           # 搬进 params 了
    assert folded["params"]["statement_full"] == " 若 n=3 则 p ", folded
    assert _boundary_problems(hoisted, folded) == [], folded
    reasons = {str(c.get("why") or "") for c in (wash.get("changes") or ())}
    assert "顶层折叠" in reasons, wash["changes"]


def test_negative_control_scrubbing_a_value_inside_the_wash_is_red(tmp_path: pathlib.Path):
    """负控④：把"改值"那条混进洗函数 ⇒ 判据 ④ 变红。"""
    sec = _secretary(tmp_path, _ValueScrubber)
    wash = sec.wash_delegation("summon", dict(BODY))
    probs = _boundary_problems(BODY, dict(wash.get("payload") or {}))
    assert probs, "改值也判绿 ⇒ ④ 没有牙"
    assert any("值不见了或被改了" in p for p in probs), probs


# --------------------------------------------------------------------------------------
# ⑤ 无差异不请示
# --------------------------------------------------------------------------------------

#: 无差异的一份派活：动作名对、`params` 的键都对、值都在 `params` 里（没有可洗的）。
CLEAN: dict[str, Any] = {
    "role": "B",
    "action": "register_statement",
    "task": "把这条命题入库",
    "params": {"statement_full": "若 n=3 则 p", "statement_text": "短名"},
    "why": "要一条能引的命题",
}

#: 一批派活（两段式对 `summon_many` 是同一份判据：一个载荷一份请示）。
MANY: dict[str, Any] = {
    "targets": [
        {"role": "B", "action": "own.register_statement",
         "params": {"stmt_text": " 一个短名 "}, "task": "把命题入库"},
        {"role": "B", "task": "把第二条也入库"},
    ],
}
MANY_LOOPS: dict[tuple[str, str], dict[str, Any]] = {("B", "register_statement"): {},
                                                     ("B", ""): {}}


def test_no_diff_executes_at_once_without_a_proposal(tmp_path: pathlib.Path):
    """正控⑤：`washed == original` ⇒ 直接执行、不产生 `wash_proposed`（不多花一轮）。"""
    got = _run(tmp_path, body=CLEAN)
    step = got["steps"][0]
    assert _no_diff_problems(step, got["store"]) == []
    assert step["ok"] is True, step
    assert _boundary_problems(CLEAN, CLEAN) == []


def test_negative_control_proposing_without_a_diff_is_red(tmp_path: pathlib.Path):
    """负控⑤：无差异也请示 ⇒ 判据 ⑤ 变红（证明它不会为"没差异"多花一轮）。"""
    got = _run(tmp_path, body=CLEAN, secretary=_secretary(tmp_path, _AlwaysProposes))
    probs = _no_diff_problems(got["steps"][0], got["store"])
    assert probs, "无差异也请示却判绿 ⇒ ⑤ 没有牙"
    assert any("无差异也请示" in p for p in probs), probs


# --------------------------------------------------------------------------------------
# 批量的那一支：两段式是同一份判据（`summon_many` 也要先请示、再按表态派）
# --------------------------------------------------------------------------------------

def test_a_batch_is_proposed_and_then_dispatched_washed(tmp_path: pathlib.Path):
    """`summon_many`：整批先请示（不派），接受之后整批按洗过的那份派出去。"""
    proposed = _run(tmp_path / "a", body=MANY, shape="summon_many", loops=MANY_LOOPS)
    step = proposed["steps"][0]
    assert _proposal_problems(step, proposed["seen"], proposed["store"]) == []
    assert proposed["seen"] == [], "整批请示时一次都不许派"
    assert any("targets[0]" in str(k) for k in step["changed_keys"]), step["changed_keys"]

    accepted = _run(tmp_path / "b", body=MANY, shape="summon_many", loops=MANY_LOOPS,
                    key=ACCEPT_PROPOSAL)
    last = accepted["steps"][1]
    audit = last.get("wash") or {}
    assert audit.get("accepted") is True and audit.get("executed_with") == "washed", last
    assert len(accepted["seen"]) == 2, accepted["seen"]
    assert accepted["seen"][0]["params"].get("statement_text") == " 一个短名 ", accepted["seen"]
    assert "stmt_text" not in accepted["seen"][0]["params"], accepted["seen"]


# --------------------------------------------------------------------------------------
# 可审计：编号与三份读数在会话事件里查得到（不另造表）
# --------------------------------------------------------------------------------------

def test_the_proposal_and_the_three_readings_are_on_the_session_events(tmp_path: pathlib.Path):
    """`proposal_id` 与 original/washed/accepted 在会话事件里可查（`agent_step` 那一格）。"""
    got = _run(tmp_path, key=ACCEPT_PROPOSAL)
    proposal, step = got["steps"][0], got["steps"][1]
    events, _bad = __import__("agentflow.jsonlfile", fromlist=["read_jsonl"]).read_jsonl(
        got["root"] / "sessions" / f"{SID}.jsonl")
    steps = [e for e in events
             if e.get("kind") == "agent_step" and str(e.get("role")) == "M"]
    assert steps, [e.get("kind") for e in events]
    blob = json.dumps([e.get("result") for e in steps], ensure_ascii=False, default=str)
    pid = str(proposal.get("proposal_id") or "")
    assert pid in blob, "请示编号不在会话事件里（父事后查不到）"
    assert "wash_proposed" in blob, "第一段的 outcome 不在会话事件里"
    assert '"accepted": true' in blob.replace("\n", ""), "执行那一刻的 accepted 不在会话事件里"
    assert step["wash"]["proposal_id"] == pid

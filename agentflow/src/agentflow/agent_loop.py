"""LLM 驱动的角色循环：模型决定调哪个工具、唤起谁、给谁留言，框架负责执行与留痕。

## 这一层补的是哪一个洞

`draft/28` §178 的实测：A-H 里六个角色一份提示词都没有，C 两处、D 一处钩子；
更根本的是，角色之间没有一条"由模型决定"的协作路径 —— `Conductor.summon`
是给编排层用的（`run_plan` 拿一份写死的计划去跑），而不是给模型用的。
于是"互相唤起"这件事在系统里从来没有发生过：它只发生在脚本里。

这一层把三件事接起来：

1. 提示词（`agent_prompts`）：模型知道自己有哪些工具、该做什么、能跟谁协作；
2. 模型缝（`llmseam`）：每次调用都带版本与哈希落档，没接线/超预算/坏 JSON 分得开；
3. 工具与召唤（`ToolRegistry.call` 与 `Conductor.summon`）：模型说的每个动作都过既有的
   权限面与策略闸门，被拒的理由原样回到模型手里。

## 四种形状（与提示词里的循环协议逐字对应）

- `{"tool": ...}`   → 走 `ToolRegistry.call(name, role=...)`，角色面不对就 `role_denied`；
- `{"summon": ...}` → 走 `Conductor.summon(..., by=<本角色>)`，边/深度/扇出/预算全由策略判；
- `{"message": ...}` → 追加一条 `agent_message` 事件（持久），收件人下次运行时在收件箱里看到；
- `{"final": ...}`  → 收工，带它自报的证据 id。

## 三态与"不许静默"

- 没接线（没有 key）：整个循环不发起任何请求，`stop_reason="not_wired"`，并落一条记录；
- 模型返回坏 JSON：计数，超过上限就停（`stop_reason="bad_json_limit"`），不静默当空；
- 工具被拒 / 召唤被拒：结果里带原因码，并且原样回给模型（那是一次纠正，不是失败）；
- 步数或预算耗尽：停，并把 `stop_reason` 如实写进运行记录。

## 消息传递的投递语义

消息落进项目会话记录（`sessions.append`，不新增表）。收件人"读过哪些"用一个
`agent_inbox` 事件登记（append-only）：某条消息只要出现在过任何一条针对该角色的
`agent_inbox` 事件里，就算已投递。于是"投递"是可复算的，而不是靠内存里的一个集合。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import agent_prompts as AP
from . import capabilities as C
from . import schema as S
from . import sessions as SS
from .llmseam import LlmSeam

#: 循环允许的形状（与 `LOOP_PROTOCOL` 逐字对应；多一个少一个都要改两处）。
SHAPES = ("tool", "summon", "message", "note", "final")

#: 公共频道。`message.to` 写它 = 所有人都能收到（说话，而不是派活）。
PUBLIC = "#public"

#: 草稿本目录名：`<项目根>/notes/<角色>.md`。它刻意不在数据面里 ——
#: 于是只读角色（C / H）也能"有手"：写自己的思考不算写数据。
NOTES_DIR_NAME = "notes"

#: 子循环的完整产出落点：`<项目根>/runs/<角色>-<时间戳>-<序号>.json`。
#:
#: 为什么必须落盘而不是塞进召唤结果：真机实测（2026-09-29）M 拿到的 D 的结论被摘要截断，
#: 于是它只能发留言去问 D"把结论正文回传" —— 而 D 的循环早已结束，问也问不回来。
#: 正确做法是把长产出放磁盘、把路径给上游：上游有眼睛（fs.read），自己去读全文。
RUNS_DIR_NAME = "runs"

#: 单个工具结果回给模型时的字符上限（超了截断并写明截了多少）。
RESULT_CHARS = 1200


def _clip(value: Any, limit: int = RESULT_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + f"…（原文 {len(text)} 字，已截断）"


@dataclass(frozen=True)
class LoopStep:
    """循环里的一步：模型说了什么、框架做了什么、结果是什么。"""

    index: int
    shape: str
    payload: Mapping[str, Any]
    result: Mapping[str, Any]
    problem: str = ""

    def to_dict(self) -> dict[str, Any]:
        """落会话记录用的扁平结构（模型说了什么、框架做了什么、结果是什么）。"""
        return {"index": self.index, "shape": self.shape, "payload": dict(self.payload),
                "result": dict(self.result), "problem": self.problem}


@dataclass
class LoopRun:
    """一次角色运行的完整记录（含每一步与提示词审计读数）。"""

    role: str
    task: str
    steps: list[LoopStep] = field(default_factory=list)
    final: str = ""
    evidence: list[str] = field(default_factory=list)
    stop_reason: str = "final"
    prompt_audit: dict[str, Any] = field(default_factory=dict)
    spend: dict[str, Any] = field(default_factory=dict)
    bad_json: int = 0
    elapsed_sec: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def summons(self) -> list[str]:
        """这次运行真的唤起过哪些角色（按发生顺序，可重复）。"""
        return [str(s.payload.get("role") or "") for s in self.steps if s.shape == "summon"]

    @property
    def messages_sent(self) -> list[str]:
        """这次运行给谁发过留言（按发生顺序，可重复）。"""
        return [str(s.payload.get("to") or "") for s in self.steps if s.shape == "message"]

    def to_dict(self) -> dict[str, Any]:
        """一次运行的完整记录（每一步 + 提示词审计 + 用量 + 停止原因）。"""
        return {
            "role": self.role, "task": self.task,
            "steps": [s.to_dict() for s in self.steps],
            "final": self.final, "evidence": list(self.evidence),
            "stop_reason": self.stop_reason, "bad_json": self.bad_json,
            "summons": self.summons, "messages_sent": self.messages_sent,
            "prompt_audit": dict(self.prompt_audit), "spend": dict(self.spend),
            "elapsed_sec": round(self.elapsed_sec, 3), "notes": list(self.notes),
        }


# ------------------------------------------------------------------ 消息
def read_messages(session_root: Path, role: str, *, sid: str | None = None,
                  ) -> tuple[list[dict[str, Any]], list[str]]:
    """读某个角色的收件箱（含未投递标记）。返回 `(消息, 问题)`。"""
    events, problems = SS.read_session(session_root, sid=sid)
    delivered: set[str] = set()
    for event in events:
        if event.get("kind") == "agent_inbox" and str(event.get("role")) == role:
            delivered.update(str(x) for x in (event.get("delivered") or []))
    out: list[dict[str, Any]] = []
    for i, event in enumerate(events, 1):
        if event.get("kind") != "agent_message":
            continue
        to = str(event.get("to"))
        if to != role and to != PUBLIC:
            continue
        if str(event.get("from")) == role:
            continue                     # 自己说的不用再听一遍
        msg_id = str(event.get("msg_id") or f"m{i:04d}")
        out.append({**event, "msg_id": msg_id, "delivered": msg_id in delivered})
    return out, problems


def send_message(session_root: Path, *, sender: str, to: str, subject: str, body: str,
                 reply_to: str = "", sid: str | None = None) -> tuple[str, str]:
    """发一条消息（append-only）。`to=PUBLIC` 是公共频道。返回 `(msg_id, 问题)`。"""
    events, _problems = SS.read_session(session_root, sid=sid)
    seq = sum(1 for e in events if e.get("kind") == "agent_message") + 1
    msg_id = f"m{seq:04d}"
    _path, problem = SS.append(session_root, {
        "kind": "agent_message", "msg_id": msg_id, "from": sender, "to": to,
        "subject": subject, "body": body, "reply_to": reply_to,
        "channel": "public" if to == PUBLIC else "private",
    }, sid=sid)
    return msg_id, problem


def mark_delivered(session_root: Path, role: str, ids: Sequence[str], *,
                   sid: str | None = None) -> str:
    """登记"这些消息已经在这个角色的收件箱里投递过"。返回问题（空串 = 落成）。"""
    if not ids:
        return ""
    _path, problem = SS.append(session_root, {
        "kind": "agent_inbox", "role": role, "delivered": sorted(set(ids)),
    }, sid=sid)
    return problem


def note_path(session_root: Path, role: str) -> Path:
    """这个角色的草稿本路径：`<项目根>/notes/<角色>.md`。"""
    return session_root / NOTES_DIR_NAME / f"{role}.md"


def write_note(session_root: Path, role: str, text: str, *,
               sid: str | None = None) -> tuple[str, str]:
    """往草稿本追加一行。返回 `(路径, 问题)`；问题非空表示没写成。"""
    path = note_path(session_root, role)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"- [{stamp}] {text.strip()}\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
    except OSError as exc:
        return str(path), f"{type(exc).__name__}: {exc}"
    _p, problem = SS.append(session_root, {"kind": "agent_note", "role": role,
                                           "text": text.strip(), "path": str(path)}, sid=sid)
    return str(path), problem


def notebook_digest(session_root: Path, role: str, limit: int = 6) -> str:
    """草稿本最近几条（进提示词，让"我上一步想过什么"不必靠记忆）。"""
    path = note_path(session_root, role)
    if not path.is_file():
        return "（草稿本还是空的）"
    try:
        lines = [ln.rstrip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError as exc:
        return f"（草稿本读不出来：{type(exc).__name__}: {exc}）"
    return "\n".join(lines[-limit:]) if lines else "（草稿本还是空的）"


def inbox_digest(session_root: Path, role: str, *, sid: str | None = None) -> tuple[str, list[str], list[str]]:
    """收件箱摘要：`(文本, 未投递的 id, 读会话时的问题)`。"""
    messages, problems = read_messages(session_root, role, sid=sid)
    fresh = [m for m in messages if not m.get("delivered")]
    if not messages:
        return "（没有收到留言）", [], problems
    lines: list[str] = []
    for m in messages[-8:]:
        mark = "" if m.get("delivered") else "（新）"
        lines.append(f"- {mark}[{m['msg_id']}] 来自 {m.get('from')}：{m.get('subject')} —— "
                     f"{_clip(m.get('body'), 300)}")
    return "\n".join(lines), [str(m["msg_id"]) for m in fresh], problems


# ------------------------------------------------------------------ 循环
def _shape_of(data: Mapping[str, Any]) -> tuple[str, Mapping[str, Any], str]:
    """把模型的一句输出判成一个形状。判不出来时返回 `("", {}, 原因)`。"""
    present = [k for k in SHAPES if k in data]
    if len(present) != 1:
        return "", {}, (f"一次只能说一件事：同时出现 {present}" if present
                        else f"认不出的形状（键：{sorted(data)}）")
    key = present[0]
    value = data[key]
    if key == "tool":
        if not isinstance(value, str) or not value:
            return "", {}, "tool 必须是一个工具名字符串"
        args = data.get("args") or {}
        if not isinstance(args, Mapping):
            return "", {}, "args 必须是一个对象"
        return key, {"name": value, "args": dict(args), "why": str(data.get("why") or "")}, ""
    if key == "summon":
        if not isinstance(value, Mapping):
            return "", {}, "summon 必须是一个对象"
        role = str(value.get("role") or "")
        action = str(value.get("action") or "")
        if role not in S.ROLES:
            return "", {}, f"角色名 {role!r} 不在 {S.ROLES} 里"
        params = value.get("params") or {}
        if not isinstance(params, Mapping):
            return "", {}, "summon.params 必须是一个对象"
        return key, {"role": role, "action": action, "params": dict(params),
                     "why": str(value.get("why") or "")}, ""
    if key == "note":
        text = value if isinstance(value, str) else str((value or {}).get("text") or "")
        if not text.strip():
            return "", {}, "note 得有一句话可写"
        return key, {"text": text.strip()}, ""
    if key == "message":
        if not isinstance(value, Mapping):
            return "", {}, "message 必须是一个对象"
        to = str(value.get("to") or "")
        if to != PUBLIC and to not in S.ROLES:
            return "", {}, f"收件人 {to!r} 既不是角色也不是 {PUBLIC}"
        return key, {"to": to, "subject": str(value.get("subject") or "（无标题）"),
                     "body": str(value.get("body") or ""),
                     "reply_to": str(value.get("reply_to") or "")}, ""
    final = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return key, {"final": final, "evidence": [str(x) for x in (data.get("evidence") or [])]}, ""


@dataclass
class AgentLoop:
    """一个角色的一次循环。跑完即弃（没有可复用的状态，避免两次运行互相污染）。"""

    role: str
    session_root: Path
    registry: Any
    seam: LlmSeam
    conductor: Any = None
    max_steps: int = 6
    max_bad_json: int = 2
    workspace_root: str = ""
    sid: str | None = None
    token: Any = None
    store: Any = None
    #: 本次运行自己的台账号与深度（由 `run` 设置）。唤起下一环时必须把它当 parent 传下去，
    #: 否则链条在台账里会断成两段互不相干的记录。
    my_task_id: str = ""
    depth: int = 1

    def _prompt(self, transcript: str, *, step: int) -> str:
        last = step >= self.max_steps - 1
        tail = ("这是最后一步：不要再调用工具、不要再唤起伙伴，直接输出 "
                '{"final": "<结论>", "evidence": [...]}。' if last else
                "请按循环协议输出下一步（一个 JSON 对象，四种形状取其一）。")
        return (f"{transcript}\n\n---\n现在是第 {step + 1} 步（最多 {self.max_steps} 步）。{tail}\n"
                f"剩余花销预算：{self._budget_text()}")

    def _availability(self) -> dict[str, str] | None:
        """现在的接线态（哪个伙伴真的能被唤起）。拿不到就返回 None 并留一条 note。"""
        if self.store is None:
            return None
        try:
            from .host import wiring_status

            return dict(wiring_status(self.store, workspace_root=self.workspace_root))
        except Exception as exc:
            return None

    def _hear(self) -> list[dict[str, Any]]:
        """听一次新消息：把这次运行期间新到的消息取出来并登记投递。"""
        digest, fresh, problems = inbox_digest(self.session_root, self.role, sid=self.sid)
        if not fresh:
            return []
        problem = mark_delivered(self.session_root, self.role, fresh, sid=self.sid)
        heard: list[dict[str, Any]] = []
        messages, _ = read_messages(self.session_root, self.role, sid=self.sid)
        for m in messages:
            if str(m.get("msg_id")) in fresh:
                heard.append({"id": m.get("msg_id"), "from": m.get("from"),
                              "channel": m.get("channel"), "subject": m.get("subject"),
                              "body": _clip(m.get("body"), 400)})
        if problem:
            heard.append({"投递登记失败": problem})
        return heard

    def _budget_text(self) -> str:
        if self.seam.usd_budget is None:
            return f"未设置上限（已用 {self.seam.spend.usd:.6f} 美元）"
        left = max(0.0, self.seam.usd_budget - self.seam.spend.usd)
        return f"{left:.6f} 美元（上限 {self.seam.usd_budget:.6f}）"

    def run(self, task: str, *, summoned_by: str = "", my_task_id: str = "",
            depth: int = 1) -> LoopRun:
        """跑一次循环。`task` 是这次要做的事（被召唤时就是调用方给的参数）。"""
        t0 = time.monotonic()
        self.my_task_id = my_task_id
        self.depth = depth
        inbox, fresh_ids, inbox_problems = inbox_digest(self.session_root, self.role, sid=self.sid)
        notebook = notebook_digest(self.session_root, self.role)
        run = LoopRun(role=self.role, task=task)
        run.notes.extend(f"收件箱读取：{p}" for p in inbox_problems)
        if fresh_ids:
            problem = mark_delivered(self.session_root, self.role, fresh_ids, sid=self.sid)
            if problem:
                run.notes.append(f"投递登记失败：{problem}")

        availability = self._availability()
        facts = dict(task=task, summoned_by=summoned_by, task_id=my_task_id, depth=depth,
                     budget_left=self._budget_text(), inbox=inbox,
                     workspace_root=self.workspace_root, availability=availability,
                     notebook=notebook)
        run.prompt_audit = AP.prompt_audit(self.role, registry=self.registry, **facts)
        system = AP.system_prompt(self.role, registry=self.registry, **facts)
        transcript = (f"你的任务：{task}\n\n"
                      f"你的收件箱：{inbox}\n\n"
                      f"你的处境：由 {summoned_by or '（顶层发起）'} 发起，"
                      f"召唤链深度 {depth}，台账号 {my_task_id or '（本次运行未拿到台账号）'}。")

        SS.append(self.session_root, {
            "kind": "agent_run_start", "role": self.role, "task": task,
            "summoned_by": summoned_by, "task_id": my_task_id, "depth": depth,
            "prompt_version": run.prompt_audit.get("prompt_version"),
            "prompt_sha256": run.prompt_audit.get("prompt_sha256"),
        }, sid=self.sid)

        for step in range(self.max_steps):
            if self.seam.usd_budget is not None and self.seam.spend.usd >= self.seam.usd_budget:
                run.stop_reason = "budget"
                run.final = run.final or "预算已耗尽，停止（没有继续调用模型）"
                break
            data, call = self.seam.ask_json(self._prompt(transcript, step=step),
                                           system=system, task_id=my_task_id,
                                           note=f"{self.role}.step{step}")
            if data is None:
                run.bad_json += 1
                run.steps.append(LoopStep(step, "invalid", {}, {"problem": call.problem},
                                          problem=call.problem))
                if call.problem == "judge_not_wired":
                    run.stop_reason = "not_wired"
                    run.final = ("没有接模型（judge_not_wired）：这次运行没有产生任何判断，"
                                 "也没有写任何数据")
                    break
                if run.bad_json > self.max_bad_json:
                    run.stop_reason = "bad_json_limit"
                    run.final = (f"连续 {run.bad_json} 次没有给出可解析的 JSON"
                                 f"（最后一次：{call.problem}），停止")
                    break
                transcript += (f"\n\n[第 {step + 1} 步] 框架：你上一条回复不是可解析的 JSON 对象"
                               f"（{call.problem}）。请只输出一个 JSON 对象，四种形状取其一。")
                continue
            shape, payload, problem = _shape_of(data)
            if problem:
                run.bad_json += 1
                run.steps.append(LoopStep(step, "invalid", payload, {"problem": problem},
                                          problem=problem))
                if run.bad_json > self.max_bad_json:
                    run.stop_reason = "bad_json_limit"
                    run.final = f"连续 {run.bad_json} 次形状不合法（最后一次：{problem}），停止"
                    break
                transcript += f"\n\n[第 {step + 1} 步] 框架：{problem}。请按循环协议重说一次。"
                continue
            if shape == "final":
                run.final = str(payload.get("final") or "")
                run.evidence = list(payload.get("evidence") or [])
                run.steps.append(LoopStep(step, shape, payload, {}))
                run.stop_reason = "final"
                break
            result = self._execute(shape, payload)
            # 耳朵一直开着：这一步做完先听一次新消息，把它并进这一步的结果里
            # （并进结果而不是只并进 transcript：台账与会话记录要能看到"他当时听到了什么"）。
            heard = self._hear()
            if heard:
                result = {**result, "新消息": heard}
            step_obj = LoopStep(step, shape, payload, result)
            run.steps.append(step_obj)
            SS.append(self.session_root, {
                "kind": "agent_step", "role": self.role, "index": step, "shape": shape,
                "payload": dict(payload), "result": dict(result),
            }, sid=self.sid)
            transcript += (f"\n\n[第 {step + 1} 步] 你说了：{_clip(payload, 400)}\n"
                           f"框架执行结果：{_clip(result)}")
        else:
            run.stop_reason = "max_steps"
            run.final = run.final or f"步数用尽（{self.max_steps} 步）仍未给出 final"

        run.spend = self.seam.spend.to_dict()
        run.elapsed_sec = time.monotonic() - t0
        SS.append(self.session_root, {
            "kind": "agent_run_end", "role": self.role, "stop_reason": run.stop_reason,
            "steps": len(run.steps), "summons": run.summons, "messages": run.messages_sent,
            "final_chars": len(run.final), "spend": dict(run.spend),
            "elapsed_sec": round(run.elapsed_sec, 3),
        }, sid=self.sid)
        return run

    # -------------------------------------------------------------- 执行
    def _execute(self, shape: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if shape == "tool":
            return self._do_tool(payload)
        if shape == "summon":
            return self._do_summon(payload)
        if shape == "note":
            return self._do_note(payload)
        return self._do_message(payload)

    def _do_tool(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name"))
        args = dict(payload.get("args") or {})
        try:
            res = self.registry.call(name, role=self.role, **args)
        except Exception as exc:  # 工具层抛错也要变成"模型看得见的结果"
            return {"tool": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"tool": name, "ok": bool(res.ok), "data": _clip(res.data),
                "error": res.error or "", "meta": dict(res.meta or {})}

    def _do_summon(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        role = str(payload.get("role"))
        action = str(payload.get("action"))
        out: dict[str, Any] = {"summoned": role, "action": action}
        if self.conductor is None:
            out.update(ok=False, error="本次运行没有接线主控（summon 不可用）")
            return out
        if self.token is not None and getattr(self.token, "cancelled", False):
            out.update(ok=False, error="取消信号已置位：不再发起新的召唤")
            return out
        budget: Mapping[str, Any] | None = None
        if self.seam.usd_budget is not None:
            budget = {"usd": max(0.0, self.seam.usd_budget - self.seam.spend.usd)}
        try:
            res = self.conductor.summon(role, action, dict(payload.get("params") or {}),
                                        by=self.role, parent_task_id=self.my_task_id or None,
                                        budget=budget, token=self.token)
        except Exception as exc:
            out.update(ok=False, error=f"{type(exc).__name__}: {exc}")
            return out
        payload = res.payload
        path = str(payload.get("llm_run_path") or "") if isinstance(payload, Mapping) else ""
        out.update(
            ok=bool(res.ok), task_id=res.task_id, status=res.status, outcome=res.outcome,
            refusal_reason=res.refusal_reason, detail=_clip(res.detail, 400),
            children=list(res.children or []),
        )
        if path:
            # 伙伴是 LLM 循环驱动的：它的完整产出在磁盘上，这里只给路径 + 一段结论。
            out["llm_run_path"] = path
            out["final"] = _clip(payload.get("final") or "", 600)
            out["payload"] = _clip({k: v for k, v in payload.items() if k != "llm_run"}, 400)
        else:
            out["payload"] = _clip(payload, 800)
        return out

    def _do_message(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        to = str(payload.get("to"))
        reply_to = str(payload.get("reply_to") or "")
        if to != PUBLIC:
            allowed = (to in AP.partners_out(self.role) or self.role in AP.partners_out(to)
                       or bool(reply_to))
            if not allowed:
                return {"message": "未发出", "to": to, "ok": False,
                        "error": f"{self.role} 与 {to} 之间没有协作边（{self.role} 能叫的是 "
                                 f"{sorted(AP.partners_out(self.role))}）⇒ 私聊不成立；"
                                 f"要么发到公共频道（to={PUBLIC}），要么先公开开口。"}
        msg_id, problem = send_message(self.session_root, sender=self.role, to=to,
                                       subject=str(payload.get("subject") or ""),
                                       body=str(payload.get("body") or ""),
                                       reply_to=reply_to, sid=self.sid)
        if problem:
            return {"message": "未发出", "to": to, "ok": False, "error": problem}
        where = "公共频道" if to == PUBLIC else f"给 {to} 的私聊"
        return {"message_sent": msg_id, "to": to, "channel": where, "ok": True,
                "note": "收件人下次运行时（或本步之后）会在收件箱里看到它"}

    def _do_note(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        path, problem = write_note(self.session_root, self.role,
                                   str(payload.get("text") or ""), sid=self.sid)
        if problem:
            return {"note": "没写成", "ok": False, "error": problem}
        return {"note_written": path, "ok": True}


# ------------------------------------------------------------------ 后端
@dataclass
class LlmBackend:
    """把登记过的 (角色, 动作) 交给 LLM 循环，其余交给内层后端（`LocalBackend`）。

    为什么要"按动作登记"而不是"整个角色交给模型"：角色的确定性动作（算图、分配号、
    落一行表）不该被模型取代 —— 那正是本仓库反复守的那条线（模型只做语义判断）。
    于是接线表显式列出哪些动作由模型驱动，其余照旧走 Python 实现。
    """

    inner: Any
    loops: Mapping[tuple[str, str], Mapping[str, Any]]
    session_root: Path
    registry: Any = None
    conductor: Any = None
    seam_factory: Any = None
    max_steps: int = 6
    workspace_root: str = ""
    sid: str | None = None
    store: Any = None
    name = "llm"

    def known_roles(self) -> list[str]:
        """能接活儿的角色（模型驱动的那些 + 内层后端登记的那些）。"""
        return sorted({role for role, _action in self.loops} | set(self.inner.known_roles()))

    def resolve(self, role: str) -> Any:
        """本后端不提供实例（它按动作决定走哪条路），把问题交给内层。"""
        return self.inner.resolve(role)

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: Any) -> Any:
        """登记过的 `(角色, 动作)` 走 LLM 循环；其余交给内层后端（确定性实现）。"""
        cfg = self.loops.get((role, action))
        if cfg is None:
            return self.inner.call(role, action, params, token=token)
        seam = self._seam(role)
        loop = AgentLoop(role=role, session_root=self.session_root, registry=self.registry,
                         seam=seam, conductor=self.conductor, max_steps=int(cfg.get("max_steps", self.max_steps)),
                         workspace_root=self.workspace_root, sid=self.sid, token=token,
                         store=self.store)
        run = loop.run(str(cfg.get("task_from_params") or "") or _task_text(params, role, action),
                       summoned_by=str(params.get("_summoned_by") or S.CONDUCTOR_ROLE),
                       my_task_id=str(params.get("_task_id") or self._lookup_task_id(role)),
                       depth=int(params.get("_depth") or 1))
        artifact = self._write_run_artifact(role, run)
        SS.append(self.session_root, {"kind": "agent_run_artifact", "role": role,
                                      "path": artifact, "stop_reason": run.stop_reason,
                                      "task_id": run.prompt_audit.get("task_id", "")}, sid=self.sid)
        out = {"llm_run_path": artifact, "final": run.final, "stop_reason": run.stop_reason,
               "steps": len(run.steps), "summons": run.summons, "messages": run.messages_sent}
        if not artifact:
            out["llm_run"] = run.to_dict()      # 落盘失败时退回内联，绝不静默丢产出
        return out

    def _seam(self, role: str) -> LlmSeam:
        if self.seam_factory is not None:
            return self.seam_factory(role)
        raise RuntimeError("LlmBackend 需要 seam_factory（一个按角色造模型缝的调用方）")

    def _write_run_artifact(self, role: str, run: LoopRun) -> str:
        """把这次循环的完整记录写成文件，返回路径（失败就返回空串并留 note）。"""
        try:
            d = self.session_root / RUNS_DIR_NAME
            d.mkdir(parents=True, exist_ok=True)
            n = len(list(d.glob(f"{role}-*.json"))) + 1
            path = d / f"{role}-{time.strftime('%Y%m%d-%H%M%S')}-{n:03d}.json"
            path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
            return str(path)
        except OSError as exc:
            run.notes.append(f"产出落盘失败：{type(exc).__name__}: {exc}")
            return ""

    def _lookup_task_id(self, role: str) -> str:
        """从台账里找出"刚刚为这个角色写下的那条 running 行"。

        为什么要找而不是让调用方传：`Conductor.summon` 先写 running 行、再调后端，
        所以后端天然不知道自己的台账号。找得到就用；找不到或有歧义就返回空串
        （提示词里会如实写"本次运行未拿到台账号"），绝不猜一个号 ——
        猜错会让两个任务的记录混在一起，而那是审计面最贵的错。
        """
        store = self.store
        if store is None:
            return ""
        try:
            rows = [r for r in store.rows("tasks")
                    if str(r.get("role")) == role and str(r.get("status")) == "running"]
        except Exception:
            return ""
        if len(rows) != 1:
            return ""
        return str(rows[0].get("task_id") or "")


def _task_text(params: Mapping[str, Any], role: str, action: str) -> str:
    """把召唤参数渲染成给孩子看的任务描述（没有参数时如实说明）。"""
    given = {k: v for k, v in (params or {}).items() if not str(k).startswith("_")}
    if not given:
        return f"{role}.{action}：这次没有带参数（调用方只要求你按职责做这件事）。"
    return (f"{role}.{action}：调用方给了这些参数：\n"
            + "\n".join(f"- {k}：{_clip(v, 400)}" for k, v in given.items()))


def run_role(role: str, task: str, *, store: Any, registry: Any,
             session_root: Path | str | None = None,
             conductor: Any = None, seam: LlmSeam | None = None, gateway: Any | None = None,
             max_steps: int = 6, usd_budget: float | None = None,
             workspace_root: str = "", sid: str | None = None, token: Any = None,
             from_env: bool = True) -> LoopRun:
    """跑一个角色的一次循环（真机或替身都走这一条）。

    `session_root` 不给时取 `store.root`：会话记录的落点就该是项目根，
    两处分开写迟早会出现"审计记录落在别处"的静默错位。
    """
    root = Path(session_root) if session_root is not None else Path(str(getattr(store, "root", "")))
    if not str(root):
        raise ValueError("run_role 需要 session_root，或一个带 root 的 store")
    if seam is None:
        seam = LlmSeam.for_role(role, session_root=root, gateway=gateway,
                                usd_budget=usd_budget, sid=sid, from_env=from_env)
    loop = AgentLoop(role=role, session_root=root, registry=registry, seam=seam,
                     conductor=conductor, max_steps=max_steps, workspace_root=workspace_root,
                     sid=sid, token=token, store=store)
    return loop.run(task, summoned_by=(S.CONDUCTOR_ROLE if role == S.CONDUCTOR_ROLE else ""),
                    my_task_id="", depth=1 if role == S.CONDUCTOR_ROLE else 2)


def selftest() -> int:
    """自检：形状判定与收件箱（不需要模型、不需要网络）。"""
    problems: list[str] = []

    def check(ok: bool, what: str) -> None:
        """记一条自检结论（不通过就写进 problems，供最后统一打印）。"""
        if not ok:
            problems.append(what)

    shape, payload, problem = _shape_of({"tool": "graph.stats", "args": {}})
    check((shape, problem) == ("tool", ""), f"tool 形状判错：{shape}/{problem}")
    check(payload.get("name") == "graph.stats", "tool 名字没取到")
    shape, _p, problem = _shape_of({"summon": {"role": "E", "action": "run_experiment"}})
    check((shape, problem) == ("summon", ""), f"summon 形状判错：{shape}/{problem}")
    shape, _p, problem = _shape_of({"summon": {"role": "Z", "action": "x"}})
    check(shape == "" and "不在" in problem, "不存在的角色没有被拒")
    shape, _p, problem = _shape_of({"tool": "a", "final": "b"})
    check(shape == "" and "一次只能说一件事" in problem, "两种形状同时出现没有被拒")
    shape, payload, problem = _shape_of({"final": "做完了", "evidence": ["c-0001"]})
    check((shape, problem) == ("final", "") and payload["evidence"] == ["c-0001"],
          "final 形状判错")

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        msg_id, problem = send_message(root, sender="M", to="D", subject="任务", body="看一下这个")
        check(problem == "" and msg_id == "m0001", f"发消息失败：{msg_id}/{problem}")
        digest, fresh, problems_ = inbox_digest(root, "D", sid=SS.session_id())
        check("看一下这个" in digest and fresh == ["m0001"], f"收件箱没读到：{digest!r}/{fresh}")
        check(not problems_, f"读会话时报了问题：{problems_}")
        mark_delivered(root, "D", fresh, sid=SS.session_id())
        digest2, fresh2, _ = inbox_digest(root, "D", sid=SS.session_id())
        check(fresh2 == [] and "（新）" not in digest2, "投递登记没有生效")
        other, fresh_other, _ = inbox_digest(root, "E", sid=SS.session_id())
        check("（没有收到留言）" == other and fresh_other == [], "别人的留言跑进了 E 的收件箱")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（四种形状 + 消息投递与隔离）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())

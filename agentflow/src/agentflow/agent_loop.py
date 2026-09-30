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
from . import userio as U
from .llmseam import LlmSeam

#: 循环允许的形状（与 `LOOP_PROTOCOL` 逐字对应；多一个少一个都要改两处）。
SHAPES = ("tool", "summon", "message", "note", "ask_user", "final")

#: 这些拒绝理由 ⇒ 自动转成"请主控代唤"的申请（2026-09-30）。
#:
#: `forbidden_edge`：目标不在 `capabilities.ALLOWED_EDGES` 里（例如 G 想找 A 要文献）；
#: `depth_exceeded`：召唤链已经到 `policy.max_depth`。两者都是"这条路今天不通"，
#: 而不是"我参数写错了" —— 参数错（`invalid_params`）该自己改，越权不该重试。
RELAY_REFUSALS: frozenset[str] = frozenset({"forbidden_edge", "depth_exceeded"})

#: 代唤申请的留言标题（机器可识别的那一位；改它要同时改提示词里的同一句）。
RELAY_SUBJECT = "请代唤"

#: 每一步最后读到的那段输出契约（`draft/28` §195）。
#:
#: 为什么要在最后一行重述一遍：系统提示词有 6k+ token，循环协议埋在中间；
#: 真机实测（2026-09-30，M 做"核验定理与引理的证明"）—— 模型连着三次回 1400–2400 字的散文，
#: `judge_bad_json` × 3 ⇒ `bad_json_limit`，那次运行对交付物零贡献。
#: 它不是不听指令，是没读到：中间那句"请只输出一个 JSON 对象"离它的回答太远了。
JSON_TAIL = (
    "只回一行 JSON（不要解释、不要 Markdown 围栏、不要前后缀）。形状取其一"
    "（键名与嵌套层级照抄，`<...>` 是占位符）：\n"
    '{"tool": "<工具名>", "args": {...}}\n'
    '{"summon": {"role": "A-H", "action": "<动作名>", "params": {...}}}\n'
    '{"message": {"to": "<伙伴或 #public>", "subject": "...", "body": "..."}}\n'
    '{"note": "一句话"}\n'
    '{"ask_user": {"question": "...", "options": ["..."]}}\n'
    '{"final": {"final": "<结论>", "evidence": []}}'
)

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

#: 单个工具结果回给模型时的字符上限（超了按字段截断并写明截了多少）。#:
#: 1200 → 3000 是 2026-09-30 的真机读数逼出来的：三次运行里模型自己的抱怨逐字都是
#: "读数被观测层截断" —— 验收表 10 行、24 条断言台账、253 条 findings，没有一件
#: 装得进 1200 字，于是它把步数花在"换个姿势再读一遍"上。观测窗口比任务需要的读数小，
#: 表现不是"模型笨"，而是"它反复做同一件事"。
RESULT_CHARS = 3000
#: 模型自己那一步说了什么，回显时的上限（够长到能看见自己给的参数没被截成半截路径）。
ECHO_CHARS = 600


def _clip(value: Any, limit: int = RESULT_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + f"…（原文 {len(text)} 字，已截断）"


#: 观测层渲染单个字段时的下限（给最短的那个字段也不能给到 0 字）。
FIELD_CHARS_MIN = 120
#: 落进"审计记录/台账"的字符串上限。观测层给模型看的是预算内的视图，
#: 而记录要的是"他当时到底拿到了什么" —— 这个上限只防"一屏数据把会话文件撑爆"。
RECORD_CHARS = 2000


def _flatten_one_level(result: Mapping[str, Any]) -> dict[str, Any]:
    """把工具结果里那一层 `data` 字典摊平（`data.rows` 这样带前缀）。

    为什么要摊平：工具的 `data` 常常是一个十几个键的字典，而"按字段分配预算"
    只有在这一层才谈得上。摊平之前 `data` 是一个字段，它的尾巴（真机里正是
    `documents` 那一栏 —— 验收表背后的 doc_id）会被整段切掉，而切掉的部分
    恰好是"下一步该派谁"的读数。
    """
    top = list(result.items())
    flat: dict[str, Any] = {}
    for key, value in top:
        if isinstance(value, Mapping) and len(value) > 1:
            for sub, inner in value.items():
                flat[f"{key}.{sub}"] = inner
        else:
            flat[key] = value
    return flat


def _clip_fields(result: Mapping[str, Any], limit: int = RESULT_CHARS) -> str:
    """把一步的结果渲染出来，但逐字段限长，而不是整体切掉尾部。

    为什么不是 `_clip(result)`：真机实测（2026-09-30）E 拿到的是 17849 字节台账的前 1200 字，
    而 `meta`（里面有 `total_bytes` / 续读位置）与同批到达的 `新消息` 都在 JSON 的尾部，
    整体截断正好把它们切掉 ⇒ 模型只知道"内容很长"，不知道"怎么读剩下的"，
    于是连续 14 步重读同一个开头。逐字段限长保证每个键都在，代价是每个键都短一点。

    预算按"便宜的先给满、贵的再平分"来分，而不是等分：等分在两头都错 ——
    一个 `data` 独大的结果（`fs.read`）会被压到 1/5，而十几个键的结果（验收表）
    会把每一栏都压成 120 字。这里先让"放得下的小字段"整份通过，剩下的额度再给大字段平分。
    """
    flat = _flatten_one_level(result or {})
    rendered = {key: (value if isinstance(value, str)
                      else json.dumps(value, ensure_ascii=False, default=str))
                for key, value in flat.items()}
    cheap_cap = max(FIELD_CHARS_MIN, limit // 8)
    cheap = [key for key, text in rendered.items() if len(text) <= cheap_cap]
    big = [key for key, text in rendered.items() if len(text) > cheap_cap]
    left = max(FIELD_CHARS_MIN, limit - sum(len(rendered[key]) for key in cheap))
    per = max(FIELD_CHARS_MIN, left // len(big)) if big else 0
    out: dict[str, Any] = {}
    for key, value in flat.items():
        text = rendered[key]
        budget = len(text) if key in cheap else per
        if len(text) > budget:
            out[key] = (text[:budget] +
                        f"…（该字段原 {len(text)} 字，这里只给了前 {budget} 字 —— 这是**观测层**的截断，"
                        f"不是内容没了；要后面的部分见下面的续读办法）")
        else:
            # 没被截的字段保持原样（结构还在），只有被截的那个退化成"带说明的字符串"。
            out[key] = value
    text = json.dumps(out, ensure_ascii=False, default=str)
    return text if len(text) <= limit * 2 else _clip(text, limit * 2)


def _for_record(result: Mapping[str, Any]) -> dict[str, Any]:
    """落档用的结果视图（长字符串截到 `RECORD_CHARS`，其余原样）。"""
    out: dict[str, Any] = {}
    for key, value in (result or {}).items():
        if isinstance(value, str) and len(value) > RECORD_CHARS:
            out[key] = value[:RECORD_CHARS] + f"…（落档截断，原 {len(value)} 字）"
        else:
            out[key] = value
    return out


def _continue_hint(result: Mapping[str, Any]) -> str:
    """从结果里读出"还要更多怎么办"，写成一句可执行的话。

    没有续读办法时返回空串（不编造）。这是上一个坑的正面：截断必须附带出路，
    否则"少给一点并说清楚"仍然等于"给不出来"。
    """
    meta = result.get("meta")
    if not isinstance(meta, Mapping):
        return ""
    tool = str(result.get("tool") or "该工具")
    if meta.get("next_line") is not None:
        return (f"【续读】{tool} 本次到第 {meta.get('start_line')}–"
                f"{meta.get('start_line', 1) + max(0, int(meta.get('lines_read') or 0)) - 1} 行"
                f"（共 {meta.get('total_lines')} 行）：再调一次 {tool}(path=…, "
                f"start_line={meta['next_line']}) 接着读")
    if meta.get("truncated"):
        return (f"【没读完】{tool} 只读了前 {meta.get('bytes_read')} / {meta.get('total_bytes')} 字节："
                f"要剩余部分就再调一次并给更大的 max_bytes")
    if meta.get("total_lines") and not meta.get("windowed"):
        return (f"【分段】{tool} 这次给的是整段（共 {meta.get('total_lines')} 行）："
                f"要后面的部分再调一次 {tool}(path=…, start_line=N, max_lines=M) —— "
                f"别反复重读同一个开头")
    return ""


def _observe(result: Mapping[str, Any]) -> str:
    """一步的结果 → 模型看得见的那段文本（`data` 可截，`meta` 与续读提示必须到）。"""
    text = _clip_fields(result)
    hint = _continue_hint(result)
    return text + ("\n" + hint if hint else "")


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
def _sha(text: str) -> str:
    """文本的 sha256（会话记录里给交付物留指纹用；与 `llmseam._sha` 同一个口径）。"""
    import hashlib

    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


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
    if key == "ask_user":
        if not isinstance(value, Mapping):
            return "", {}, "ask_user 必须是一个对象"
        question = str(value.get("question") or "").strip()
        if not question:
            return "", {}, "ask_user 得有一个 question"
        options = value.get("options") or []
        if not isinstance(options, (list, tuple)):
            return "", {}, "ask_user.options 必须是数组"
        timeout = value.get("timeout_sec")
        if timeout is not None and not isinstance(timeout, (int, float)):
            return "", {}, "ask_user.timeout_sec 必须是数字"
        return key, {"question": question,
                     "options": [str(x) for x in options],
                     "timeout_sec": float(timeout) if timeout is not None else None}, ""
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
    #: 问用户时的默认等待上限（秒）。调用方可以按场景放长或缩短。
    user_timeout_sec: float = 30.0
    #: 本次运行自己的台账号与深度（由 `run` 设置）。唤起下一环时必须把它当 parent 传下去，
    #: 否则链条在台账里会断成两段互不相干的记录。
    my_task_id: str = ""
    depth: int = 1

    def _prompt(self, transcript: str, *, step: int) -> str:
        last = step >= self.max_steps - 1
        tail = ("这是最后一步：不要再调用工具、不要再唤起伙伴，直接输出 "
                '{"final": "<结论>", "evidence": [...]}。' if last else
                "请按循环协议输出下一步（一个 JSON 对象，六种形状取其一）。")
        # 输出契约重述在最后一行（`draft/28` §195 实测）：
        # 系统提示词有 6k+ token，循环协议埋在中间；真机跑 M 做"核验证明"那种长任务时，
        # 模型连着三次回了 1400–2400 字的散文（`judge_bad_json` ⇒ `bad_json_limit`），
        # 而中间那句"请只输出一个 JSON 对象"它没听。把骨架放到它最后读到的那一行。
        return (f"{transcript}\n\n---\n现在是第 {step + 1} 步（最多 {self.max_steps} 步）。{tail}\n"
                f"剩余花销预算：{self._budget_text()}\n"
                f"{JSON_TAIL}")

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
        replies = AP.user_replies_digest(U.read_replies(self.session_root, role=self.role,
                                                       sid=self.sid))
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
                     notebook=notebook, user_replies=replies)
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
                               f"（{call.problem}）。**不要写分析、不要写方案、不要写 Markdown**："
                               f"只回一行 JSON。骨架：\n{JSON_TAIL}")
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
            step_obj = LoopStep(step, shape, payload, _for_record(result))
            run.steps.append(step_obj)
            SS.append(self.session_root, {
                "kind": "agent_step", "role": self.role, "index": step, "shape": shape,
                "payload": dict(payload), "result": dict(step_obj.result),
            }, sid=self.sid)
            transcript += (f"\n\n[第 {step + 1} 步] 你说了：{_clip(payload, ECHO_CHARS)}\n"
                           f"框架执行结果：{_observe(result)}")
        else:
            run.stop_reason = "max_steps"
            run.final = run.final or f"步数用尽（{self.max_steps} 步）仍未给出 final"

        run.spend = self.seam.spend.to_dict()
        run.elapsed_sec = time.monotonic() - t0
        SS.append(self.session_root, {
            "kind": "agent_run_end", "role": self.role, "stop_reason": run.stop_reason,
            "steps": len(run.steps), "summons": run.summons, "messages": run.messages_sent,
            # `final` 是这一岗的交付物本身：只记长度的话，事后没人能核
            # "它到底与验收表对齐了没有"（实测：终点门槛 A 要逐条核交付说明，
            # 而会话记录里只有 `final_chars`）。文本与哈希一起留，长度保留是为了
            # 让"有没有被截断"一眼可见。
            "final": run.final, "final_sha256": _sha(run.final)[:16],
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
        if shape == "ask_user":
            return self._do_ask_user(payload)
        return self._do_message(payload)

    def _do_tool(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name"))
        args = dict(payload.get("args") or {})
        try:
            res = self.registry.call(name, role=self.role, **args)
        except Exception as exc:  # 工具层抛错也要变成"模型看得见的结果"
            return {"tool": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"tool": name, "ok": bool(res.ok), "data": res.data,
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
        if not res.ok and self._needs_relay(role, str(res.refusal_reason or "")):
            # ---- 越权/超深不是"此路不通"，而是"要换一条路"（2026-09-30）
            #
            # 真机实测：被协同唤起的角色一次都没有向主控申请过代唤 ——
            # 因为它拿到的只是一句 `forbidden_edge`，然后就没有然后了
            # （17 个 review 会话里非 M 的 summon 只有 F→E 7 次）。
            # 用户的原话是"如果互相唤起困难，至少要能向主控申请唤起别的智能体做任务"，
            # 所以这里把"被拒绝"自动转成一次结构化的代唤申请：
            # 落一条 `agent_summon_request` 事件 + 给 M 发一条 `subject=请代唤` 的留言。
            # 注意它不是假装成功：`ok` 仍是 False，`relay_requested` 才是这次
            # 实际发生的事；申请有没有被受理由主控在它自己那一步决定。
            out["relay_requested"] = self._request_relay(role, action, payload,
                                                         str(res.refusal_reason or ""),
                                                         str(res.detail or ""))
        if path:
            # 伙伴是 LLM 循环驱动的：它的完整产出在磁盘上，这里只给路径 + 一段结论。
            out["llm_run_path"] = path
            out["final"] = _clip(payload.get("final") or "", 600)
            out["payload"] = _clip({k: v for k, v in payload.items() if k != "llm_run"}, 400)
        else:
            out["payload"] = _clip(payload, 800)
        return out

    def _needs_relay(self, role: str, reason: str) -> bool:
        """这次拒绝该不该转成"请主控代唤"。

        两档要转：

        - `forbidden_edge` / `depth_exceeded`：这条路今天不通（边表 / 深度），
          而重试不会让它通。
        - `invalid_params` 且目标不在我的伙伴表里：这是同一件事的另一种表现 ——
          我看不到他的动作表（伙伴表只列我能唤起的人），所以我给的参数必然是在猜；
          `Conductor.summon` 的顺序是"先查参数、再查边"，于是我会拿到 `invalid_params`，
          而真相是"我根本不该直接找他"。把这一档也算进来，代唤才不会因为
          "参数猜错"而永远发不出去（这是本轮实测出来的：第一次写这条判据时，
          真实场景恰恰落在这档上）。

        反过来，目标在我能唤起的伙伴里时 `invalid_params` 就只是"参数写错了"：
        那种情况该由模型自己改参数，不该占用主控的注意力。
        """
        if reason in RELAY_REFUSALS:
            return True
        return reason == "invalid_params" and role not in AP.partners_out(self.role)

    def _request_relay(self, role: str, action: str, params: Mapping[str, Any],
                       reason: str, detail: str) -> dict[str, Any]:
        """把一次被拒的越权召唤转成"请主控代唤"的申请（留言 + 结构化事件）。

        为什么是留言而不是新造一个形状：`message` 这条通道今天已经通到 M
        （`to="M"` 的私聊判据 `self.role in partners_out("M")` 对每个角色都成立），
        且 M 的循环下一步就会 `_hear()` 到它。新造形状要动循环协议、提示词、
        与会话格式三处，而这一条的用户诉求是"至少能申请"，留言 + 可识别 subject
        就够了；"M 必须受理"那一半只能靠提示词与审计（`verify.py` 是禁改区）。

        `subject` 用固定常量是为了让机器可识别（人读也一眼懂）；body 里逐项写清
        "要谁、做什么动作、什么参数、为什么"，让 M 不必回头问。
        """
        asked = {k: v for k, v in (params or {}).items() if not str(k).startswith("_")}
        body_lines = [f"要谁：{role}", f"做什么动作：{action}"]
        if asked:
            body_lines.append("参数：" + json.dumps(asked, ensure_ascii=False, default=str)[:600])
        else:
            body_lines.append("参数：（这次没有参数）")
        body_lines.append(f"为什么：我要做的这件事被策略拒了（{reason}）—— {detail[:300]}")
        if role not in AP.partners_out(self.role):
            body_lines.append("注意：他不在我的可唤起伙伴里，所以我**看不到他的参数表** —— "
                              "参数可能不合法，请用 conductor.role_spec 核一遍再派。")
        body_lines.append(f"申请方：{self.role}（台账号 {self.my_task_id or '未拿到'}）；"
                          f"批准与否由你决定，我这一步不会替你做。")
        body = "\n".join(body_lines)
        msg_id, problem = send_message(self.session_root, sender=self.role, to=S.CONDUCTOR_ROLE,
                                       subject=RELAY_SUBJECT, body=body, sid=self.sid)
        rec: dict[str, Any] = {"kind": "agent_summon_request", "role": self.role,
                               "wants_role": role, "wants_action": action, "params": asked,
                               "refusal_reason": reason, "message_id": msg_id}
        if problem:
            rec["problem"] = problem
        SS.append(self.session_root, rec, sid=self.sid)
        return {"to": S.CONDUCTOR_ROLE, "subject": RELAY_SUBJECT, "message_id": msg_id,
                "problem": problem,
                "note": ("越权的边不会因为重试而成立 ⇒ 已向主控申请代唤；"
                         "不要把这条申请当成'对方已经在做'。")}

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

    def _do_ask_user(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """问用户一个问题并等回答。超时是 `user_no_answer`，不是默许。"""
        timeout = payload.get("timeout_sec")
        outcome = U.ask_user(self.session_root, role=self.role,
                             question=str(payload.get("question") or ""),
                             options=tuple(payload.get("options") or ()),
                             timeout_sec=float(self.user_timeout_sec if timeout is None else timeout),
                             sid=self.sid)
        if outcome.answered:
            return {"asked": outcome.qid, "answer": outcome.answer, "by": outcome.by,
                    "ok": True}
        return {"asked": outcome.qid, "ok": False, "problem": outcome.problem,
                "note": ("没等到用户回答（user_no_answer）：这是没查成，不是默许。"
                         "要么按最保守的做法继续并把这件事写进结论，要么收工等回答；"
                         "绝不许把它当成用户同意。")}

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

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        """登记过的 `(角色, 动作)` 走 LLM 循环；其余交给内层后端（确定性实现）。"""
        cfg = self.loops.get((role, action))
        if cfg is None:
            return self.inner.call(role, action, params, token=token, instance=instance,
                                   task_id=task_id)
        seam = self._seam(role)
        loop = AgentLoop(role=role, session_root=self.session_root, registry=self.registry,
                         seam=seam, conductor=self.conductor, max_steps=int(cfg.get("max_steps", self.max_steps)),
                         workspace_root=self.workspace_root, sid=self.sid, token=token,
                         store=self.store)
        row = self._running_row(role, task_id)
        run = loop.run(str(cfg.get("task_from_params") or "") or _task_text(params, role, action),
                       summoned_by=str(row.get("called_by") or params.get("_summoned_by")
                                       or S.CONDUCTOR_ROLE),
                       my_task_id=str(row.get("task_id") or params.get("_task_id") or ""),
                       depth=int(row.get("depth") or params.get("_depth") or 1))
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

    def _running_row(self, role: str, task_id: str = "") -> dict[str, Any]:
        """找出"这次召唤那条 running 行"，整行返回。

        两条取材路径，按可靠性排序：

        1. 给了 `task_id`（`Conductor.summon` 现在会传，见 `conductor.py` 第 [6] 步）：
           直接按号取那一行 —— 并发多实例下这是唯一可靠的做法（按角色找会同时找到 N 条）。
        2. 没给号（旧调用方 / 直接建 `LlmBackend` 的单测）：退回"按角色找恰好一条"。

        为什么要找而不是让调用方传：`Conductor.summon` 先写 running 行、再调后端，
        所以后端天然不知道自己的台账号。三种"没拿到"必须分得开（没有台账 /
        读台账失败 / 恰好不是一条），所以返回值带 `checked` 与 `reason`，
        而不是给一个"看起来像没结果"的空字典。提示词据此如实写"本次运行未拿到台账号"。

        ## 为什么返回整行而不是只返回 `task_id`（2026-09-30 修的 bug）

        子循环的 `summoned_by` / `depth` 以前读 `params["_summoned_by"]` /
        `params["_depth"]`，而全仓没有任何地方生产这两个键 ⇒ 每一次被同伴
        唤起的角色都以为"是主控直接派的、深度 1"。实测（`temp/review-task-20260930-111332`）：
        台账里 `t-0260 E.run_experiment called_by=F parent=t-0259 depth=2`，
        而 E 自己的 `agent_run_start` 记的是 `summoned_by=M, depth=1` ——
        协同链在孩子自己的认知里断掉，"像主控的 subagent"这句话就不成立。
        权威来源本来就是台账那一行（`called_by` / `depth` 都在上面），直接读它。
        """
        store = self.store
        if store is None:
            return {"checked": False, "reason": "本次运行没有 store（读不到台账）"}
        want = str(task_id or "")
        try:
            rows = [dict(r) for r in store.rows("tasks")
                    if (str(r.get("task_id")) == want if want
                        else (str(r.get("role")) == role and str(r.get("status")) == "running"))]
        except Exception as exc:
            return {"checked": False, "reason": f"读 tasks 表失败：{type(exc).__name__}: {exc}"}
        if len(rows) != 1:
            why = (f"台账号 {want} 在 tasks 表里不是恰好一条（{len(rows)} 条）" if want
                   else f"running 行不是恰好一条（{len(rows)} 条）")
            return {"checked": False, "reason": why + "，不猜台账号"}
        row = dict(rows[0])
        row["checked"] = True
        return row


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
             from_env: bool = True, user_timeout_sec: float = 30.0) -> LoopRun:
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
                     sid=sid, token=token, store=store, user_timeout_sec=user_timeout_sec)
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
    print("SELF-CHECK DONE（六种形状的形状判定 + 消息投递与隔离）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())

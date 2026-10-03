"""用户频道：向用户提问、停着等回答，以及"没答"这一档三态。

## 为什么它必须是结构而不是提示词

"能互动"在提示词里写一百句都不算数：模型说"我想问用户"之后，框架得真的有一条路
把问题送到人面前、把回答带回来。在没有这条路之前，模型只有两种坏选择 ——
替用户把关键取舍定了（事后无法追溯），或者卡在那里不动。

这一层给的是第三条路，并守住两条纪律：

1. 问题是持久的、可被事后复核的：问题与回答都追加进项目会话记录
   （`kind="user_question"` / `"user_answer"`），谁在什么时候问了什么、用户怎么答的，
   事后都能逐条读出来。不新增表（与 `draft/29` §3.2 的"候选落点先落文件"一致）。
2. 没答就是没答：没答「绝不许」被当成"用户默许"。迟到的回答也不会被丢掉：
   `read_replies()` 会把落在日志里的回答捞出来（含迟到的），下一次运行照样看得到。

## 2026-10-03 的口径变更：从"等 30 秒然后继续"改成"停着"

旧行为：`ask_user` 最多等 `DEFAULT_TIMEOUT_SEC`（30 秒），超时返回 `NO_ANSWER`，
调用方（模型循环）「继续往下跑」。真机反复撞到的后果是：问了、没人答、
模型自己把关键取舍定了，而事后从读数上分不清"它问过"与"它没问过"。

用户 2026-10-03 的裁定是「就停着」—— 问了就停在那里等回答，不许超时后继续。
下面是落地形态；其中字段形状参考 DSH 的 `dsh-tool-ask-user`（MIT），
规则是我们自己的（出处逐条写在句子里）：

- 「默认一直等」（`timeout_sec=None`）：等到有回答、或者被这一趟运行的取消信号中止。
  `DEFAULT_TIMEOUT_SEC` 这个常量「保留但不再是默认值」—— 留着是因为历史会话事件里
  写着 `timeout_sec` 这个字段（读老记录还要用到它），也因为它是一处显式的历史口径：
  改成"无限等"不是把 30 秒调大，而是取消"超时后继续"这件事本身。
- 「等待期间不产生 token 开销」：等的是磁盘上的一条回答事件，不调模型。
- 「`wait=False` 或 `timeout_sec=0` = 问了就停」：登记问题、立刻返回 `pending`，
  由调用方（`agent_loop`）停下来等人答。
- 「无人值守档（`ASK_POLICY="unattended"`）确定性拒绝」：不落问题、不提示人、
  返回 `refused`。依据是运行时的三态纪律（`DESIGN-INTERACTIONS.md` §3.4
  「所有空必须三态」：没人在场是"没查成"，不是"通过"）与用户 2026-10-03 的运行时裁定
  （「就停着」；没问过就不许当成默许）—— 它不是"问一下试试"。

## 谁可以问用户（我们的结构决定的）

`DESIGN-CONDUCTOR.md` §1.1 逐字：「它是用户唯一面对的东西」—— 用户只对主控说话，
主控召唤 A–H、再把结果汇总成人看到的东西。`capabilities.NON_SUMMONABLE = {"M"}`
让这条结构成立（主控不可被任何人召唤 ⇒ 它永远是顶层入口）。于是：

只有主控（`schema.CONDUCTOR_ROLE` = `"M"`）可以问用户。 A–H 一律不当面问人 ——
把未决问题写进自己的结果，交回召唤者，由主控汇总。人工直接驱动单个角色
（`agentflow run-agent D`）是「运维/测试」路径，不是用户通道：那条路上 `role != M`，
问用户同样被拒，未决问题出现在结果里，由操作者读。

## `NO_ANSWER` 的含义变了（逐字说清）

`ask_user` 返回 `problem=NO_ANSWER` 时，它现在说的是「还停在等」，不再是
「这次提问失败了」。它仍然是三态里的"没查成"：我们「没有查到用户的意向」，
所以既不能当作"用户同意"，也不能当作"用户拒绝"—— 唯一合法的处置是停在那里等。
停止本身由调用方落地：`agent_loop` 见到 `state="pending"` 就把整趟运行停成
`stop_reason="waiting_for_user"`（不再发任何模型请求），人答完再 `--resume` 续跑。

## 形状（形态参考 DSH 的 `dsh-tool-ask-user`，MIT；同时对旧的会话文件保持可读）

- 提问：`{"id"→qid, "question"→text, "header", "options":[{"label","description"}],
  "multiSelect"→multi_select}`；选项「既可以是新形状的字典，也可以是旧的裸字符串」
  （旧会话事件、旧调用方、`llmseam` 里那张函数面 schema 现在都还是裸字符串）。
- 回答：`{"qid", "selected": [...], "custom": "..."}`；`selected` 可 0/1/n 个；
  `custom` 对多选是补充、对单选是覆盖；不用则省略。读法 `reply_text(event)`：
  `custom` 非空就用它，否则把 `selected` 用「、」拼起来，否则退回旧的 `answer` 字段
  （老会话文件必须照样读得出来）。

## 谁在"回答"

人：CLI 用 `answer_question(...)`（或者直接往会话记录里追加一条 `user_answer`）。
自动化验收里则由脚本扮演用户（这也是 `ask_user` 允许显式给 `qid` 的原因：
测试可以先登记一条回答，再让 `ask_user` 精确地等到它，从而不依赖睡眠与竞态）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import schema as S
from . import sessions as SS

#: 事件类型（落进会话记录，append-only）。
ASK_KIND = "user_question"
ANSWER_KIND = "user_answer"

#: 三态码：等不到回答时的结论。它属于 `judge.JUDGE_PROBLEMS` 那一族"没查成"，
#: 消费方必须走"停下来等"（不许折成"用户同意"）。
#:
#: 2026-10-03 起它的含义是「还停在等」而不是「提问失败」—— 见模块 docstring
#: 里那一节。名字没改是有意的：历史会话记录、`closing` / `reviewaccept` 两个判据层
#: 与提示词里都写着这个字面量，改名字会把"同一件事"变成两处口径。
NO_ANSWER = "user_no_answer"
#: 无人值守档（`ASK_POLICY="unattended"`）的拒绝码：它是「确定性拒绝」，
#: 不是"等不到" —— 两者必须分得开，否则 CI 里的"没人可问"会被读成"问了没人答"。
ASK_REFUSED = "ask_refused"
#: 非主控角色当面问用户的拒绝码（「运行时」协作纪律：人机通道归主控）。
#: 依据是 `DESIGN-CONDUCTOR.md` §1.1「它是用户唯一面对的东西」与
#: `capabilities.NON_SUMMONABLE = {"M"}`（主控永远是顶层入口）—— 不是开发期纪律。
#: 与 `ASK_REFUSED` 刻意分开：一个是"没人可问"，一个是"不该由你问"，
#: 处置方向不同：前者按最保守的做法继续，后者交回召唤者。
#: 落点在循环那一层（`agent_loop._do_ask_user`），见 `ask_user` 的 `role` 一档。
ASK_NOT_CONDUCTOR = "not_conductor"
#: 等待被这一趟运行的取消信号中止。问题仍留在待答清单里：我们的会话记录是
#: append-only 的审计面，撤回只体现在这一档码上，不删已经落盘的问题。
ASK_CANCELLED = "ask_cancelled"

#: 历史默认等待上限（秒）。「不再是默认值」（见模块 docstring）：
#: 它现在只服务于两件事 —— 读老会话事件里的 `timeout_sec` 字段的兜底口径，
#: 以及给"我知道自己在做什么"的调用方一个具名常量。
DEFAULT_TIMEOUT_SEC = 30.0
#: 轮询间隔（秒）。等待就是轮询磁盘上的回答事件，不产生任何 token 开销。
DEFAULT_POLL_SEC = 0.25

#: 无人值守档：`"ask"`（默认，问人）或 `"unattended"`（确定性地拒绝提问，不提示人）。
#:
#: 这是模块级缺省：`ask_user(policy=...)` 没给时读它，于是"整进程无人值守"
#: 只需要改这一处（`agentflow run-agent --no-ask` 走的是显式传参那条路，
#: 不改全局 —— 一个进程里跑第二次调用时不该继承上一次的档位）。
ASK_POLICY = "ask"
#: 认得的策略取值。认不出来的一律按无人值守处置（fail-closed）：把拼错的策略
#: 当成"ask"会让无人值守的运行静默地开始等人。
ASK_POLICIES = ("ask", "unattended")
#: 历史取值（等价于 `"unattended"`）：只为兼容老配置与老调用方保留，不再新写。
ASK_POLICY_LEGACY = ("never",)
#: 判定"这一档要不要拒绝"用的小表（新值 + 历史别名）。
ASK_POLICIES_REFUSE = ASK_POLICIES[1:] + ASK_POLICY_LEGACY

#: `AskOutcome.state` 的取值（四档，不是一个能折平的布尔）。
#:
#: 为什么"停着等"与"被取消"要分开：前者是"还有人可能会答"，后者是"这一趟已经被叫停"
#: —— 两者的下一步动作完全不同（等 vs 收工），折成一个会逼调用方去猜。
STATE_ANSWERED = "answered"
STATE_PENDING = "pending"
STATE_CANCELLED = "cancelled"
STATE_REFUSED = "refused"


@dataclass(frozen=True)
class Option:
    """一个选项：`label` 是回答里原样带回来的那一位，`description` 是给人读的补充。

    为什么不是裸字符串（形态参考 DSH 的 `dsh-tool-ask-user`，MIT；而"选项要能带一句
    解释"这条要求是我们自己的接口契约）：选项常常需要一句解释
    （"选这个的代价是什么"），而裸字符串没有地方放它；更硬的一条是"推荐"这件事 ——
    推荐的做法是把选项放首位并在 label 末尾写 `(Recommended)`，那要求 label 是一个
    独立的、可比较的字符串，而不是一整句人话。
    """

    label: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """落档/打印用的扁平结构（与 DSH 的选项形状逐字对应）。"""
        return {"label": self.label, "description": self.description}


def coerce_option(value: Any) -> Option:
    """把一条选项读成 `Option`：新形状（字典）与旧形状（裸字符串）都认。

    兼容读法是这一层的硬要求：会话记录是 append-only 的，历史上落盘的
    `user_question` 事件里 `options` 是一串裸字符串，而 `llmseam` 里那张给模型看的
    函数面 schema 现在也仍然只广告 `array of string`。读不出来的东西一律按
    `str(value)` 收下（不静默丢选项 —— 选项少了，人就看不到可选项）。
    """
    if isinstance(value, Option):
        return value
    if isinstance(value, Mapping):
        return Option(label=str(value.get("label") or ""),
                      description=str(value.get("description") or ""))
    return Option(label=str(value))


def coerce_options(values: Any) -> tuple[Option, ...]:
    """一串选项 ⇒ `tuple[Option, ...]`（`None` 与空串按空表处置）。"""
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        return (coerce_option(values),)
    return tuple(coerce_option(v) for v in values)


@dataclass(frozen=True)
class Question:
    """一条待回答（或已回答）的问题。"""

    qid: str
    role: str
    text: str
    options: tuple[Option, ...] = ()
    ts: str = ""
    #: `None` = 一直等（新默认）。老事件里写着 30.0/60.0 之类的数，照样读得出来。
    timeout_sec: float | None = None
    #: 短标题（DSH 的 `header`）：界面里当行首用，问题正文可能很长。
    header: str = ""
    #: 多选题（DSH 的 `multiSelect`）：`selected` 可以有 n 个。
    multi_select: bool = False

    @property
    def option_labels(self) -> tuple[str, ...]:
        """选项的 label（需要字符串的地方用它，例如表格与提示词）。"""
        return tuple(o.label for o in self.options)

    def to_dict(self) -> dict[str, Any]:
        """落档/打印用的扁平结构（不含答案：答案在回答事件里）。"""
        return {"qid": self.qid, "role": self.role, "text": self.text,
                "options": [o.to_dict() for o in self.options],
                "option_labels": list(self.option_labels),
                "header": self.header, "multi_select": self.multi_select,
                "ts": self.ts, "timeout_sec": self.timeout_sec}


@dataclass
class AskOutcome:
    """一次提问的结局：答案（可能没有）、状态档、三态码、以及这条问题的 id。"""

    qid: str
    answer: str = ""
    problem: str = ""
    waited_sec: float = 0.0
    by: str = ""
    #: `answered` / `pending` / `cancelled` / `refused`；空串 = 这一档没落成
    #: （例如问题没能写进会话记录 —— 那时连"在等什么"都不存在，不许编一个状态）。
    state: str = ""
    #: 回答的原始形状（`read_replies` 也逐项给出这两栏；`answer` 是它们读出来的文本）。
    selected: tuple[str, ...] = ()
    custom: str = ""
    note: str = ""

    @property
    def answered(self) -> bool:
        """拿到回答了没有。

        为什么以 `state` 为准（而不是"answer 非空且没有 problem"）：DSH 的「跳过此问题」
        发的是空 `{selected: []}` —— 那也是一次回答（人看了一眼、决定不选），
        而按"答案非空"判会把这次回答读成"没答"。`state` 为空（老调用方手搭的对象）
        时退回旧判据，保持向后兼容。
        """
        if self.state:
            return self.state == STATE_ANSWERED
        return bool(self.answer) and not self.problem

    def to_dict(self) -> dict[str, Any]:
        """一次提问的结局读数（含 waited_sec 与是谁答的）。"""
        return {"qid": self.qid, "answer": self.answer, "problem": self.problem,
                "answered": self.answered, "state": self.state,
                "selected": list(self.selected), "custom": self.custom,
                "waited_sec": round(self.waited_sec, 3), "by": self.by,
                "note": self.note}


def reply_text(event: Mapping[str, Any]) -> str:
    """从一条回答事件里读出"用户到底说了什么"（唯一的读法）。

    三档，按新到旧：`custom` 非空就用它（单选里它是覆盖）；否则把 `selected`
    用「、」拼起来；否则退回旧的 `answer` 字段（老会话文件里只有它）。

    一条已知的简化：DSH 里 `custom` 对「多选」是"补充"而不是"覆盖"，而这里
    只要 `custom` 非空就返回它。补选的那几个 label 不会丢 —— 它在事件的 `selected`
    里，`read_replies` 逐项给出；需要两者一起看的消费方读 `selected` 那一栏。
    """
    custom = str(event.get("custom") or "")
    if custom.strip():
        return custom
    selected = [str(x) for x in (event.get("selected") or [])]
    if selected:
        return "、".join(selected)
    return str(event.get("answer") or "")


def _events(session_root: Path, sid: str | None) -> list[dict]:
    events, _problems = SS.read_session(session_root, sid=sid)
    return events


def _next_qid(events: Sequence[Mapping[str, Any]]) -> str:
    """下一个问题号：取所有已出现过的 qid 的数值上界 + 1。

    为什么不是"数一数有多少条提问"：qid 必须先登记回答也可能先存在（自动化里"先答后问"，
    或者一条迟到的回答先落盘）。按提问条数编号会与那些 qid 撞号，而撞号的后果是
    `ask_user` 拿到上一个问题的答案当成本次的回答 —— 静默的错配，比报错坏得多。
    """
    top = 0
    for e in events:
        qid = str(e.get("qid") or "")
        if len(qid) > 1 and qid[0] == "q" and qid[1:].isdigit():
            top = max(top, int(qid[1:]))
    return f"q{top + 1:04d}"


def _timeout_of(event: Mapping[str, Any]) -> float | None:
    """事件里的 `timeout_sec` 读回成数；缺字段或写的是 `None` ⇒ `None`（= 一直等）。

    为什么不用 `DEFAULT_TIMEOUT_SEC` 兜底：那会把"这条问题是默认档（一直等）"
    读成"它等了 30 秒" —— 一个读数被静默换成了另一个意思。
    """
    raw = event.get("timeout_sec")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _question_of(event: Mapping[str, Any]) -> Question:
    """一条 `user_question` 事件 ⇒ `Question`（选项兼容裸字符串这个旧形状）。"""
    return Question(qid=str(event.get("qid") or ""), role=str(event.get("role") or ""),
                    text=str(event.get("text") or ""),
                    options=coerce_options(event.get("options")),
                    ts=str(event.get("ts") or ""),
                    timeout_sec=_timeout_of(event),
                    header=str(event.get("header") or ""),
                    multi_select=bool(event.get("multi_select")
                                      or event.get("multiSelect")))


def pending_questions(session_root: Path | str, *, sid: str | None = None) -> list[Question]:
    """还没被回答的问题（按提问顺序）。给 CLI 用：人打开终端时就能看到它在等什么。

    语义没有变（"问了还没答"）—— 变的只是"没答时框架会停下来"这件事的落点
    （在 `agent_loop` / `run-agent` 里，不在这里）。
    """
    root = Path(session_root)
    events = _events(root, sid)
    answered = {str(e.get("qid")) for e in events if e.get("kind") == ANSWER_KIND}
    out: list[Question] = []
    for e in events:
        if e.get("kind") != ASK_KIND:
            continue
        qid = str(e.get("qid"))
        if qid in answered:
            continue
        out.append(_question_of(e))
    return out


def list_questions(session_root: Path | str, *, sid: str | None = None) -> list[Question]:
    """「所有」问题（含已回答的，按提问顺序）。

    与 `pending_questions` 分开是有意的：待人处置的清单与"问过什么"的历史不是一件事，
    而界面（回放）要的是后者。两者合成一个带过滤参数的函数，迟早会出现
    "某个调用方忘了过滤" ⇒ 面板把答过的问题又列一遍。
    """
    root = Path(session_root)
    return [_question_of(e) for e in _events(root, sid) if e.get("kind") == ASK_KIND]


def session_ids_with_questions(session_root: Path | str) -> list[str]:
    """哪些会话里出现过提问（给界面做跨会话扫描）。

    为什么要它：待答的东西必须「全局可达」。这条界面纪律我们抄自 DSH 的
    `dsh-client-ui-user-questions`（`docs/USER-END-DSH-STYLE.md` §3），而它在我们
    自己的结构里同样成立：`DESIGN-CONDUCTOR.md` §1.1「用户只对主控说话」——
    提问正阻塞着某一趟运行，而那一趟的会话可能不在人当前看的地方。
    于是人得先知道"该去哪些会话里找"，而这件事只有读遍 `sessions/` 才知道。
    读不出坏行的会话照样返回（提问可能就在那些好行里）—— 由调用方按需报出坏行数。
    """
    root = Path(session_root)
    out: list[str] = []
    for row in SS.list_sessions(root):
        sid = str(row.get("sid") or "")
        if not sid:
            continue
        events, _problems = SS.read_session(root, sid=sid)
        if any(e.get("kind") == ASK_KIND for e in events):
            out.append(sid)
    return out


def read_replies(session_root: Path | str, *, role: str | None = None,
                 sid: str | None = None) -> list[dict[str, Any]]:
    """读回答（含迟到的）。给 `role` 时只返回"问这个角色的那些问题"的回答。

    迟到的回答必须留在这条路上：用户答完之后（哪怕提问那一趟已经停了）那条回答
    对下一次运行仍然是有用的事实 —— 丢掉它就等于把用户说过的话当没说过。

    每一项同时给出 `selected` 与 `custom`（新形状的原样）以及 `answer`
    （= `reply_text` 读出来的那句话）：既有读者（`agent_prompts.user_replies_digest`、
    `autonomy._latest_user_answer`）只认 `answer`，它们不许因为这一版而读不到东西。
    """
    root = Path(session_root)
    events = _events(root, sid)
    asked = {str(e.get("qid")): str(e.get("role") or "") for e in events if e.get("kind") == ASK_KIND}
    text_of = {str(e.get("qid")): str(e.get("text") or "") for e in events if e.get("kind") == ASK_KIND}
    out: list[dict[str, Any]] = []
    for e in events:
        if e.get("kind") != ANSWER_KIND:
            continue
        qid = str(e.get("qid"))
        asker = asked.get(qid)
        if asker is None:
            continue                      # 回答指向一个不存在的问题：不算（也不静默当成别人的）
        if role is not None and asker != role:
            continue
        selected = tuple(str(x) for x in (e.get("selected") or []))
        custom = str(e.get("custom") or "")
        out.append({"qid": qid, "role": asker, "question": text_of.get(qid, ""),
                    "answer": reply_text(e), "selected": selected, "custom": custom,
                    "by": str(e.get("by") or "user"),
                    "ts": str(e.get("ts") or ""), "late": bool(e.get("late"))})
    return out


def answer_question(session_root: Path | str, *, qid: str, answer: str | None = None,
                    selected: Sequence[Any] = (), custom: str = "",
                    by: str = "user", late: bool = False, sid: str | None = None) -> str:
    """登记一条回答。返回问题串（空串 = 写成了）。

    `answer` 是「兼容参数」：旧调用方（`agentflow answer` 的位置参数、各测试、
    真机脚本）写的都是它，语义等价于 `custom`（给了就覆盖 `custom`）。
    新调用方用 `selected` / `custom` 那一对，形状与 DSH 的回答一致。

    事件里三栏都写：`selected` + `custom`（新形状）与 `answer`（`reply_text` 读出来的
    那句话）。为什么连 `answer` 也写：`autonomy._latest_user_answer` 直接读
    `event["answer"]`（它不看 `selected`），而"答了却读不到"与"没答"在读数上
    长得一模一样 —— 那正是三态纪律要挡的形态。
    """
    custom_text = str(custom or "")
    if answer is not None:
        custom_text = str(answer)
    row: dict[str, Any] = {"kind": ANSWER_KIND, "qid": qid,
                           "selected": [coerce_option(x).label for x in (selected or ())],
                           "custom": custom_text, "by": by, "late": bool(late)}
    row["answer"] = reply_text(row)
    _path, problem = SS.append(session_root, row, sid=sid)
    return problem


def _find_answer(session_root: Path, qid: str, sid: str | None) -> dict | None:
    for e in _events(session_root, sid):
        if e.get("kind") == ANSWER_KIND and str(e.get("qid")) == qid:
            return e
    return None


def ask_user(session_root: Path | str, *, role: str, question: str,
             options: Any = (), timeout_sec: float | None = None, wait: bool = True,
             sid: str | None = None, qid: str | None = None,
             poll_sec: float = DEFAULT_POLL_SEC,
             cancel_check: Callable[[], bool] | None = None,
             policy: str | None = None, header: str = "",
             multi_select: bool = False) -> AskOutcome:
    """把问题登记进用户频道，然后「停着等」回答（默认一直等）。

    ## 参数（每一档都在说"停下来等多久"这件事）

    - `wait=False` 或 `timeout_sec=0`：登记问题后「立刻」返回 `state="pending"`。
      调用方（`agent_loop`）据此把整趟运行停下来 —— 这就是「问了就停」那一档。
    - `timeout_sec=None`（默认）：一直等，直到有回答或 `cancel_check` 返回真。
    - `timeout_sec>0`：等到那个上限；到了上限仍然是 `pending`（「不是失败」：
      含义变了，见模块 docstring），调用方照样停。
    - `cancel_check`：每一轮轮询调一次，返回真就停止等待并落 `state="cancelled"`。
      取消的判据来自「发起的这一趟运行」自己的取消令牌，不是全局开关。
    - `policy`：不给时读模块级 `ASK_POLICY`。它是 `"unattended"`（历史别名 `"never"`）
      时「不落问题」、直接返回 `state="refused"`、`problem="ask_refused"`：确定性的拒绝。
      认不出的取值也按这一档处置（fail-closed）。
    - `role`：这一档不在本函数里拦。`ask_user` 是通道的底层原语，`role` 是
      「回答归谁」的归属字段（`read_replies(role=...)` 按它做隔离，判据见
      `tests/test_interaction.py::test_answers_are_scoped_to_the_role_that_asked`）。
      「只有主控当面问人」这条纪律的落点在「循环」那一层：`agent_loop` 见到
      `role != CONDUCTOR_ROLE` 就按 `ASK_NOT_CONDUCTOR` 挡回并让角色把未决问题
      写进结果（见 `agent_loop._do_ask_user`）。放那里的理由是：会"停住等人"的
      只有循环；底层原语保持按角色可用，是项目既有的能力，不因这条纪律被削掉。
    - `qid` 可以显式给：测试与"先答后问"的自动化用得上（避免睡眠与竞态）。

    ## 三态与返回值

    `AskOutcome.state` 四档：`answered` / `pending` / `cancelled` / `refused`。
    `pending` 时 `problem=NO_ANSWER`（含义是「还停在等」，不是「问失败了」）；
    `cancelled` 时 `problem=ASK_CANCELLED`；`refused` 时 `problem=ASK_REFUSED`。
    问题没能写进会话记录时 `state=""`、`problem` 里带失败原因 —— 那一档连
    "在等什么"都不存在，不许折成 `pending`（折了就会让调用方停在等一个
    没人能看到的 qid）。
    """
    root = Path(session_root)
    eff_policy = ASK_POLICY if policy is None else str(policy)
    if eff_policy not in ASK_POLICIES and eff_policy not in ASK_POLICY_LEGACY:
        # fail-closed：认不出的策略按无人值守处置。把 `"nevr"` 当成"ask"
        # 会让无人值守的运行开始等人 —— 那正是这一档要防的。
        return AskOutcome(qid="", state=STATE_REFUSED, problem=ASK_REFUSED,
                          note=(f"认不出的提问策略 {eff_policy!r}"
                                f"（只认 {ASK_POLICIES + ASK_POLICY_LEGACY}）"
                                "⇒ 按无人值守处置：确定性拒绝，而不是降级成'问一下试试'。"))
    if eff_policy in ASK_POLICIES_REFUSE:
        # 无人值守档：确定性拒绝，而且「不提示人」（不落问题）。
        return AskOutcome(qid="", state=STATE_REFUSED, problem=ASK_REFUSED,
                          note=("无人值守档（ASK_POLICY=unattended）：问用户被确定性拒绝 —— "
                                "这是三态里的「没人在场」，不是'等不到'；按最保守的做法继续，"
                                "并把「这件事本该问用户但没人可问」写进结论。"))

    opts = coerce_options(options)
    events = _events(root, sid)
    my_qid = qid or _next_qid(events)
    # 先看"是不是已经有答案了"（先答后问 / 重放同一 qid 的场合）
    found = _find_answer(root, my_qid, sid)
    if found is None:
        problem = ""
        if my_qid not in {str(e.get("qid")) for e in events if e.get("kind") == ASK_KIND}:
            _p, problem = SS.append(root, {"kind": ASK_KIND, "qid": my_qid, "role": role,
                                           "text": question, "header": header,
                                           "options": [o.to_dict() for o in opts],
                                           "multi_select": bool(multi_select),
                                           "timeout_sec": (None if timeout_sec is None
                                                           else float(timeout_sec))}, sid=sid)
        if problem:
            return AskOutcome(qid=my_qid, problem=f"问题没能落档：{problem}",
                              note=("用户频道这条通道没通（问题没能落进会话记录）⇒ "
                                    "这不是'停在等回答'：没有 qid 就没有人能答。"
                                    "按最保守的做法继续，并把这件事写进结论。"))
    # ---- 等：轮询磁盘上的回答事件（不产生任何 token 开销）
    t0 = time.monotonic()
    cancelled = False
    want_wait = bool(wait) and (timeout_sec is None or float(timeout_sec) > 0)
    if found is None and want_wait:
        deadline = None if timeout_sec is None else t0 + max(0.0, float(timeout_sec))
        # 轮询间隔的下限：0 会让"一直等"变成忙等（真机里那是一个烧满一个核的死循环）。
        interval = float(poll_sec) if float(poll_sec) > 0 else 0.05
        while True:
            if cancel_check is not None and cancel_check():
                cancelled = True
                break
            found = _find_answer(root, my_qid, sid)
            if found is not None:
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(interval)
    waited = time.monotonic() - t0
    if cancelled:
        return AskOutcome(qid=my_qid, state=STATE_CANCELLED, problem=ASK_CANCELLED,
                          waited_sec=waited,
                          note=("等待被当前轮次的取消信号中止：这一趟停在这里。"
                                "问题仍留在待答清单里 —— 取消不等于用户答过了。"))
    if found is None:
        return AskOutcome(qid=my_qid, state=STATE_PENDING, problem=NO_ANSWER, waited_sec=waited,
                          note=("还停在等用户回答（user_no_answer 的含义是「还停在等」，"
                                "不是「问失败了」）⇒ 框架会停下这一趟，等人答完再续跑。"
                                "绝不许把它当成用户同意。"))
    return AskOutcome(qid=my_qid, answer=reply_text(found), by=str(found.get("by") or "user"),
                      state=STATE_ANSWERED, waited_sec=waited,
                      selected=tuple(str(x) for x in (found.get("selected") or [])),
                      custom=str(found.get("custom") or ""))


@dataclass
class _Probe:
    """自检用的小账本（避免在自检里写断言库）。"""

    problems: list[str] = field(default_factory=list)

    def check(self, ok: bool, what: str) -> None:
        """记一条自检结论。"""
        if not ok:
            self.problems.append(what)


def selftest() -> int:
    """自检：停着等 / 立刻停 / 被取消 / 无人值守拒绝 / 回答形状三态 / 迟到回答。

    语义自 2026-10-03 起是"停着"：`NO_ANSWER` 那一档不再意味着"提问失败"，
    而是"还停在等"。所以这一份自检也逐条对着新语义来（旧的那一份判的是
    "超时返回 user_no_answer 就对了"，那一条正是要废掉的口径）。
    """
    import tempfile

    p = _Probe()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 正控：先登记回答，再问同一个 qid ⇒ 立刻拿到（先答后问那条路）
        p.check(answer_question(root, qid="q0001", answer="选 A", sid="t") == "", "回答没写成")
        got = ask_user(root, role="D", question="用哪个口径？", qid="q0001",
                       timeout_sec=1.0, sid="t")
        p.check(got.answered and got.answer == "选 A", f"没等到回答：{got.to_dict()}")
        # 负控：问了就停（timeout 0）⇒ pending，而不是"失败"；问题留在待答清单里
        miss = ask_user(root, role="D", question="还要继续吗？", timeout_sec=0.0, sid="t")
        p.check(miss.state == STATE_PENDING and miss.problem == NO_ANSWER and not miss.answered,
                f"没有停着等：{miss.to_dict()}")
        p.check("不许把它当成用户同意" in miss.note, f"停着等的说明里没有三态纪律：{miss.note}")
        pend = pending_questions(root, sid="t")
        p.check(any(q.qid == miss.qid for q in pend), f"待答清单里没有那条问题：{pend}")
        # 迟到：答完之后 read_replies 必须能看到它（并能让下一次运行读到）
        p.check(answer_question(root, qid=miss.qid, answer="STOP 先停", late=True, sid="t") == "",
                "迟到的回答没写成")
        replies = read_replies(root, role="D", sid="t")
        p.check(any(r["qid"] == miss.qid and "STOP" in r["answer"] for r in replies),
                f"迟到的回答没被捞出来：{replies}")
        p.check(not any(q.qid == miss.qid for q in pending_questions(root, sid="t")),
                "回答之后它还在待答清单里")

        # 回答形状三态：selected 拼串 / custom 覆盖 / 旧的裸 answer 字段
        q2 = ask_user(root, role="D", question="多选还是单选？",
                      options=["甲", {"label": "乙", "description": "乙的代价"}],
                      timeout_sec=0.0, qid="q0100", sid="t")
        asked_back = [q for q in pending_questions(root, sid="t") if q.qid == "q0100"]
        p.check(q2.state == STATE_PENDING and asked_back
                and asked_back[0].option_labels == ("甲", "乙")
                and asked_back[0].options[1].description == "乙的代价",
                "选项的两种形状没有都被读出来")
        p.check(answer_question(root, qid="q0100", selected=["甲", "乙"], sid="t") == "",
                "多选回答没写成")
        p.check(any(r["qid"] == "q0100" and r["answer"] == "甲、乙" for r in read_replies(root, sid="t")),
                "多选回答没有被拼成一句")
        # 再答一次（人改主意 / 单选覆盖）：latest 那一条的 custom 覆盖 selected，
        # 而 selected 本身留在形状里（要两者一起看的消费方读它）
        p.check(answer_question(root, qid="q0100", selected=["甲"], custom="其实选丙",
                                sid="t") == "", "覆盖式回答没写成")
        p.check(any(r["qid"] == "q0100" and r["answer"] == "其实选丙"
                    and r["selected"] == ("甲",) for r in read_replies(root, sid="t")),
                "custom 没有覆盖 selected（或 selected 丢了）")
        # 老会话文件：只有 `answer` 字段、选项是裸字符串
        SS.append(root, {"kind": ASK_KIND, "qid": "q0900", "role": "D", "text": "老问题",
                         "options": ["老甲"], "timeout_sec": 30.0}, sid="t")
        SS.append(root, {"kind": ANSWER_KIND, "qid": "q0900", "answer": "老回答",
                         "by": "user"}, sid="t")
        old = [r for r in read_replies(root, sid="t") if r["qid"] == "q0900"]
        p.check(old and old[0]["answer"] == "老回答", f"老会话文件的回答读不出来：{old}")
        p.check([q.option_labels for q in list_questions(root, sid="t")
                 if q.qid == "q0900"][0] == ("老甲",), "老事件的裸字符串选项没读出来")

        # 无人值守档：确定性拒绝，问题不落盘（新值 + 历史别名都要拒）
        before = len(list_questions(root, sid="t"))
        for value in ("unattended", "never"):
            refused = ask_user(root, role="M", question="这条要不要问？", policy=value, sid="t")
            p.check(refused.state == STATE_REFUSED and refused.problem == ASK_REFUSED,
                    f"无人值守档（{value}）没有确定性拒绝：{refused.to_dict()}")
            p.check(len(list_questions(root, sid="t")) == before,
                    f"拒绝的那一档（{value}）却把问题落盘了")
            p.check(not refused.answered and refused.qid == "", "拒绝档不该有 qid")
        # 认不出的策略：同样 fail-closed（不许降级成"问一下试试"）
        weird = ask_user(root, role="M", question="x", policy="nevr", sid="t")
        p.check(weird.state == STATE_REFUSED, f"认不出的策略没有被拒：{weird.to_dict()}")

        # 取消：当前轮次的信号为真 ⇒ cancelled（不是 pending，也不是 answered）
        calls = {"n": 0}

        def _cancel() -> bool:
            """扮当前轮次的取消信号：第一次轮询就置位。"""
            calls["n"] += 1
            return True

        cancelled = ask_user(root, role="D", question="会被取消的问题", sid="t",
                             cancel_check=_cancel)
        p.check(cancelled.state == STATE_CANCELLED and cancelled.problem == ASK_CANCELLED,
                f"取消没有落成 cancelled：{cancelled.to_dict()}")
        p.check(calls["n"] >= 1, "cancel_check 一次都没被调用")
        p.check(any(q.qid == cancelled.qid for q in pending_questions(root, sid="t")),
                "取消之后问题不在待答清单里（取消不等于答过了）")

        # 会话枚举：提问落在哪些会话里（界面跨会话扫描那两个函数的判据）
        p.check(session_ids_with_questions(root) == ["t"],
                f"会话枚举不对：{session_ids_with_questions(root)}")
        p.check(len(list_questions(root, sid="t")) >= len(pending_questions(root, sid="t")),
                "list_questions 必须含已回答的那些")

    if p.problems:
        print("SELF-CHECK FAILED")
        for x in p.problems:
            print("  -", x)
        return 1
    print("SELF-CHECK DONE（停着等 / 问了就停 / 取消 / 无人值守拒绝 / 回答形状三态 / 迟到回答）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())

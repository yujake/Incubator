"""用户频道：向用户提问、等回答，以及"没答"这一档三态。

## 为什么它必须是结构而不是提示词

"能互动"在提示词里写一百句都不算数：模型说"我想问用户"之后，框架得真的有一条路
把问题送到人面前、把回答带回来。在没有这条路之前，模型只有两种坏选择 ——
替用户把关键取舍定了（事后无法追溯），或者卡在那里不动。

这一层给的是第三条路，并守住两条纪律：

1. 问题是持久的、可被事后复核的：问题与回答都追加进项目会话记录
   （`kind="user_question"` / `"user_answer"`），谁在什么时候问了什么、用户怎么答的，
   事后都能逐条读出来。不新增表（与 `draft/29` §3.2 的"候选落点先落文件"一致）。
2. 没答就是没答：等回答有超时，超时返回 `user_no_answer` ——
   它是三态里的"没查成"，绝不许被当成"用户默许"。迟到的回答也不会被丢掉：
   `read_replies()` 会把落在日志里的回答捞出来（含迟到的），下一次运行照样看得到。

## 谁在"回答"

人：CLI 用 `answer_question(...)`（或者直接往会话记录里追加一条 `user_answer`）。
自动化验收里则由脚本扮演用户（这也是 `ask_user` 允许显式给 `qid` 的原因：
测试可以先登记一条回答，再让 `ask_user` 精确地等到它，从而不依赖睡眠与竞态）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import sessions as SS

#: 事件类型（落进会话记录，append-only）。
ASK_KIND = "user_question"
ANSWER_KIND = "user_answer"

#: 三态码：等不到回答时的结论。它属于 `judge.JUDGE_PROBLEMS` 那一族"没查成"，
#: 消费方必须走"降级 + 留痕"，不许折成"用户同意"。
NO_ANSWER = "user_no_answer"

#: 默认等待上限（秒）。给一个有限值：无限等会让自动化流水线挂死。
DEFAULT_TIMEOUT_SEC = 30.0
#: 轮询间隔（秒）。
DEFAULT_POLL_SEC = 0.25


@dataclass(frozen=True)
class Question:
    """一条待回答（或已回答）的问题。"""

    qid: str
    role: str
    text: str
    options: tuple[str, ...] = ()
    ts: str = ""
    timeout_sec: float = DEFAULT_TIMEOUT_SEC

    def to_dict(self) -> dict[str, Any]:
        """落档/打印用的扁平结构（不含答案：答案在回答事件里）。"""
        return {"qid": self.qid, "role": self.role, "text": self.text,
                "options": list(self.options), "ts": self.ts,
                "timeout_sec": self.timeout_sec}


@dataclass
class AskOutcome:
    """一次提问的结局：答案（可能没有）、三态码、以及这条问题的 id。"""

    qid: str
    answer: str = ""
    problem: str = ""
    waited_sec: float = 0.0
    by: str = ""

    @property
    def answered(self) -> bool:
        """拿到回答了没有（有答案、且没有三态码）。"""
        return bool(self.answer) and not self.problem

    def to_dict(self) -> dict[str, Any]:
        """一次提问的结局读数（含 waited_sec 与是谁答的）。"""
        return {"qid": self.qid, "answer": self.answer, "problem": self.problem,
                "answered": self.answered, "waited_sec": round(self.waited_sec, 3),
                "by": self.by}


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


def pending_questions(session_root: Path | str, *, sid: str | None = None) -> list[Question]:
    """还没被回答的问题（按提问顺序）。给 CLI 用：人打开终端时就能看到它在等什么。"""
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
        out.append(Question(qid=qid, role=str(e.get("role") or ""), text=str(e.get("text") or ""),
                            options=tuple(str(x) for x in (e.get("options") or [])),
                            ts=str(e.get("ts") or ""),
                            timeout_sec=float(e.get("timeout_sec") or DEFAULT_TIMEOUT_SEC)))
    return out


def read_replies(session_root: Path | str, *, role: str | None = None,
                 sid: str | None = None) -> list[dict[str, Any]]:
    """读回答（含迟到的）。给 `role` 时只返回"问这个角色的那些问题"的回答。

    迟到的回答必须留在这条路上：`ask_user` 超时之后用户才答，那条回答对那次调用没用了，
    但对下一次运行仍然是有用的事实 —— 丢掉它就等于把用户说过的话当没说过。
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
        out.append({"qid": qid, "role": asker, "question": text_of.get(qid, ""),
                    "answer": str(e.get("answer") or ""), "by": str(e.get("by") or "user"),
                    "ts": str(e.get("ts") or ""), "late": bool(e.get("late"))})
    return out


def answer_question(session_root: Path | str, *, qid: str, answer: str, by: str = "user",
                    late: bool = False, sid: str | None = None) -> str:
    """登记一条回答。返回问题串（空串 = 写成了）。"""
    _path, problem = SS.append(session_root, {"kind": ANSWER_KIND, "qid": qid,
                                              "answer": answer, "by": by, "late": late}, sid=sid)
    return problem


def ask_user(session_root: Path | str, *, role: str, question: str,
             options: Sequence[str] = (), timeout_sec: float = DEFAULT_TIMEOUT_SEC,
             sid: str | None = None, qid: str | None = None,
             poll_sec: float = DEFAULT_POLL_SEC) -> AskOutcome:
    """把问题登记进用户频道并等回答；超时返回 `user_no_answer`（不是默许）。

    `qid` 可以显式给：测试与"先答后问"的自动化用得上（避免睡眠与竞态）。
    """
    root = Path(session_root)
    events = _events(root, sid)
    my_qid = qid or _next_qid(events)
    # 先看"是不是已经有答案了"（先答后问 / 重放同一 qid 的场合）
    found = _find_answer(root, my_qid, sid)
    if found is None:
        problem = ""
        if my_qid not in {str(e.get("qid")) for e in events if e.get("kind") == ASK_KIND}:
            _p, problem = SS.append(root, {"kind": ASK_KIND, "qid": my_qid, "role": role,
                                           "text": question, "options": list(options),
                                           "timeout_sec": float(timeout_sec)}, sid=sid)
        if problem:
            return AskOutcome(qid=my_qid, problem=f"问题没能落档：{problem}")
        t0 = time.monotonic()
        while time.monotonic() - t0 < max(0.0, float(timeout_sec)):
            found = _find_answer(root, my_qid, sid)
            if found is not None:
                break
            time.sleep(min(poll_sec, 0.05) if poll_sec <= 0 else poll_sec)
    waited = 0.0 if found is not None else float(timeout_sec)
    if found is None:
        return AskOutcome(qid=my_qid, problem=NO_ANSWER, waited_sec=waited)
    return AskOutcome(qid=my_qid, answer=str(found.get("answer") or ""),
                      by=str(found.get("by") or "user"), waited_sec=waited)


def _find_answer(session_root: Path, qid: str, sid: str | None) -> dict | None:
    for e in _events(session_root, sid):
        if e.get("kind") == ANSWER_KIND and str(e.get("qid")) == qid:
            return e
    return None


@dataclass
class _Probe:
    """自检用的小账本（避免在自检里写断言库）。"""

    problems: list[str] = field(default_factory=list)

    def check(self, ok: bool, what: str) -> None:
        """记一条自检结论。"""
        if not ok:
            self.problems.append(what)


def selftest() -> int:
    """自检：问到答案、超时三态、迟到回答、以及"不敢替用户默认"。"""
    import tempfile

    p = _Probe()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 正控：先登记回答，再问同一个 qid ⇒ 立刻拿到
        p.check(answer_question(root, qid="q0001", answer="选 A", sid="t") == "", "回答没写成")
        got = ask_user(root, role="D", question="用哪个口径？", qid="q0001",
                       timeout_sec=1.0, sid="t")
        p.check(got.answered and got.answer == "选 A", f"没等到回答：{got.to_dict()}")
        # 负控：超时必须是 user_no_answer，而且问题留在了待答清单里
        miss = ask_user(root, role="D", question="还要继续吗？", timeout_sec=0.0, sid="t")
        p.check(miss.problem == NO_ANSWER and not miss.answered,
                f"超时没有落成 {NO_ANSWER}：{miss.to_dict()}")
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

    if p.problems:
        print("SELF-CHECK FAILED")
        for x in p.problems:
            print("  -", x)
        return 1
    print("SELF-CHECK DONE（问到答案 / 超时三态 / 迟到回答 / 待答清单）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())

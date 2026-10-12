"""自主轮次 + 周期汇报：把"跑一次循环"接成"跑一程并按节拍向用户报账"。

## 这一层补的是哪一个洞

`agent_loop` 解决的是"一次运行里，模型自己决定调工具、唤起伙伴、留言"。
它一次只跑一轮：给出 `final` 就收工（预算或墙钟耗尽才强制收工；步数不是收工理由 ——
`max_steps` 只是向父代理报账的阈值，见裁定 12-K），
下一轮从哪开始、这一轮该不该告诉用户、要不要接着上一轮往下做 —— 全都不在它里面。

于是"自主"这件事在系统里只到"跑一轮"为止：要么调用方自己写 `for` 循环
（于是每一处循环各有一套停止判据与各自的汇报口径），要么一轮就停。
这一层给的是那条被写过很多遍的循环的唯一实现：

1. 每一轮都是完整的一次 `run_role(...)`（工具面、权限面、审计面与单轮完全一样）；
2. 第 N>1 轮的任务 = 原始任务 + 上一轮的结论与"还差什么"（短块，不重述全文）；
3. 按节拍把阶段汇报发到公共频道，并落一条会话事件（发不出去也要留痕）。

## 停止判据与三态

每一轮开跑前按固定顺序判一次，命中就停，并把命中哪一条如实写进
`AutonomyRun.stop_reason`（`rounds` / `budget` / `stop_file` / `user_stop`）
—— 顺序写死是为了"多条同时成立"时也有一个确定的答案，而不是看谁先被读到：

- `rounds`：轮次用尽（这是唯一的正常终点，"跑完了"就是它）；
- `budget`：花销预算已到（有共享的模型缝就问缝，没有就把各轮的用量加起来）；
- `stop_file`：磁盘上出现了那个开关文件（人不用等着发指令就能叫停）；
- `user_stop`：用户最新一条回答里有 `STOP` 这个字（"我看到了，停"）。

`not_wired` 是第五种停法，它在第一轮跑完之后判：没有接线时循环不发起任何请求，
这时继续排下一轮只会连排 N 次空转 —— 所以停，并说明"后续轮次不再发起"。

## 汇报是结构，不是提示词里的请求

"要定期汇报"写在提示词里不算数：模型可以整轮不说话。所以汇报由这一层发：
每 `report_every` 轮一次，且在最后一轮必发（最后一轮 = 这一程实际跑到的最后一轮，
提前停下时那一轮也算），正文里逐条给出轮次、本轮结论、本轮唤起过谁、留言给谁、
以及剩余预算。两件事分开记，谁也不替谁兜底：

- 发到用户频道的那条消息走 `send_message`，失败原因记进 `RoundReport.report_sent`
  与 `notes`（空串 = 发出去了）；
- 会话事件 `autonomy_report` 是审计面，它独立于发送结果：发失败时那条事件仍然落，
  于是"当时想报的是什么"事后可读，"没发出去"由 `report_sent` 回答。

## 已知缺口（写下来，免得被读成"已经覆盖了"）

- 这一层不做跨进程恢复：会话事件里留下了每一轮的账，但"从第 K 轮接着跑"
  还没有一条命令来实现；
- `min_usd_between_reports` 只拦节拍上的汇报，不拦最后一轮 —— "收工要有交代"
  比"别报得太密"更硬。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import sessions as SS
from .agent_loop import PUBLIC, LoopRun, run_role, send_message
from .llmseam import LlmSeam

#: 用户在回答里写这个字 = 让这一程停下（它不是"我看看"，是停止信号）。
STOP_TOKEN = "STOP"

#: 检查点目录与文件名：`<项目根>/runs/autonomy-<角色>.json`。
#: 为什么要检查点：`run_autonomous` 的一次调用可能跑几十分钟（每轮都要调好几次模型），
#: 被 Ctrl-C、断电或预算闸门打断之后，"从第 1 轮重跑"会把已经做过的活再做一遍 ——
#: 而每一轮都可能写了数据、发了汇报。检查点让下一段只跑没做过的那些轮。
CHECKPOINT_DIR_NAME = "runs"


def checkpoint_path(session_root: Path | str, role: str) -> Path:
    """这个角色的自主轮检查点路径。"""
    return Path(session_root) / CHECKPOINT_DIR_NAME / f"autonomy-{role}.json"


def task_fingerprint(role: str, task: str) -> str:
    """任务指纹：`角色 + 任务原文` 的哈希前缀。

    恢复之前必须比对它：拿 A 任务的检查点去续 B 任务，会把两件事的进度混成一条，
    而那条记录看起来完全正常（这正是要拦的形态）。
    """
    import hashlib

    return hashlib.sha256(f"{role}\n{task}".encode("utf-8")).hexdigest()[:16]


def load_checkpoint(session_root: Path | str, role: str) -> dict[str, Any] | None:
    """读检查点；不存在或读不出来都返回 None（读不出来另记一条 note 由调用方决定）。"""
    path = checkpoint_path(session_root, role)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_checkpoint(session_root: Path | str, role: str, *, fingerprint: str,
                    completed_rounds: int, rounds: int, task: str,
                    spend: Mapping[str, Any], stop_reason: str = "",
                    last_final: str = "") -> str:
    """写检查点，返回问题串（空 = 写成了）。写入失败不许静默。"""
    path = checkpoint_path(session_root, role)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"role": role, "task": task, "fingerprint": fingerprint,
                   "completed_rounds": int(completed_rounds), "rounds": int(rounds),
                   "spend": dict(spend), "stop_reason": stop_reason,
                   "last_final": str(last_final)[:FINAL_CHARS],
                   "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""

#: 结论进下一轮任务块与进汇报正文时的字符上限（超了截断并写明原文多少字）。
FINAL_CHARS = 300

#: 一轮的用量里要逐栏相加的计数器（与 `SeamSpend.to_dict` 的键同名，不另立口径）。
_COUNTER_KEYS = ("calls", "tokens_in", "tokens_out", "unknown_usd_calls")

#: 「唤醒」允许多开几轮（S-G，裁定 15）。为什么必须有这个上限：唤醒的判据是
#: "收件箱里有没投递过的留言"，而只要有人一直在说话，那个判据就永远为真 ——
#: 没有上限等于把"轮次用尽"这个停止条件变成死循环（而且每一轮都在烧钱）。
#: 一次唤醒只多开一轮：那一轮的 `_hear` 会把留言标记成已投递 ⇒ 下一轮的判据
#: 自然为假（"唤醒"是事件，不是状态）。
WAKE_ALLOWANCE = 1


@dataclass
class RoundReport:
    """一程里的一轮：它怎么停的、结论是什么、以及这一轮的汇报发出去没有。"""

    index: int
    stop_reason: str
    final: str
    summons: list[str]
    messages: list[str]
    report_sent: str = ""

    def to_dict(self) -> dict[str, Any]:
        """这一轮的扁平记录（`report_sent` 空串 = 阶段汇报已发出）。"""
        return {"index": self.index, "stop_reason": self.stop_reason, "final": self.final,
                "summons": list(self.summons), "messages": list(self.messages),
                "report_sent": self.report_sent}


@dataclass
class AutonomyRun:
    """一程自主运行的完整账：跑了几轮、每轮汇报如何、为什么停、花了多少、哪里异常。"""

    role: str
    task: str
    rounds_done: int = 0
    reports: list[RoundReport] = field(default_factory=list)
    stop_reason: str = ""
    spend: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    #: 这一段之前已经完成了几轮（检查点里读到的）；0 = 全新开始。
    resumed_from: int = 0
    #: 检查点路径（这一段跑完把它写到哪）。
    checkpoint: str = ""
    #: 被"唤醒"多开的轮数（S-G，裁定 15；DSH 的 `next-turn` 那一格）：
    #: 轮次用尽之后，收件箱里还有没投递过的留言 ⇒ 再开一轮（有界，见 `WAKE_ALLOWANCE`）。
    woke_rounds: int = 0

    def to_dict(self) -> dict[str, Any]:
        """一程的扁平记录（轮次 + 逐轮汇报 + 停止原因 + 用量 + 异常各一行）。"""
        return {"role": self.role, "task": self.task, "rounds_done": self.rounds_done,
                "resumed_from": self.resumed_from, "checkpoint": self.checkpoint,
                "stop_reason": self.stop_reason, "spend": dict(self.spend),
                "woke_rounds": self.woke_rounds,
                "reports": [r.to_dict() for r in self.reports], "notes": list(self.notes)}


# ------------------------------------------------------------------ 小工具
def _clip(value: Any, limit: int = FINAL_CHARS) -> str:
    """把一段文本截到上限；超了就写明原文多少字（截断不静默）。"""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"…（原文 {len(text)} 字，已截断）"


def _spend_of(value: Mapping[str, Any] | None) -> dict[str, float]:
    """把一份用量记录读成可相减的数：缺项按 0 算，None 表示还没用过任何模型。

    为什么要有这一层而不是直接拿 `run.spend` 相加：同一个模型缝在多轮之间是共用的，
    于是第 2 轮的 `run.spend` 里已经含第 1 轮 —— 直接把各轮相加会把账算多。
    这里相减出来的才是"这一轮新花的"，各轮相加才等于总数。
    """
    if value is None:
        return {**{k: 0.0 for k in _COUNTER_KEYS}, "usd": 0.0}
    out = {k: float(value.get(k) or 0) for k in _COUNTER_KEYS}
    out["usd"] = float(value.get("usd") or 0.0)
    return out


def _spend_delta(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float]:
    """两个用量读数之差（这一轮新花的）：这是各轮可相加的那个量。"""
    out = {k: float(after.get(k) or 0) - float(before.get(k) or 0) for k in _COUNTER_KEYS}
    out["usd"] = float(after.get("usd") or 0.0) - float(before.get("usd") or 0.0)
    return out


def _spend_view(total: Mapping[str, float]) -> dict[str, Any]:
    """累加出来的用量整理成可读视图：计数器取整，美元按 6 位小数收口。"""
    out: dict[str, Any] = {k: int(round(float(total.get(k) or 0))) for k in _COUNTER_KEYS}
    out["usd"] = round(float(total.get("usd") or 0.0), 6)
    return out


def _root_of(store: Any, session_root: Path | str | None) -> Path:
    """会话记录的落点：给了就用给的，否则取 `store.root`（与 `run_role` 同一条口径）。

    两处分开写迟早会出现"汇报落在别处"的静默错位，所以这里与 `run_role` 用同一条规则，
    并且在两处都不成立时直接报错，而不是退回当前目录（那会让记录落进一个没人看的地方）。
    """
    if session_root is not None:
        return Path(session_root)
    raw = str(getattr(store, "root", "") or "")
    if not raw:
        raise ValueError("run_autonomous 需要 session_root，或一个带 root 的 store")
    return Path(raw)


def _round_task(task: str, previous: RoundReport, index: int, *, user_answer: str = "") -> str:
    """第 N>1 轮的任务：原始任务 + 上一轮结论与还差什么（短块，不重述全文）。

    `user_answer`（`draft/37` §14.5 第 4 件）必须真的进到这一段里 ——
    它是 `ask_user → cli answer → --resume` 这条闭环的最后一格：
    用户答了什么，续跑那一段就按什么做。只把回答写进会话记录不算闭环：
    真机与离线判据都证明过，"答了但模型看不到"与"没答"在读数上长得一模一样
    （`tests/test_resume_runs_and_consumes_answer.py` 就是为这一格写的）。
    """
    head = (f"{task}\n\n---\n"
            f"上一轮（第 {previous.index} 轮）的结论：{_clip(previous.final) or '（没有给出结论）'}\n"
            f"上一轮为什么停：{previous.stop_reason}\n"
            f"还差什么：接着上一轮的结论往下做，不要从头重来（这是第 {index} 轮）。")
    if user_answer.strip():
        head += (f"\n\n---\n用户的最新回答（**按它做**，别再问一遍）：{_clip(user_answer, 400)}")
    return head


def _round_budget(root: str | Path, fallback: float | None) -> float | None:
    """开下一轮之前现读这一趟的总预算（业主 2026-10-12 的追加预算轴）。

    为什么每一轮都现读（而不是构造期取一次）：多轮跑是小时级的，用户在网页上追加预算
    之后，下一轮就该受新上限约束 —— 取一次会把"追加"变成"重启才生效"。
    读不懂时回退到调用方给的上限（少花是安全的那一侧，见 `budget` 模块的 docstring）。
    """
    from . import budget as B

    if not root:
        # 没有工作区根 ⇒ 没有寄存器可读（测试里常给 `session_root=None`）：
        # 直接用调用方给的上限，别去 `Path(None)` —— 那会抛 TypeError，
        # 把"这一趟没有预算寄存器"说成一个崩溃。
        return fallback
    return B.limit_usd(root, fallback=fallback)


def _stop_before_round(index: int, *, rounds: int, spent_usd: float,
                       usd_budget: float | None, stop_path: Path | None,
                       user_answer: str, last_stop_reason: str = "",
                       pending_qids: tuple[str, ...] = (),
                       wake_pending: int = 0, woke: int = 0) -> str:
    """下一轮开跑前的停止判据；返回停止原因（空串 = 继续跑）。

    顺序是 `waiting_for_user` → `rounds` → `budget` → `stop_file` → `user_stop`：
    先看"上一轮停在等用户回答、而「那个回答到现在还没来」"（唯一一条不能靠继续跑绕过去的），
    再耗尽轮次，再看钱，再看磁盘上那个人工开关，最后看用户最新那句话。
    多条同时成立时按这个顺序给一个确定的答案 —— 否则"为什么停"这件事会取决于读取顺序，
    而那是不可复现的。

    ## `waiting_for_user` 为什么排在最前，以及为什么要看 `pending_qids`（`draft/37` §72）

    上一轮停在等用户回答时开下一轮，后果很具体：那一轮问了一个只有人能定的取舍、
    然后停在等；多轮驱动照常开下一轮，模型就在「没有那个回答」的情况下继续做 ——
    等于替人把取舍定了，还多烧一轮的钱。

    但"上一轮停过"本身不足以判定停机：「人可能已经答了」。人一答，正确答案就是
    "接着跑"（那正是 autonomy 消费回答的那条路：答案进下一轮的任务原文）。
    所以判据是两件事同时成立：上一轮停在等用户 「且」 那个问题至今还挂在待答清单里
    （`pending_qids` 非空）。只看前者会把"答了之后续跑"一起拦掉 —— 实测撞过：
    `tests/test_resume_runs_and_consumes_answer.py` 两条判据当场红（续跑一次模型都没调）。
    """
    if last_stop_reason == "waiting_for_user" and tuple(pending_qids):
        return "waiting_for_user"
    if index > rounds:
        # ---- S-G（裁定 15；DSH 的 `next-turn` + `wakeDriver`）：轮次用尽之后，
        # 收件箱里还有没投递过的留言 ⇒ 再开一轮（那是"有人在等我"这件事的机器可判形态）。
        # 有界（`WAKE_ALLOWANCE`）：一次唤醒只多开一轮，理由见那个常量的注释。
        #
        # 三条不许被它挤掉的东西：① `waiting_for_user` 已在上面拦过（那一档"人没答"不许被
        # "有人说话"绕过去）；② 钱 / 人工开关 / 用户叫停照旧优先 —— 唤醒不是硬闸的豁免
        # （判据：预算用尽 + 有留言 ⇒ 停，理由仍是下面那一道给出的那个）；
        # ③ 报出来的理由顺序一个字不改（`rounds` 在 `budget` 之前是文档化的口径）。
        hard = (usd_budget is not None and spent_usd >= usd_budget) or \
            (stop_path is not None and stop_path.exists()) or (STOP_TOKEN in user_answer)
        if not hard and wake_pending > 0 and woke < WAKE_ALLOWANCE:
            return ""
        return "rounds"
    if usd_budget is not None and spent_usd >= usd_budget:
        return "budget"
    if stop_path is not None and stop_path.exists():
        return "stop_file"
    if STOP_TOKEN in user_answer:
        return "user_stop"
    return ""


def _latest_user_answer(session_root: Path, role: str, *,
                        sid: str | None) -> tuple[str, list[str]]:
    """最近一条"对本角色说的"用户回答；返回 `(回答文本, 异常说明)`。

    首选 `userio.read_replies`（它知道一条回答是在答哪个角色的哪个问题）。这一层
    在本仓库里是存在的，但它不保证永远存在，所以 `import` 失败时改读会话里的
    `user_answer` 事件 —— 两条路都留着，而不是"import 得到就假定它永远在"。

    两条路都要走一遍：`read_replies` 只认"问过的问题"的回答，而一条直接写着
    `role` 的回答（问题没落档的场合）同样算"对本角色说的"，它只能从事件里读。
    答案按事件顺序收集，最后一条才是"最新"的那条。
    """
    events, problems = SS.read_session(session_root, sid=sid)
    notes = [f"读会话记录：{p}" for p in problems]
    answers: list[str] = []
    try:
        from . import userio
    except ImportError as exc:
        notes.append(f"userio 读不到（{type(exc).__name__}: {exc}）："
                     "回退成自己读会话里的 user_answer 事件")
        for event in events:
            if event.get("kind") == "user_answer" and str(event.get("role") or "") == role:
                answers.append(str(event.get("answer") or ""))
        return (answers[-1] if answers else ""), notes
    asked_by_role = {str(reply.get("qid") or "")
                     for reply in userio.read_replies(session_root, role=role, sid=sid)}
    for event in events:
        if event.get("kind") != userio.ANSWER_KIND:
            continue
        qid = str(event.get("qid") or "")
        if qid in asked_by_role or str(event.get("role") or "") == role:
            answers.append(str(event.get("answer") or ""))
    return (answers[-1] if answers else ""), notes


def _report_body(report: RoundReport, *, rounds: int, usd_budget: float | None,
                 spent_usd: float) -> str:
    """阶段汇报的正文：轮次、本轮结论、本轮唤起与留言、剩余预算（缺一样都不算报账）。"""
    left = ("未设置上限" if usd_budget is None
            else f"{max(0.0, usd_budget - spent_usd):.6f} 美元（上限 {usd_budget:.6f}）")
    summons = "、".join(report.summons) if report.summons else "（本轮没有唤起任何人）"
    messages = "、".join(report.messages) if report.messages else "（本轮没有留言）"
    return (f"第 {report.index}/{rounds} 轮已结束，这一轮的停止原因：{report.stop_reason}。\n"
            f"本轮结论：{report.final or '（本轮没有给出结论）'}\n"
            f"本轮唤起过：{summons}\n"
            f"本轮留言给：{messages}\n"
            f"花销：累计 {spent_usd:.6f} 美元，剩余预算 {left}")


def _publish_report(session_root: Path, *, role: str, report: RoundReport, rounds: int,
                    usd_budget: float | None, spent_usd: float,
                    sid: str | None) -> list[str]:
    """把一轮的阶段汇报发到公共频道并落一条事件；返回异常说明（空列表 = 干净）。

    两件事分开做：发消息（用户看得见的那一半）与会话事件（审计的那一半）。
    发送失败不改写终态，也不阻止事件落档 —— 事件记的是"当时想报什么"，
    而"没发出去"由 `RoundReport.report_sent` 与返回的异常说明回答。
    """
    subject = f"[自主轮次] {role} 第 {report.index}/{rounds} 轮"
    body = _report_body(report, rounds=rounds, usd_budget=usd_budget, spent_usd=spent_usd)
    # 框架身份（S6-a）：阶段汇报是框架代表这个角色发给操作者的通报，不是代理在
    # 行使广播权（业主 T20 管的是后者）—— 它没有"发给我的子代理"这个语义，
    # 所以按框架档走（全角色可见，与改前逐字相同）。代理自己发的公聊必须
    # 带台账号；两处的区别写在 `agent_loop.public_visibility` 的 docstring 里。
    _msg_id, problem = send_message(session_root, sender=role, to=PUBLIC, subject=subject,
                                    body=body, sid=sid, by_framework=True)
    report.report_sent = problem
    notes: list[str] = []
    if problem:
        notes.append(f"第 {report.index} 轮的阶段汇报没有发出去：{problem}")
    _path, write_problem = SS.append(session_root, {
        "kind": "autonomy_report", "role": role, "round": report.index,
        "subject": subject, "body": body,
    }, sid=sid)
    if write_problem:
        notes.append(f"第 {report.index} 轮的 autonomy_report 事件没有落进会话记录：{write_problem}")
    return notes


# ------------------------------------------------------------------ 主入口
def run_autonomous(role: str, task: str, *, store: Any, registry: Any,
                   conductor: Any = None, session_root: Path | str | None = None,
                   gateway: Any = None, seam: LlmSeam | None = None,
                   rounds: int = 3, report_every: int = 1,
                   usd_budget: float | None = None, max_steps: int = 30,
                   stop_file: Path | str | None = None, sid: str | None = None,
                   from_env: bool = True,
                   min_usd_between_reports: float = 0.0,
                   user_timeout_sec: float | None = None,
                   resume: bool = False) -> AutonomyRun:
    """把 `role` 的这件事跑成最多 `rounds` 轮，并按节拍向公共频道发阶段汇报。

    每一轮都是一次完整的 `run_role(...)`：工具面、权限面、审计面与单轮运行完全一样，
    这一层只负责"接着跑、按节拍报账、按判据停"。

    参数
    ----
    store, registry, conductor, session_root, max_steps, sid, from_env
        原样交给 `run_role`；`session_root` 不给时取 `store.root`，
        于是汇报落在与运行记录同一个会话里（同一条 `sid`）。
    gateway, seam
        替身模型或一条现成的模型缝。给了 `seam` 就整程共用它（用量与预算是一份）；
        只给 `gateway` 时这里造一条共用的缝。都不给时每一轮各自按 `from_env` 造缝。
    usd_budget
        整程的花销上限（不是每轮各一份）。到顶时连模型都不调用，直接以 `budget` 停。
    report_every, min_usd_between_reports
        汇报节拍：每 `report_every` 轮一次；两次汇报之间花销不到
        `min_usd_between_reports` 时跳过（最后一轮不受这条限制 —— 收工要有交代）。
    stop_file
        磁盘上的停止开关：每一轮开跑前看一眼，存在就以 `stop_file` 停。
    """
    notes: list[str] = []
    root = _root_of(store, session_root)
    total_rounds = max(0, int(rounds))
    every = int(report_every)
    if every < 1:
        notes.append(f"report_every={report_every} 不是一个有效的节拍（至少 1）：按每轮都报处理")
        every = 1
    min_usd = max(0.0, float(min_usd_between_reports))
    stop_path = Path(stop_file) if stop_file is not None else None
    if stop_path is not None and not stop_path.parent.is_dir():
        notes.append(f"stop_file 的父目录不存在（{stop_path.parent}）：按这个路径，"
                     "停止开关永远不会出现（路径写错了，不是'还没按'）")

    shared = seam
    if shared is None and gateway is not None:
        shared = LlmSeam.for_role(role, session_root=root, gateway=gateway,
                                  usd_budget=usd_budget, sid=sid, from_env=False)

    total = _spend_of(None)          # 本段（这一次调用）的用量，进 run.spend
    baseline = _spend_of(None)       # 上一段（检查点里读到的）的用量，只进预算口径
    reports: list[RoundReport] = []
    last_report_usd = 0.0
    stop_reason = ""
    index = 1

    # ---- 检查点：恢复之前先比指纹（拿 A 任务的检查点续 B 任务 = 把两件事混成一条）
    cp_path = checkpoint_path(root, role)
    fingerprint = task_fingerprint(role, task)
    resumed_from = 0
    prev_report = RoundReport(index=0, stop_reason="", final="", summons=[], messages=[])
    if resume:
        cp = load_checkpoint(root, role)
        if cp is None:
            notes.append(f"要求恢复，但读不到检查点（{cp_path}）⇒ 从第 1 轮开始")
        elif str(cp.get("fingerprint")) != fingerprint:
            return AutonomyRun(role=role, task=task, rounds_done=0, reports=[],
                               stop_reason="checkpoint_mismatch", spend=_spend_view(total),
                               notes=[f"检查点的任务指纹（{cp.get('fingerprint')}）与本次"
                                      f"（{fingerprint}）不一致 ⇒ 不许续跑："
                                      "拿一个任务的进度去续另一个任务会把两件事混成一条"],
                               checkpoint=str(cp_path))
        else:
            resumed_from = int(cp.get("completed_rounds") or 0)
            # 上一段的花销要并进预算口径：否则每一段都从 0 开始算，总额会超
            prev = _spend_of(cp.get("spend") if isinstance(cp.get("spend"), Mapping) else None)
            for key in _COUNTER_KEYS:
                baseline[key] += prev[key]
            baseline["usd"] += prev["usd"]
            notes.append(f"从检查点恢复：前 {resumed_from} 轮已完成（不重跑、不重复汇报）；"
                         f"上一段花销 {prev['usd']:.6f} 美元已并入预算口径")
            prev_final = str(cp.get("last_final") or "")
            if resumed_from and not prev_final:
                notes.append("检查点里没有上一轮的结论（老格式）⇒ 续跑的第一轮只带原始任务，"
                             "没有上一轮上下文")
            prev_report = RoundReport(index=resumed_from,
                                      stop_reason=str(cp.get("stop_reason") or ""),
                                      final=prev_final, summons=[], messages=[])
            index = resumed_from + 1
            if resumed_from >= total_rounds:
                return AutonomyRun(role=role, task=task, rounds_done=0, reports=[],
                                   stop_reason="resumed_done", spend=_spend_view(total),
                                   notes=notes + [f"检查点显示 {resumed_from}/{total_rounds} 轮已完成"
                                                  " ⇒ 没有要做的事"],
                                   resumed_from=resumed_from, checkpoint=str(cp_path))

    def _spent_usd() -> float:
        """到现在为止花了多少（含上一段的基线）。

        为什么不只看本段的 seam：续跑的第二段如果从 0 开始算额度，
        "总额不超预算"这条就只在单段内成立 —— 实测（2026-09-29）正是这样：
        基线并进了 `total`，而这里返回的是 `shared.spend.usd`，基线被绕过去了。
        """
        if shared is not None:
            return float(baseline["usd"] + shared.spend.usd)
        return float(baseline["usd"] + total["usd"])

    def _stop_reason_for(next_index: int, last_stop_reason: str = "",
                         woke: int = 0) -> tuple[str, list[str], str]:
        """算"第 next_index 轮开跑前会不会停"，并现读一次用户频道（返回 `(原因, 说明, 回答)`）。

        第三个返回值是给下一轮的任务用的（`§14.5` 第 4 件）：读一次就用一次，
        不要在别处再读一遍 —— 两处各读一次会造出"停的判据用旧回答、任务用新回答"的错位。

        `last_stop_reason` 是「上一轮」的停止理由（`draft/37` §72）：上一轮停在等用户回答时，
        这里必须停，不许开下一轮。
        """
        answer, answer_notes = _latest_user_answer(root, role, sid=sid)
        # 还挂在待答清单里的问题（`draft/37` §72）：它非空且上一轮停在等用户 ⇒ 不许开下一轮。
        # 这里的 import 与 `_latest_user_answer` 里那一处同源（本模块刻意不在顶层 import
        # `userio`，那是"问答频道可能整层缺席"年代的防御）；但「这一条判据依赖它」：
        # 读不到待答清单就判不出"人答了没有"。两个模块是一起发的（`agent_loop` 本身就
        # 通过 `userio` 提问），所以这里不做"读不到就当没人等"的静默回退 ——
        # 那正好会把"没查成"折成"可以继续跑"。
        from . import userio

        pending = tuple(q.qid for q in userio.pending_questions(root, sid=sid))
        # S-G（裁定 15）：唤醒判据现读一次收件箱（"还没投递过的留言"）。
        # 读不成 ⇒ 0（不放行）：`pending_wake` 的 `checked=False` 走的是"没有可唤醒的"，
        # 而"没读成"这件事会由那一轮的收工读数再报一次（不许在这里悄悄多烧一轮钱）。
        from . import agent_loop as AL

        wake = AL.pending_wake(root, role, sid=sid)
        wake_pending = int(wake.get("count") or 0) if wake.get("checked") else 0
        reason = _stop_before_round(next_index, rounds=total_rounds, spent_usd=_spent_usd(),
                                    usd_budget=_round_budget(session_root, usd_budget),
                                    stop_path=stop_path,
                                    user_answer=answer, last_stop_reason=last_stop_reason,
                                    pending_qids=pending, wake_pending=wake_pending, woke=woke)
        return reason, answer_notes, answer

    # 上一轮的停止理由（续跑时来自上一段的最后一轮）：`waiting_for_user` 会让这一次
    # 在开跑下一轮之前就停 —— 见 `_stop_before_round` 的 docstring。
    last_round_stop = prev_report.stop_reason if prev_report is not None else ""
    #: 被唤醒多开的轮数（S-G，裁定 15）：只在超过 `total_rounds` 的那几轮上加一。
    woke_rounds = 0
    while True:
        reason, answer_notes, latest_answer = _stop_reason_for(index, last_round_stop, woke_rounds)
        for line in answer_notes:
            if line not in notes:
                notes.append(line)
        if reason == "user_stop":
            notes.append(f"用户最新一条回答里有 {STOP_TOKEN}：按用户的意思停在第 {index} 轮之前")
        if reason:
            stop_reason = reason
            break

        # 续跑的第一轮：`reports` 是空的（那些轮在上一段），上一轮结论来自检查点
        previous = reports[-1] if reports else prev_report
        # S-G（裁定 15）：这一轮是不是"被唤醒多开的"（超过轮次预算 ⇒ 它必须是被唤醒开起来的，
        # 因为唯一的例外就是那条）。落进事件与读数，"为什么多跑了一轮"事后答得出来。
        woke = index > total_rounds
        if woke:
            woke_rounds += 1
        if index == 1:
            # 第一轮也要带上用户的最新回答（"先答后跑"与"跑到一半答了"是同一件事：
            # 问答频道是跨轮的，不该只在第 N>1 轮才被读到）
            round_task = task + ((f"\n\n---\n用户的最新回答（**按它做**，别再问一遍）："
                                  f"{_clip(latest_answer, 400)}") if latest_answer.strip() else "")
        else:
            round_task = _round_task(task, previous, index, user_answer=latest_answer)
        before = _spend_of(shared.spend.to_dict() if shared is not None else None)
        run: LoopRun = run_role(role, round_task, store=store, registry=registry,
                                session_root=root, conductor=conductor, seam=shared,
                                gateway=gateway, max_steps=max_steps,
                                # 每一轮现读一次（追加预算在下一轮生效）：
                                usd_budget=_round_budget(root, usd_budget),
                                workspace_root=str(root), sid=sid, from_env=from_env,
                                user_timeout_sec=user_timeout_sec)
        delta = _spend_delta(before, _spend_of(run.spend))
        for key in _COUNTER_KEYS:
            total[key] += delta[key]
        total["usd"] += delta["usd"]

        _path, problem = SS.append(root, {
            "kind": "autonomy_round", "role": role, "index": index,
            "stop_reason": run.stop_reason, "spend": dict(run.spend),
            "woke": woke,
        }, sid=sid)
        if problem:
            notes.append(f"第 {index} 轮的 autonomy_round 事件没有落进会话记录：{problem}")

        report = RoundReport(index=index, stop_reason=run.stop_reason, final=_clip(run.final),
                             summons=list(run.summons), messages=list(run.messages_sent))
        reports.append(report)
        last_round_stop = run.stop_reason

        # 最后一轮必发：它要么是轮次用尽的那一轮，要么是"跑完这轮就不得不停"的那一轮；
        # 没有接线时也算收工（那一轮没有产出，更要说清楚）。
        next_reason, next_notes, _next_answer = _stop_reason_for(index + 1, last_round_stop,
                                                                 woke_rounds)
        for line in next_notes:
            if line not in notes:
                notes.append(line)
        closing = (index >= total_rounds) or run.stop_reason == "not_wired" or bool(next_reason)
        on_beat = index % every == 0
        if on_beat and not closing and min_usd > 0.0 and (_spent_usd() - last_report_usd) < min_usd:
            report.report_sent = (f"距上次汇报的花销还没到 {min_usd:.6f} 美元"
                                  f"（本轮后累计 {_spent_usd():.6f}）")
        elif on_beat or closing:
            notes.extend(_publish_report(root, role=role, report=report, rounds=total_rounds,
                                         usd_budget=usd_budget, spent_usd=_spent_usd(), sid=sid))
            last_report_usd = _spent_usd()
        else:
            report.report_sent = f"本轮不在汇报节拍上（每 {every} 轮一次）"

        cumulative = _spend_view(total)
        cumulative["usd"] = round(float(baseline["usd"] + total["usd"]), 6)
        problem_cp = save_checkpoint(root, role, fingerprint=fingerprint,
                                     completed_rounds=index, rounds=total_rounds, task=task,
                                     spend=cumulative,
                                     last_final=reports[-1].final if reports else "")
        if problem_cp:
            notes.append(f"第 {index} 轮的检查点没写成：{problem_cp}（下一段会从更早的位置重跑）")

        if run.stop_reason == "not_wired":
            stop_reason = "not_wired"
            notes.append(f"第 {index} 轮没有接线（not_wired）：后续轮次不再发起，"
                         "免得连排 N 次空转")
            break
        index += 1

    cumulative_end = _spend_view(total)
    cumulative_end["usd"] = round(float(baseline["usd"] + total["usd"]), 6)
    final_cp = save_checkpoint(root, role, fingerprint=fingerprint,
                               completed_rounds=resumed_from + len(reports),
                               rounds=total_rounds, task=task, spend=cumulative_end,
                               stop_reason=stop_reason or "rounds",
                               last_final=reports[-1].final if reports else prev_report.final)
    if final_cp:
        notes.append(f"收工时的检查点没写成：{final_cp}")
    view = _spend_view(total)
    view["baseline_usd"] = round(float(baseline["usd"]), 6)
    return AutonomyRun(role=role, task=task, rounds_done=len(reports), reports=reports,
                       stop_reason=stop_reason or "rounds", spend=view, woke_rounds=woke_rounds,
                       notes=notes, resumed_from=resumed_from, checkpoint=str(cp_path))


# ------------------------------------------------------------------ 自检
def selftest() -> int:
    """自检：三轮跑完 + 阶段汇报 + 预算为零不碰模型 + 用户一句 STOP 就停 + 没接线如实停。

    不需要网络也不需要真工作区：替身模型照剧本回答，工作区是临时目录。
    """
    import tempfile

    problems: list[str] = []

    def check(ok: bool, what: str) -> None:
        """记一条自检结论（不通过就写进 problems，供最后统一打印）。"""
        if not ok:
            problems.append(what)

    class Scripted:
        """照剧本回答的替身模型（与测试里的 ScriptedGateway 同款契约）。"""

        spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

        def __init__(self, replies: list[str]) -> None:
            self.replies = list(replies)
            self.prompts: list[str] = []

        def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                     **kw: Any) -> Any:
            """记下这一次的 prompt，并按次序回一句；剧本用完就重复最后一句。"""
            self.prompts.append(prompt)
            text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
            return type("Reply", (), {"ok": True, "text": text, "tokens_in": 0,
                                      "tokens_out": 0, "error_detail": "", "error_kind": ""})()

    class Idle:
        """一次都不该被叫到的替身：它记下自己被调用了几次。"""

        spec = type("Spec", (), {"model": "idle"})()

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, *a: Any, **kw: Any) -> Any:
            """被叫到就计数并回一句合法的 final（自检据此断言它一次都没被叫到）。"""
            self.calls += 1
            return type("Reply", (), {"ok": True, "text": '{"final": "不该跑到这里"}',
                                      "tokens_in": 0, "tokens_out": 0,
                                      "error_detail": "", "error_kind": ""})()

    class StubRegistry:
        """自检用的小注册表：这个角色没有工具，提示词只需要 `for_role`。"""

        def for_role(self, role: str) -> list[Any]:
            """返回这个角色的工具面（自检里是空的）。"""
            return []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        store = type("StubStore", (), {"root": root})()
        registry = StubRegistry()

        # 正控：三轮跑完，每轮一条汇报（含事件），第 2 轮的任务里有第 1 轮的结论。
        gw = Scripted([json.dumps({"final": f"第 {i} 轮结论：还差一步"}, ensure_ascii=False)
                       for i in (1, 2, 3)])
        run = run_autonomous("D", "把这件事做完", store=store, registry=registry, gateway=gw,
                             rounds=3, max_steps=3, sid="self")
        check(run.rounds_done == 3 and run.stop_reason == "rounds",
              f"三轮没有跑完：{run.to_dict()}")
        check(len(run.reports) == 3 and all(r.report_sent == "" for r in run.reports),
              f"阶段汇报有问题：{[r.report_sent for r in run.reports]}")
        check(len(gw.prompts) >= 2 and "第 1 轮结论" in gw.prompts[1],
              "第 2 轮的任务里没有第 1 轮的结论")
        check(run.spend.get("calls") == 3, f"用量没有逐轮相加：{run.spend}")
        events, bad = SS.read_session(root, sid="self")
        check(not bad, f"会话记录读回有问题：{bad}")
        check(sum(1 for e in events if e.get("kind") == "autonomy_report") == 3,
              "汇报事件数不对")
        check(sum(1 for e in events if e.get("kind") == "autonomy_round") == 3,
              "轮次事件数不对")

        # 负控：预算为零 ⇒ 一轮都不跑，而且一次模型调用都不发起。
        idle = Idle()
        broke = run_autonomous("D", "别花钱", store=store, registry=registry, gateway=idle,
                               rounds=3, usd_budget=0.0, sid="self2")
        check(broke.rounds_done == 0 and broke.stop_reason == "budget",
              f"预算为零没有拦住：{broke.to_dict()}")
        check(idle.calls == 0, f"预算耗尽却发起了 {idle.calls} 次模型调用")

        # 负控：用户说 STOP ⇒ 一轮都不跑（answer 走 userio 那条路）。
        from . import userio

        SS.append(root, {"kind": "user_question", "qid": "q0001", "role": "D",
                         "text": "还要继续吗？"}, sid="self3")
        userio.answer_question(root, qid="q0001", answer=f"{STOP_TOKEN} 先停", sid="self3")
        idle2 = Idle()
        stopped = run_autonomous("D", "接着做", store=store, registry=registry, gateway=idle2,
                                 rounds=3, sid="self3")
        check(stopped.rounds_done == 0 and stopped.stop_reason == "user_stop",
              f"用户说停却还在跑：{stopped.to_dict()}")
        check(idle2.calls == 0, "用户说停却发起了模型调用")

        # 三态：没接线 ⇒ 停成 not_wired，也算跑过一轮（不是"零轮、静默收工"）。
        unwired = run_autonomous("D", "没人接线", store=store, registry=registry,
                                 rounds=3, from_env=False, sid="self4")
        check(unwired.rounds_done == 1 and unwired.stop_reason == "not_wired",
              f"没接线没有如实停：{unwired.to_dict()}")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（三轮与阶段汇报 / 预算 / 用户 STOP / 没接线四条路）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())

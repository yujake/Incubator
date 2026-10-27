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
`AutonomyRun.stop_reason`（`waiting_for_user` / `escalated` / 用户叫停三档 / `rounds` /
`budget` / `stop_file`；`user_stop` 已按业主口径删除）
—— 顺序写死是为了"多条同时成立"时也有一个确定的答案，而不是看谁先被读到：

- `waiting_for_user`：上一轮停在等人答、而那个问题至今还挂着（唯一一条不能靠继续跑绕过去的）；
- `escalated`：上一轮用 `conductor.escalate` 把卡住的那件事交给了召唤者（业主 2026-10-19
  「父子天然双向」）—— 再开一轮就是替父把判断定了，所以停在这里等父；
- 用户叫停三档（`stopctl.USER_STOP_REASONS`：`stop_file` / `force_stop` /
  `interrupted_by_parent`，D19）：上一轮就是被一个比这一层更大的意思叫停的 ——
  再开一轮等于把它按下去的那只手改写掉。判据只看上一轮的理由码，不看盘：读到它的
  那一趟在收尾时已经把开关撤走了（`agent_loop` 的 `_consume_stop_at_teardown`），
  "盘上还在"反而是少数形态；
- `rounds`：轮次用尽（这是唯一的正常终点，"跑完了"就是它）；
- `budget`：花销预算已到（有共享的模型缝就问缝，没有就把各轮的用量加起来）；
- `stop_file`：磁盘上出现了那个开关文件（人不用等着发指令就能叫停）；
- `user_stop`：已删除（业主口径 2026-10-17「删掉旁路」：停意由主控理解意思后调
  `conductor.stop` 完成，不靠单词匹配）。

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
from . import stopctl
from . import agent_loop as AL
from .agent_loop import ALL, LoopRun, run_role, send_message
from .llmseam import LlmSeam

#: （已删除） 原本这里是 `STOP_TOKEN = "STOP"` 的字面匹配旁路。
#: 业主口径 2026-10-17「删掉旁路」：优雅停是主控的工具/动作 —— 用户表达出意思，
#: 主控就会启动 `conductor.stop`，不靠单词匹配（字面匹配必然漏：中文「停」「收工」都不认）。
#: 旧常量删掉之后，任何还引用 `autonomy.STOP_TOKEN` 的代码都会立刻 `NameError`（这是有意的：
#: 静默返回"没叫停"比报错更坏）。

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
                    last_final: str = "",
                    stop_switch: Mapping[str, Any] | None = None) -> str:
    """写检查点，返回问题串（空 = 写成了）。写入失败不许静默。

    `stop_switch`（D19）：收工原因是用户叫停时，把那把开关上写着的东西（谁在什么时候
    为什么按的、是不是强制）一并落进 `runs/autonomy-<角色>.json`。
    为什么检查点里要留这一份：`stop_reason="stop_file"` 只答"为什么停的这一档"，
    而"是谁按的 / 是不是用户"只能从开关那份负载里读到 —— 开关随后就被消费掉了，
    不在检查点里留一份，事后就只剩 `runs/stop-history.jsonl` 那一条可查。
    """
    path = checkpoint_path(session_root, role)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"role": role, "task": task, "fingerprint": fingerprint,
                   "completed_rounds": int(completed_rounds), "rounds": int(rounds),
                   "spend": dict(spend), "stop_reason": stop_reason,
                   "last_final": str(last_final)[:FINAL_CHARS],
                   "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if stop_switch is not None:
            # 恒为空的键会让"没人叫停"与"叫停了但没读到是谁"在盘上长得一样
            # （与 `stopctl.request_stop_detail` 只在给了 `root_task_id` 时才写那一格同一条纪律）。
            payload["stop_switch"] = dict(stop_switch)
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
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
                       wake_pending: int = 0, woke: int = 0,
                       stop_latch_reason: str = "") -> str:
    """下一轮开跑前的停止判据；返回停止原因（空串 = 继续跑）。

    顺序是 `waiting_for_user` → `escalated` → 用户叫停 → `rounds` → `budget` →
    `stop_file`：
    先看"上一轮停在等用户回答、而「那个回答到现在还没来」"（唯一一条不能靠继续跑绕过去的），
    再看"上一轮已经把卡住的那件事交给召唤者了"（同一族：等的是别人，不是钱也不是轮次），
    再看"上一轮是被外面的人叫停的"（D19，见下），
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

    ## 用户叫停为什么单独成一档，而不是并进下面那一格（D19，2026-10-22）

    改前这里只有 `waiting_for_user` 与 `escalated` 两档"看理由码"的判据，用户叫停那一族
    完全没有：上一轮以 `stop_file` 收工之后，这一层照开第 2 轮。三层叠加的现场是：
    ① 多轮那一档的 `stop_file` 曾经一路传成 `None`（`stop_path is not None` 整条短路，
    从头没读过盘）；② 就算给了路径，读到它的那一趟树根在收尾时把开关撤掉了
    （`agent_loop._consume_stop_at_teardown`），下一轮再问"盘上还有没有"必然得到"没有了"；
    ③ 于是只有"上一轮的理由码"能回答这件事，而它当时不在判据里。

    所以这一档只看 `last_stop_reason`（`stopctl.USER_STOP_REASONS` 三档，单一真身），
    不看盘。强停（`force_stop`）与父叫停（`interrupted_by_parent`）同一档：
    对"这一趟还要不要往下跑"这个问题，三者给的是同一个答案。

    `stop_latch_reason` 是闩式那一半：调用方开跑前在盘上读到过开关、或某一轮边界上读到过
    （之后又被别人撤走），也算"用户叫停过"。它与上一轮的理由码互为补充 ——
    前者答"这一趟见过没有"，后者答"上一轮是不是被它叫停的"。
    """
    if last_stop_reason == "waiting_for_user" and tuple(pending_qids):
        return "waiting_for_user"
    # ---- 已上报召唤者（`conductor.escalate`，业主 2026-10-19「父子天然双向」）
    #
    # 与 `waiting_for_user` 同一族、同一个理由：上一轮把孩子卡住的那件事已经交给
    # 召唤者了，再开一轮就是替父把判断定了（还多烧一轮钱）。
    # 为什么排在 `rounds` / `budget` / `stop_file` 之前：它不是"跑完了"也不是"钱没了"——
    # 那三条都说"这一趟可以不跑了"，而这一条说"这一趟必须等别人"。
    # 为什么 `escalated` 不是"用户叫停"：停意不是用户下的（`_user_stop_reason` 只会给
    # `stop_file` / `force_stop` / `interrupted_by_parent`），这一档是这一趟自己
    # 决定交出去 —— 判据 `tests/test_escalate_goes_up_and_stops.py` 两向都钉着。
    if last_stop_reason == "escalated":
        return "escalated"
    # ---- 用户叫停（D19）：上一轮就是被一个比这一层更大的意思按下去的。
    #
    # 为什么排在 `rounds` 之前：轮次用尽说的是"这一趟跑满了"，而这一条说的是
    # "人不让它跑满" —— 把它折进 `rounds` 会把"用户摁停"报成"轮数用完"，
    # 而那个读数会让下一次 `--resume` 以为还有得跑。
    # 前面那两条为什么仍在它之前：等用户回答 / 已上报召唤者也同样是"必须等别人"，
    # 而且它们各自带了自己那一份更具体的读数（待答清单 / 父的收件箱）。
    if last_stop_reason in stopctl.USER_STOP_REASONS:
        return last_stop_reason
    if stop_latch_reason:
        # 闩式那一半：这一趟见过那把开关（开跑前就在盘上 / 某个轮次边界上读到过）。
        # 即使它现在不在盘上也照停 —— "见过一次"是发生过的事实，不会因为别人撤走了
        # 文件而消失；而只看盘的判断在这里必然得到"没有人叫停"（见 docstring）。
        return stop_latch_reason
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
            (stop_path is not None and stop_path.exists())
        if not hard and wake_pending > 0 and woke < WAKE_ALLOWANCE:
            return ""
        return "rounds"
    if usd_budget is not None and spent_usd >= usd_budget:
        return "budget"
    if stop_path is not None and stop_path.exists():
        return "stop_file"
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
    _msg_id, problem = send_message(session_root, sender=role, to=ALL, subject=subject,
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
                   resume: bool = False,
                   stop_latch: Mapping[str, Any] | None = None) -> AutonomyRun:
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
        磁盘上的停止开关。不给时就是工作区根下那个 `.agentflow-stop`
        （`stopctl.stop_path`：`agentflow stop` 与 `conductor.stop` 写的就是它）——
        这个参数不再允许"没有路径"（D19：`None` 会让下面每一处"盘上有没有"整条短路）。
    stop_latch
        调用方在开跑之前取的那一份闩式快照（`stopctl.read_stop` 的负载，没有就传 `None`）。
        它与"每一轮开跑前现读一次盘"合起来回答"这一趟见过那把开关没有"：
        开关是一次性信号，读到它的那一趟收尾时会撤走，于是"用户摁过停"在盘上不留痕。
    """
    notes: list[str] = []
    root = _root_of(store, session_root)
    total_rounds = max(0, int(rounds))
    every = int(report_every)
    if every < 1:
        notes.append(f"report_every={report_every} 不是一个有效的节拍（至少 1）：按每轮都报处理")
        every = 1
    min_usd = max(0.0, float(min_usd_between_reports))
    # ---- 停止开关的路径（D19 的第一层）
    #
    # 改前是 `Path(stop_file) if stop_file is not None else None`，而 cli 的多轮那一档
    # 传的正是 `None`（它以为"轮间不叠加步内那一处"就是"轮间不用看"）⇒ 下面每一处
    # `stop_path is not None and ...` 全部短路，这一层从头没读过盘。
    # 现在路径永远有：显式给的用它，否则就是工作区那把手动开关（与 `agentflow stop`
    # 写下的那一份同一个文件）。多轮与单趟读的是同一个开关，不是两份。
    stop_path = stopctl.stop_path(root, explicit=stop_file)
    if stop_file is not None and not stop_path.parent.is_dir():
        notes.append(f"stop_file 的父目录不存在（{stop_path.parent}）：按这个路径，"
                     "停止开关永远不会出现（路径写错了，不是'还没按'）")
    # ---- 闩式快照（D19 的第三层）：这一趟"见过"那把开关没有。
    #
    # 两个来源：调用方开跑前取的那一份（`stop_latch`），以及每一轮开跑前自己现读一次盘
    # （`_user_stop_reading`：读到就闩住，之后不再依赖文件还在不在）。
    # 为什么必须"闩"：读到开关的那一趟在收尾时把它撤走（`agent_loop._consume_stop_at_teardown`），
    # 于是"用户摁过停"这件事在盘上不留痕。只问"文件在不在"的判断永远读不到"刚刚有人叫停"。
    latched_stop = stopctl.stop_reason_of(stop_latch)

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
            # 2026-10-17（IO #8）：`load_checkpoint` 只校验"能解析成 dict"，字段级不校验；
            # `completed_rounds: "abc"` 的脏检查点会把一次续跑变成 traceback。
            try:
                resumed_from = int(cp.get("completed_rounds") or 0)
            except (TypeError, ValueError):
                resumed_from = 0
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

    def _user_stop_reading() -> str:
        """这一轮开跑前读一次手动开关；读到就闩住（返回闩住的那一档，空串 = 没见过）。

        为什么要现读一次盘：调用方那份快照是"开跑之前"的读数，而用户完全可以在第 2 轮
        开跑之前才摁停 —— 那一份快照看不见它。

        三态（与别处同一条纪律）：读不成（异常）不折成"没人叫停" —— 留一条 note，
        并返回已经闩住的那一份（没有就是空串，由调用方自己那一轮里的停机判据兜底）。
        """
        nonlocal latched_stop
        try:
            state = stopctl.read_stop(root, explicit=stop_file)
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"没人叫停"
            notes.append(f"停机开关没读成（{type(exc).__name__}: {exc}）"
                         "⇒ 这一格的读数不完整（不折成「没人叫停」）")
            return latched_stop
        now = stopctl.stop_reason_of(state)
        if now and not latched_stop:
            latched_stop = now
            notes.append(f"停机开关在盘上（{stop_path}）⇒ 记下这一档：{now}；"
                         "它是一次性信号，之后即使文件被别人撤走也照停")
        return latched_stop

    last_clock_wakes: list[dict[str, Any]] = []
    clock_pump_note = ""

    def _pump_and_read_clock() -> list[dict[str, Any]]:
        """轮边界上的时钟推进 + 唤醒读数（D-53 的生产端与读口）。

        两件事在这里合起来做，因为它们必须同刻：先 `fire_due`（到点的计时器落成
        板项 + 唤醒标记），再读唤醒（否则这一轮读到的是"到点之前"的那份盘）。

        三态：`fire_due` 的 `checked=False` 与 `read_wakes` 的 `checked=False` 都
        不许折成"没有唤醒" —— 但它们也不许在这里多开一轮（那会烧钱）：
        读数进 `notes`，放行判据照旧按"读到的条数"走（读不成 ⇒ 0 条 ⇒ 不开轮）。
        """
        nonlocal clock_pump_note
        from . import agent_loop as AL

        try:
            from . import clock as CLK
        except Exception as exc:  # noqa: BLE001 —— 时钟这一层读不到是"没查成"
            clock_pump_note = f"时钟读不到（{type(exc).__name__}: {exc}）⇒ 这一格是 unknown"
            return []
        try:
            fired = CLK.fire_due(root)
        except Exception as exc:  # noqa: BLE001
            clock_pump_note = f"时钟推不动（{type(exc).__name__}: {exc}）⇒ 到点项这一轮可能漏"
        else:
            got = list(fired.get("fired") or ())
            clock_pump_note = (
                f"轮边界推时钟：推响 {len(got)} 条（checked={fired.get('checked')}）"
                if got or not fired.get("checked") else "")
        AL_clock = AL.pending_clock_wakes(root, role=role)
        if not AL_clock.get("checked"):
            clock_pump_note = (clock_pump_note + "；" if clock_pump_note else "") + \
                f"唤醒标记没读成（{AL_clock.get('reason')}）⇒ unknown"
            return []
        return [dict(e) for e in (AL_clock.get("events") or ())]

    def _stop_reason_for(next_index: int, last_stop_reason: str = "",
                         woke: int = 0) -> tuple[str, list[str], str]:
        """算"第 next_index 轮开跑前会不会停"，并现读一次用户频道（返回 `(原因, 说明, 回答)`）。

        第三个返回值是给下一轮的任务用的（`§14.5` 第 4 件）：读一次就用一次，
        不要在别处再读一遍 —— 两处各读一次会造出"停的判据用旧回答、任务用新回答"的错位。

        `last_stop_reason` 是「上一轮」的停止理由（`draft/37` §72）：上一轮停在等用户回答时，
        这里必须停，不许开下一轮。用户叫停那一族同理（D19，见 `_stop_before_round`）。
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
        # ---- D-53（业主 2026-10-24）：时钟唤醒也折进同一个 `wake_pending`。
        #
        # 改前这里只认"收件箱里还有没投递的留言" ⇒ 计时器到点（`clock.py` 落的
        # 那条唤醒标记）在这一层看不见，"到点后时钟自动给 M 发消息检查"的后半段
        # （M 真的拿到一个回合）结构上不会发生。
        # 为什么按角色读而不是按台账号：每一轮 `run_role` 都会新开一行台账号，
        # 上一轮起表时写下的 `task_id` 已经不是这一轮的编号（见 `pending_clock_wakes`）。
        clock_wakes = _pump_and_read_clock()
        if clock_pump_note and clock_pump_note not in answer_notes:
            answer_notes.append(clock_pump_note)
        nonlocal last_clock_wakes
        last_clock_wakes = list(clock_wakes)
        wake_pending += len(clock_wakes)
        reason = _stop_before_round(next_index, rounds=total_rounds, spent_usd=_spent_usd(),
                                    usd_budget=_round_budget(session_root, usd_budget),
                                    stop_path=stop_path,
                                    user_answer=answer, last_stop_reason=last_stop_reason,
                                    pending_qids=pending, wake_pending=wake_pending, woke=woke,
                                    stop_latch_reason=_user_stop_reading())
        return reason, answer_notes, answer

    def _bank_user_stop(why: str) -> dict[str, Any]:
        """用户叫停那一档的收尾：开关还在盘上就记进 `runs/stop-history.jsonl` 并撤走。

        为什么要在这里消费：`agent_loop` 那一趟读到开关时会自己消费（树根的删除落在
        它的收尾，见 `_consume_stop_at_teardown`），但"开关是在两轮之间出现的"这一档
        它根本没有机会读到（轮间判据在这一层）—— 不消费就等于把这把开关留在盘上，
        下一趟在第 0 轮被它再停一次（`draft/37` §140 的同一个 bug，方向反过来）。

        子树开关不撤：`stop_scope` 说它只管某一支时，撤掉它等于替那一支把"停"吃掉；
        这一层只停自己这一趟（`remove=False` 也不记，免得在历史里造一条不是这一趟的账）。

        三态：读不成 ⇒ `checked=False` + 理由；盘上没有 ⇒ 说明"已经被消费过"
        （不是"没人叫停"——`why` 已经把这一档说清楚了）。
        """
        try:
            state = stopctl.read_stop(root, explicit=stop_file)
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            return {"checked": False, "on_disk": None,
                    "reason": f"停机开关读不成（{type(exc).__name__}: {exc}）"}
        if state is None:
            # 开关已经不在盘上了（读到它的那一趟收尾时撤走）：去 `runs/stop-history.jsonl`
            # 找最近一笔同族的叫停，把它的负载带回来 —— 否则"按用户要求停"这句结论在检查点里
            # 只剩一个理由码，"谁按的、什么时候按的、是不是强制"三个读数全丢了。
            # 这不是"猜"：带回来的那一笔同时带着 `consumed_by_sid` / `consumed_at`，
            # 读的人分得清它是哪一趟消费的（可能是更早的某一趟）。
            recent: dict[str, Any] = {}
            try:
                for row in reversed(stopctl.stop_history(root, limit=20)):
                    if str(row.get("level") or "") in stopctl.USER_STOP_REASONS:
                        recent = dict(row)
                        break
            except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"没人叫停"
                recent = {}
                bank_note = f"（stop-history 没读成：{type(exc).__name__}: {exc}）"
            else:
                bank_note = ""
            keep = ("reason", "by", "force", "at", "level", "consumed_at",
                    "consumed_by_sid", "removed", "path")
            return {"checked": True, "on_disk": False, "consumed": False, "why": why,
                    "switch": ({k: recent[k] for k in keep if k in recent} if recent else None),
                    "reason": ("开关已经不在盘上了：读到它的那一趟收尾时把它撤走了"
                               "（审计在 runs/stop-history.jsonl 里）" + bank_note)}
        scope = stopctl.stop_scope(state)
        if not scope.get("checked") or scope.get("scope") != "all":
            return {"checked": True, "on_disk": True, "consumed": False, "why": why,
                    "scope": scope,
                    "reason": ("这把开关的作用面不是全工作区（或判不了）⇒ 这一层不撤："
                               "撤了会把别人那一支的一停吃掉")}
        try:
            record = stopctl.consume_stop(root, sid=sid, level=why,
                                          explicit=stop_file, remove=True)
        except Exception as exc:  # noqa: BLE001 —— 记账失败不许让"已经停下"这件事失效
            return {"checked": True, "on_disk": True, "consumed": False, "why": why,
                    "reason": f"记进 stop-history 失败（{type(exc).__name__}: {exc}）"}
        return {"checked": True, "on_disk": True, "consumed": bool(record), "why": why,
                "switch": dict(record),
                "reason": ("开关还在盘上 ⇒ 已记进 runs/stop-history.jsonl 并撤走"
                           if record else "开关在盘上但读不出负载 ⇒ 按这一档停下")}

    # 上一轮的停止理由（续跑时来自上一段的最后一轮）：`waiting_for_user` 会让这一次
    # 在开跑下一轮之前就停 —— 见 `_stop_before_round` 的 docstring。
    last_round_stop = prev_report.stop_reason if prev_report is not None else ""
    # ---- 续跑：上一段那一停已经兑付（D19 的第二层）
    #
    # 上一段以用户叫停收工（`stop_file` / `force_stop` / `interrupted_by_parent`）时，
    # 那份停意是针对「上一段」的，而且那把开关已经被消费掉了。这一趟是用户显式
    # `--resume` 重新叫起来的 —— 把上一段的理由码原样喂给 `_stop_before_round`，
    # 会让续跑在第 1 轮就当场停下（一次模型都不调），而 `--resume` 的整个意义就是"接着跑"
    # （退出码 4 那句话写的就是"可 --resume"）。
    # 判据与 D19 是同一句话：开关出现过、或仍在盘上 ⇒ 停；两者都不成立 ⇒ 那一停已经兑付。
    if (resume and last_round_stop in stopctl.USER_STOP_REASONS
            and not latched_stop and not stop_path.is_file()):
        notes.append(f"上一段以 {last_round_stop} 收工（用户叫停）：开关已经被消费、"
                     f"盘上没有（{stop_path}），这一趟是 --resume 重新叫起来的 ⇒ "
                     "按续跑继续，不把上一段那一停算到这一段头上")
        last_round_stop = ""
    #: 被唤醒多开的轮数（S-G，裁定 15）：只在超过 `total_rounds` 的那几轮上加一。
    woke_rounds = 0
    while True:
        reason, answer_notes, latest_answer = _stop_reason_for(index, last_round_stop, woke_rounds)
        for line in answer_notes:
            if line not in notes:
                notes.append(line)
        # （已删除）`user_stop` 那条"回答里含 STOP 就停"的分支随旁路一起删掉了：
        # 它会让一个已经不存在的常量参与 f-string（`STOP_TOKEN`）⇒ 一旦执行就 NameError。
        if reason:
            stop_reason = reason
            break

        # 续跑的第一轮：`reports` 是空的（那些轮在上一段），上一轮结论来自检查点
        previous = reports[-1] if reports else prev_report
        # S-G（裁定 15）：这一轮是不是"被唤醒多开的"（超过轮次预算 ⇒ 它必须是被唤醒开起来的，
        # 因为唯一的例外就是那条）。落进事件与读数，"为什么多跑了一轮"事后答得出来。
        woke = index > total_rounds
        # ---- D-53：这一轮如果是"被唤醒多开的"，它就是监控回合。
        #
        # 三件事在这一处落定，顺序不能换：
        # ① 消费掉那些唤醒标记（`consume_clock_wakes`）—— 只在"这一轮真的开跑"时消费，
        #    判停那一刻只读不消费（否则一轮被预算/叫停拦下时，唤醒就凭空消失了）；
        # ② 把唤醒理由作为 `monitoring_of` 交给 `run_role` —— 那一轮的第一条增量消息
        #    因此带树形读数与出口限定（`agent_loop._monitor_block`）；
        # ③ 计数（`woke_rounds`）与事件里的 `woke` 照旧（判据读的是同两个读数）。
        monitoring_of = ""
        if woke:
            woke_rounds += 1
            if last_clock_wakes:
                taken = AL.consume_clock_wakes(root, last_clock_wakes)
                for line in taken.get("problems") or ():
                    notes.append(line)
                consumed = list(taken.get("consumed") or ())
                if consumed:
                    monitoring_of = "；".join(
                        f"{e.get('reason')}（{e.get('wake_id')}）" for e in consumed)
                    _p, wake_problem = SS.append(root, {
                        "kind": "autonomy_wake", "role": role, "round": index,
                        "wake_ids": [str(e.get("wake_id") or "") for e in consumed],
                        "reasons": [str(e.get("reason") or "") for e in consumed],
                        "timer_ids": [str(e.get("timer_id") or "") for e in consumed],
                        "mailbox_item_ids": [str(e.get("mailbox_item_id") or "")
                                             for e in consumed],
                    }, sid=sid)
                    if wake_problem:
                        notes.append(f"第 {index} 轮的唤醒消费没落成：{wake_problem}")
            if not monitoring_of:
                # 收件箱里那一条唤醒（S-G）也开的是"监控回合"：两类唤醒的区别只在触发源。
                monitoring_of = "收件箱里有没投递的留言（S-G 的唤醒）"
            notes.append(f"第 {index} 轮是监控回合：{monitoring_of}")
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
                                user_timeout_sec=user_timeout_sec,
                                monitoring_of=monitoring_of)
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
    # ---- 收工时把"按用户要求停"那件事落成可读的账（D19 的收尾）
    #
    # 两处落点，各答一个问题：
    #   · `runs/stop-history.jsonl`（`stopctl.consume_stop`）：这把开关被哪一趟用掉、理由是什么；
    #   · `runs/autonomy-<角色>.json` 的 `stop_switch`：开关上写着谁在什么时候为什么按的。
    # 只在用户叫停那一族里做：别的停止理由（轮数用完 / 预算 / 等用户）没有开关可言。
    stop_switch: dict[str, Any] | None = None
    if (stop_reason or "rounds") in stopctl.USER_STOP_REASONS:
        bank = _bank_user_stop(stop_reason)
        if not bank.get("checked", False) or bank.get("reason"):
            notes.append(f"停机开关：{bank.get('reason')}")
        stop_switch = bank.get("switch") or (bank.get("scope") and {"scope": bank["scope"]})
        if stop_switch is None:
            # 盘上没有开关了（被消费掉）也留一份"这一趟是按用户要求停的"，而不是留空：
            # 留空与"没有用户叫停"在盘上长得一样，而这两种读数必须分得开。
            stop_switch = {"reason": "（开关已被消费，负载见 runs/stop-history.jsonl）",
                           "level": stop_reason}
    final_cp = save_checkpoint(root, role, fingerprint=fingerprint,
                               completed_rounds=resumed_from + len(reports),
                               rounds=total_rounds, task=task, spend=cumulative_end,
                               stop_reason=stop_reason or "rounds",
                               last_final=reports[-1].final if reports else prev_report.final,
                               stop_switch=stop_switch)
    if final_cp:
        notes.append(f"收工时的检查点没写成：{final_cp}")
    view = _spend_view(total)
    view["baseline_usd"] = round(float(baseline["usd"]), 6)
    return AutonomyRun(role=role, task=task, rounds_done=len(reports), reports=reports,
                       stop_reason=stop_reason or "rounds", spend=view, woke_rounds=woke_rounds,
                       notes=notes, resumed_from=resumed_from, checkpoint=str(cp_path))


# ------------------------------------------------------------------ 自检
def selftest() -> int:
    """自检：三轮跑完 + 阶段汇报 + 预算为零不碰模型 + 回答不算停 + 没接线如实停。

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
        gw = Scripted([json.dumps({"final": f"第 {i} 轮结论：还差一步"}, ensure_ascii=False, default=str)
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

        # 负控：回答里写「停」不再让这一程停（业主 2026-10-17「删掉旁路」）。
        #
        # 这一格改前验的是"用户说 STOP ⇒ 一轮都不跑"，而那条字面匹配已经按业主口径删掉了
        # （停意由主控理解意思后调 `conductor.stop` 完成）—— 于是这一格从删旁路那天起
        # 就一直是红的（在 HEAD 版上重跑同一段可得 `rounds_done=3`）。现在它验的是现状：
        # 一句不含状态信号的回答（「先停一停吧」）不是停机判据；真停机走
        # `stopctl.USER_STOP_REASONS` 那三档（`stop_file` / `force_stop` /
        # `interrupted_by_parent`），判据见 `tests/test_autonomy.py` 的
        # `test_a_user_answer_with_stop_addressed_to_the_role_stops_the_run`。
        from . import userio

        SS.append(root, {"kind": "user_question", "qid": "q0001", "role": "D",
                         "text": "还要继续吗？"}, sid="self3")
        userio.answer_question(root, qid="q0001", answer="先停一停吧", sid="self3")
        answered = Scripted([json.dumps({"final": "照回答做完了"}, ensure_ascii=False,
                                        default=str)])
        stopped = run_autonomous("D", "接着做", store=store, registry=registry,
                                 gateway=answered, rounds=3, sid="self3")
        check(stopped.rounds_done >= 1 and stopped.stop_reason != "user_stop",
              f"回答里写「停」被当成了停机判据（那条旁路已按业主 2026-10-17 删掉）："
              f"{stopped.to_dict()}")

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
    print("SELF-CHECK DONE（三轮与阶段汇报 / 预算 / 回答不算停 / 没接线四条路）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())

# -*- coding: utf-8 -*-
"""「秘书」：每个智能体自带的随员（`draft/53` v3 定位 · `draft/55` 接口规范 · `draft/54 §2`）。

## 它与其它角色的分别（一句话）

它不是一个同级角色：不占 `schema.ROLES`、不加注册工具、不改权限面声明、
不改 `llmseam` 的 enum、不重冻快照 ⇒ 一个计数都不变（`draft/54 §2.2` 的"明确不动"）。
它是"每个智能体都有的"那一个：同一个类，每角色一份配置（自己的角色定位 + 自己的
收发箱），先建 M 的，再批量给 A–H 装（批量 = 配置 + 每角色一条测试，不是新代码）。

## 四条职责（用户 2026-10-06 逐字裁定，`draft/53` §2）

| # | 职责 | 谁的秘书做 | 本模块的落点 |
|---|---|---|---|
| 1 | 格式与内容优化 | 发件方 | :meth:`Secretary.optimize_outbound`（对齐参数表/必填/工具真名；不替本体承诺） |
| 2 | 委派评估 | 发件方 | :meth:`Secretary.assess_delegation`（收件方真做得到吗 + 该不该派） |
| 4 | 委托加工 | 收件方 | :meth:`Secretary.rework_inbound`（按本角色定位改说法，不加码不减码） |
| 3 | 闭环提醒 | 收件方 | :meth:`Secretary.remind_closure`（未接手 / 未反馈；经 M） |

两条实质性红线（`draft/53` §2）：格式补不全、或加工后发现实质缺陷
（错的对象 / 缺前提 / 结论与证据不符）⇒ 与对方协商，不静默修。
本模块的形态是 :meth:`Secretary.negotiate`（≤2 轮）+ 台账留痕 —— 它从不替本体表态。

## 它另外持有的：手稿通道的增 / 改 / 查（`draft/55` §3）

用户原话："至少要能读 handoffs，且由于所有信息交互都由秘书过一遍手，
所以 handoffs 的增改查能力都该给秘书，智能体只保留'查'的能力。"

- 增 = :meth:`Secretary.handoff_add`（既有 `manuscripts.write`；行里的 `sender`
  仍是被服务的角色 —— 作者=角色、执笔=秘书，`manuscript_rows` 口径不变）；
- 改 = :meth:`Secretary.handoff_revise`（新增 `manuscripts.revise`，追加修订行、不改旧行）；
- 查 = :meth:`Secretary.handoff_query`（既有 `manuscripts.read/list_all/query/...`）。

智能体侧只保留"查"：`agent_loop` 的循环形状 `handoff` 与 `summon` 的 `notify`
派生写都改由本模块执笔（`agent_loop.AgentLoop._do_handoff`）。

## 权限与失败姿态（`draft/55` §4）

- 库表只读（写集 ∅）；文件两处写：手稿通道 + 自己的台账 `out/secretary/<role>.jsonl`；
- 不使用注册工具（工具面为空：只有"手稿通道增改查 + 只读读数 + 自己台账"三类内部能力）；
- 信息面 ≤ 本体，且 V 的秘书不读 F 的叙述（I12 的审校独立性不许被秘书绕过，
  `draft/55` §1.5）；
- fail-open：超时/出错 ⇒ 原样放行 + 留痕（阻塞一条委托比放行更贵 —— 那就是 #1）。
  唯一例外：手稿执笔失败必须报错留痕（静默放行会让手稿缺行，而"缺行"
  与"没交接"在账本上长得一样）；
- 不做任何统计：不计算拒绝率 / 重复率 / 闭环率，也不做花销统计与花销告警
  （用户 2026-10-06：那套统计是坏设计，去掉）。它是判断者，不是仪表盘 ——
  效果由机器读数与人评估（`tasks`/`sessions` 本来就能算）。

## 成本控制：机器预筛 + 按需介入（`draft/53` §6）

每条消息都过一次模型 ⇒ 调用量与花销翻倍。所以 :meth:`Secretary.should_engage`
只在预筛报警 / 出现重复候选 / 闭环逾期 / 首次遇见该形态时才说"叫秘书"。
本模块的默认路径是确定性的（不需要模型、不需要网络）：这是刻意的 ——
"能机器判的"不许推给模型，而秘书拿到的是读数 + 候选，不是判决书。
"""
from __future__ import annotations

import datetime as _dt
import json
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import manuscripts as MS
from . import schema as S

#: 台账落点：`<工作区>/out/secretary/<role>.jsonl`（追加式、脚本发号，`draft/53` §11.2）。
SECRETARY_DIR = ("out", "secretary")
#: 发件/收件的单次模型调用上限（`draft/55` §5.2：1 次调用、≤3 秒，超时放行）。
DEFAULT_DEADLINE_SEC = 3.0
#: 秘书 ⇄ 秘书协商的轮数上限（`draft/55` §5.2：最多 2 轮，之后上报本体）。
MAX_NEGOTIATION_ROUNDS = 2
#: 一次最多几条闭环提醒（`draft/55` §5.2：默认 5，避免刷屏）。
MAX_REMINDERS = 5
#: 六种事件名（`draft/55` §5.1）—— 常量在这里是为了让"冒充本体"这件事结构上不可能：
#: 秘书发出的每一条都带 `secretary/` 前缀。
KIND_OPTIMIZED = "secretary_optimized"
KIND_HANDOFF = "secretary_handoff"
KIND_NOTICE = "secretary_notice"
KIND_PROPOSAL = "secretary_proposal"
KIND_QUESTION = "secretary_question"
KIND_NEGOTIATION = "secretary_negotiation"
KIND_DECISION = "secretary_decision"
#: 秘书的判断结论词表（`draft/55` §2 的 B 类）。
DECISIONS = ("可派", "建议重排", "建议改派", "建议不派", "已优化", "已提醒", "已执笔")


def decisions_path(root: str | Path, role: str, task_id: str = "") -> Path:
    """这一名秘书的决定台账路径。

    - `task_id` 空 ⇒ 老文件 `out/secretary/<role>.jsonl`（每角色一份，绝不混写 ——
      `draft/53` §5 的防错①）：历史行仍然在这里，读侧必须继续读得到；
    - `task_id` 给了 ⇒ 分片 `out/secretary/<role>-<task_id>.jsonl`（S1m）：
      一实例一片、一个写者一片，于是同角色的并发实例（`summon_many` 的多 `instance`）
      不再往同一个文件里挤（D106/D107 的修法）。

    注意：名字刻意不叫 `ledger_path` —— 那个名字在 `artifacts.py`（产物归属台账）与
    `signatures.py`（签名台账）里各有一份独立实现，而秘书的决定台账与它们不是
    同一件事 —— 合并它们会把三件不同的事折成一个（lint R003 的口径是"同一判据
    的两份实现必须合并"，这里恰恰不是同一判据，所以正确的做法是改名字而不是合并）。
    """
    name = f"{role}-{task_id}.jsonl" if str(task_id or "") else f"{role}.jsonl"
    return Path(root).joinpath(*SECRETARY_DIR, name)


#: 同一进程里按路径复用的追加锁（与 `sessions.append` 同一做法）。
_APPEND_LOCKS: dict[str, Any] = {}
_APPEND_LOCKS_GUARD = threading.Lock()


def _append_lock(path: Path) -> Any:
    """同一路径的进程内锁（`filelock` 在同进程里不是线程安全的，两层都要）。"""
    key = str(path)
    with _APPEND_LOCKS_GUARD:
        lock = _APPEND_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _APPEND_LOCKS[key] = lock
        return lock


def append_jsonl(path: str | Path, rec: Mapping[str, Any]) -> tuple[bool, str]:
    """唯一的秘书台账追加口（S1m）：进程内锁 + 跨进程 `filelock`，`seq` 在锁内算。

    返回 `(写成了吗, 问题)`。为什么必须集中到一处（`draft/91` §7 的 D107）：旧写法是
    "先读全表算 `seq = max+1`、再 `path.open("a")` 追加" —— 读与写之间没有锁，
    同角色的两个实例并发时会拿到同一个 `seq`（与 `_write_new_row` 修过的那个缺陷同族）。

    `seq` 的口径是每片自增（片就是"一个实例的账"），所以两片之间 `seq` 可以重复 ——
    合并视图（`Secretary.merged_decisions`）按 `at` 排序，不靠 `seq` 全局唯一。
    """
    from filelock import FileLock

    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    line = json.dumps(dict(rec), ensure_ascii=False, sort_keys=True) + "\n"
    with _append_lock(target):
        try:
            with FileLock(str(target) + ".lock", timeout=30.0):
                seq = 1
                if target.is_file():
                    text = target.read_text(encoding="utf-8", errors="replace")
                    for raw in text.splitlines():
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            row = json.loads(raw)
                        except Exception:  # noqa: BLE001 —— 坏行不参与取号
                            continue
                        if isinstance(row, dict):
                            seq = max(seq, int(row.get("seq") or 0) + 1)
                out = dict(rec)
                out["seq"] = seq
                line = json.dumps(out, ensure_ascii=False, sort_keys=True) + "\n"
                with target.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(line)
        except Exception as exc:  # noqa: BLE001 —— 写不成要如实报（调用方留痕）
            return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _pid_alive(pid: int) -> bool:
    """这个 pid 还活着吗 —— 复用 `stopctl.alive`（一处实现，不抄第二份）。

    为什么不自己写：探活在 Windows 上有两个坑，`stopctl.alive` 的 docstring 逐字记着 ——
    `tasklist` 在沙箱里拿不到读数（本机实测：登记了自己的 pid 也判"不活着"），
    而 `os.kill(pid, 0)` 在 Windows 上不是探活、它会 `TerminateProcess`。
    本模块第一版正是踩了第一个坑（自己起 `tasklist` + 管子拿输出 ⇒ 沙箱里 EPERM），
    冒烟时就判出自己的 pid "不活着"。
    """
    try:
        from . import stopctl

        return bool(stopctl.alive(int(pid)))
    except Exception:  # noqa: BLE001 —— 查不成 ⇒ "不知道"，由调用方的三态说
        return False


# ---------------------------------------------------------------- 名册与对照表（S1k）
#
# 落点：`out/roster/<owner>.jsonl`（名册）、`<owner>-index.jsonl`（电话簿）、
# `<owner>-retired.jsonl`（销号名单）。三份都 append-only，读侧折叠。
# 为什么不放 `out/secretary/`：`webui/readers.py` 是目录 glob（`*.jsonl`），
# 同目录会把名册行混进"秘书决定台账"那一面（`draft/92` §2 的落点说明）。

ROSTER_DIR: tuple[str, ...] = ("out", "roster")


def roster_path(root: str | Path, owner: str) -> Path:
    """名册（`owner` = 父的绝对编码）。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}.jsonl")


def roster_index_path(root: str | Path, owner: str) -> Path:
    """对照表（电话簿）：本地名 → 当前调用行。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}-index.jsonl")


def retired_path(root: str | Path, owner: str) -> Path:
    """销号名单（业主 B1：名字一经退役永久不复用；后续版本的新功能读它）。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}-retired.jsonl")


# ---------------------------------------------------------------- 读写面与槽位池（S1n）
#
# 业主 T23：子代理只能读写父切割给它的面；父原则上必须把各子代理的面拆开（不重叠）；
# 面内的新文件允许。退役之后面归还"可分配池"（名字不回收，面回收）。
# 落点：`out/surfaces/<owner>/<slot>/`（面本体）、`out/roster/<owner>-surfaces.jsonl`（池事件）、
# `out/surfaces/archive/<owner>-<name>/`（归还前的归档）。

SURFACES_DIR: tuple[str, ...] = ("out", "surfaces")

#: 哪些工具的哪些参数是"落在盘上的路径"（`draft/90` §1.11 / §2 的 E22）。
#:
#: 默认规则：`fs.*` 的 `path`。名字不叫 `path` 的逐条登记在这里 —— 今天只有
#: `fs.move`（它的 schema 是 `{'src','dst'}`，没有 `path`，于是它在 S1n-b 的硬拦里
#: 整个漏掉了：子代理可以用它把面外的文件搬进自己的面）。
#:
#: 这张表只有一处，两个时机共用：预看（`Secretary.surface_fit`）与硬拦
#: （`AgentLoop._surface_refusal`）。分两份写迟早出现"预看说越界、硬拦放过去"
#: 这种自相矛盾，而两边的判据都会是绿的。
SURFACE_PATH_ARGS: dict[str, tuple[str, ...]] = {"fs.move": ("src", "dst")}


def surface_path_args(action: str) -> tuple[str, ...]:
    """某个工具/动作里"是路径"的那几个参数名（空元组 = 这个动作没有可判的盘上路径）。

    读不到名字（空串）⇒ 空元组；非 `fs.` 的动作一律空元组（面这一维今天只说 `fs.*`，
    与 `AgentLoop._surface_refusal` 同一条范围）。
    """
    name = str(action or "")
    if not name.startswith("fs."):
        return ()
    return ("path",) + tuple(SURFACE_PATH_ARGS.get(name, ()))


def surfaces_path(root: str | Path, owner: str) -> Path:
    """池事件流（`alloc` / `release` / `archive_failed`），append-only。"""
    return Path(root).joinpath(*ROSTER_DIR, f"{owner}-surfaces.jsonl")


def surface_dir(root: str | Path, owner: str, slot: str) -> Path:
    """一个槽位的面（目录）。"""
    return Path(root).joinpath(*SURFACES_DIR, owner, str(slot))


def archive_dir(root: str | Path, owner: str, name: str) -> Path:
    """归还前把面里的东西归档到这里（业主口径的反面：新子代理不该看到前任的文件）。"""
    return Path(root).joinpath(*SURFACES_DIR, "archive", f"{owner}-{name}")


def _fold_surfaces(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把池事件流折叠成"每个槽位此刻在哪一档"（空闲 / 在用 / 待释放）。"""
    items: dict[str, dict[str, Any]] = {}
    for raw in rows:
        r = dict(raw)
        slot = str(r.get("slot") or "")
        if not slot:
            continue
        item = items.setdefault(slot, {"slot": slot, "name": "", "state": "空闲"})
        kind = str(r.get("kind") or "")
        if kind == "alloc":
            item["name"] = str(r.get("name") or "")
            item["state"] = "在用"
        elif kind == "release":
            item["name"] = ""
            item["state"] = "空闲"
            item.pop("reason", None)
        elif kind == "archive_failed":
            item["name"] = str(r.get("name") or "")
            item["state"] = "待释放"
            item["reason"] = str(r.get("reason") or "")
    return [items[k] for k in sorted(items)]


def _fold_roster(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把名册事件流折叠成"当前状态"（一项一条）。

    口径：`add` 建项（后写的同名字覆盖 `retired` 标记为 False 是不可能的 ——
    名字不复用，所以同名字只会有一次 `add`）；`bind` 推当前调用；`retire` 标退役；
    `keep_alive` 只记那一格。
    """
    items: dict[str, dict[str, Any]] = {}
    for raw in rows:
        r = dict(raw)
        name = str(r.get("name") or "")
        if not name:
            continue
        item = items.setdefault(name, {"name": name, "role": str(r.get("role") or ""),
                                       "brief": "", "task_id": "", "retired": False})
        kind = str(r.get("kind") or "")
        if str(r.get("role") or ""):
            item["role"] = str(r.get("role") or "")
        if kind == "add":
            item["brief"] = str(r.get("brief") or "")
            item["task_id"] = str(r.get("task_id") or "")
            item["first_task_id"] = str(r.get("first_task_id") or r.get("task_id") or "")
            item["surface"] = str(r.get("surface") or "")
        elif kind == "bind":
            item["task_id"] = str(r.get("task_id") or item.get("task_id") or "")
        elif kind == "retire":
            item["retired"] = True
            item["retired_branch"] = str(r.get("branch") or "")
        elif kind == "keep_alive":
            item["keep_alive"] = bool(r.get("value"))
    return [items[k] for k in sorted(items)]


def _fold_index(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把对照表折叠成"名字 → 当前调用（+ 第一次那个）"。

    `bind` 推当前；`retire` 标退役（行保留：编码不回收，反查还要用）。
    """
    items: dict[str, dict[str, Any]] = {}
    for raw in rows:
        r = dict(raw)
        name = str(r.get("name") or "")
        if not name:
            continue
        item = items.setdefault(name, {"name": name, "role": str(r.get("role") or ""),
                                       "task_id": "", "first_task_id": "",
                                       "retired": False})
        if str(r.get("role") or ""):
            item["role"] = str(r.get("role") or "")
        if str(r.get("kind") or "") == "retire":
            item["retired"] = True
            continue
        item["task_id"] = str(r.get("task_id") or item.get("task_id") or "")
        if r.get("first") or not item.get("first_task_id"):
            item["first_task_id"] = str(r.get("task_id") or item.get("first_task_id") or "")
    return [items[k] for k in sorted(items)]


def _state_from(branch: str, retired: bool, cond: Any, task_id: str) -> str:
    """四态折叠（`draft/92` §2）：活跃 / 待命 / 已停 / 已退役。

    `branch` 来自 `conductor.retire_ready`（`active` / `waiting_with_children` /
    `waiting_no_children`）；"待命"再看 `keep_alive_of`（那一格只回答"声明过待命没有"）。
    两个读侧正交，折叠只在这一处做（不许让它们互相猜）。
    """
    if retired:
        return "已退役"
    if branch == "active":
        return "活跃"
    if not branch:
        return "未登记"
    try:
        ka = cond.keep_alive_of(task_id)
    except Exception:  # noqa: BLE001
        ka = {"checked": False}
    if ka.get("checked") and ka.get("keep_alive"):
        return "待命"
    return "已停"


def _clip_text(text: str, limit: int) -> str:
    """剪一段可读的正文（多余部分写清"还有多少字没进来"，不许静默截断）。"""
    body = str(text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit] + f"…（还有 {len(body) - limit} 字没进来，全文用 manuscripts.read 读）"


def _as_mapping(value: Any) -> dict[str, Any]:
    """把一个"看起来像声明"的对象读成 dict（`RoleBrief` 是 dataclass，不是 Mapping）。

    读不出来（`None` / 别的类型）就返回空表，且只在最后一个分支返回它 ——
    调用方必须把"空表"读成"这一格判不了"，不是"没有定位"。
    """
    import dataclasses

    if isinstance(value, Mapping):
        return dict(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    return {}


def declarations_candidates(name: str, names: Iterable[str], *, limit: int = 3) -> list[str]:
    """错名的并列候选（薄转发到 `tools.base.candidate_tool_names`，判据只有一份）。

    为什么在这里再包一层：秘书不使用注册工具，但它必须能回答
    "这个名字是不是真名"（职责 1）。转发而不是重写 —— 两份候选算法必然分叉，
    而分叉的形态是"机器给的候选与秘书给的候选不是同一批"。
    """
    from .tools.base import candidate_tool_names

    return candidate_tool_names(name, names, limit=limit)


class Secretary:
    """一名智能体的秘书（`draft/53` v3 §4：一个共享类 + 每角色一个实例）。

    参数
    ----
    role : 它服务的那名智能体（`"M"` / `"A"`…/`"V"`）。台账按它分文件。
    root : 工作区根（手稿通道与台账都挂在它下面）。
    store : 可选的 `Store`（只读：`tasks` / 会话事件）。给了就读，不给就跳过那一层读数。
    registry : 可选的工具注册表（只读：判"工具名是不是真名"）。
    seam : 可选的 `LlmSeam`（用本智能体自己的缝，`scope="secretary"`）。
        不给 ⇒ 判断那一格判不了（`judge()` 返回 `checked=False`），预筛与留痕照常。
    enable_model : 要不要用模型做"判断"（见 :meth:`judge`）。默认 False：
        确定性预筛是机器该做的，而"要不要为此花钱"是一次明确的取舍（`P-09` 的粒度）。
        生产装配把它打开是一行的事（`Secretary(..., seam=<本体的缝>, enable_model=True)`）。
    log : 可选日志口子（失败留痕的第二个落点）。

    本类没有写集：它不 `store.tx(...)`、不写任何库表、不改任何受保护文件。

    两类产物分得很清（这是本项目最忌的那种折平）：

    | 类 | 判据 | 形态 | 例子 |
    |---|---|---|---|
    | 预筛 | 确定性、来自既有声明 | 报警清单（字符串） | 参数缺必填 / 工具名不是真名 / 动作不在能力表 |
    | 判断 | 需要语义、"该不该" | :meth:`judge` 一次模型调用 + 台账 | 重复候选算不算正当重试 / 错名映到哪个 / 建议重排成什么 |
    """

    def __init__(self, role: str, *, root: str | Path, store: Any = None,
                 registry: Any = None, seam: Any = None, log: Any = None,
                 deadline_sec: float = DEFAULT_DEADLINE_SEC,
                 enable_model: bool = False, sid: str | None = None) -> None:
        self.role = str(role)
        self.root = Path(str(root))
        self.store = store
        self.registry = registry
        self.seam = seam
        self.log = log
        self.deadline_sec = float(deadline_sec)
        #: 会话号（花销归因要读 `llm_call` 事件；`None` = 缺省会话，与 `llmseam` 同一口径）。
        self.sid = sid
        #: 判断类要不要真发一次模型调用（`draft/53` §12 / `draft/55` §5.2）。
        #: 关着的时候 :meth:`judge` 仍然返回三态中的"没查成"（`checked=False` + 理由），
        #: 于是"判断没做"与"判断过了、可派"在台账上永远分得开。
        #:
        #: 生产装配由 `agent_loop._secretary_for` 打开它（主控裁定 A5）：
        #: 用本体自己的那一个缝（同一个实例 ⇒ 角色/scope/账本一致，钱记在同一条账上）。
        self.enable_model = bool(enable_model)
        #: 写集恒为 ∅ 的声明式落点：它让"秘书有没有写集"成为一个可读的事实，
        #: 而不是"读遍本文件找不到 store.tx 所以大概没有"。
        self.writes: frozenset[str] = frozenset()
        self._negotiations: list[dict[str, Any]] = []
        #: 这个秘书服务的实例（台账号）。由 `bind_task` 在循环开跑时绑上（S1m）：
        #: 绑上之后台账分片到 `out/secretary/<role>-<task_id>.jsonl`，于是同角色的并发实例
        #: 各写各的片（今天只有角色维度 ⇒ 两个 D 实例会把记录写进同一个文件，读的人分不出是谁）。
        self.task_id: str = ""
        #: 最近一次判断的墙钟（秒）与最近一次闭环该不该介入的读数 —— 都是读数，
        #: 不是判据（fail-open 的代价要看得见，但不许拿它去卡任何一条委托）。
        self._last_judge_elapsed = 0.0
        self._last_closure_engage = False

    # ------------------------------------------------------------ 台账（E 类：记录）

    def bind_task(self, task_id: str) -> None:
        """把这一名秘书绑到它服务的实例上（S1m）。绑上之后台账分片。

        为什么必须有这一步：秘书的台账先前只有角色维度
        （`out/secretary/<role>.jsonl`），而同角色的并发实例（`summon_many` 的多 `instance`）
        会写进同一个文件 —— 读的人分不出哪一行是哪一个代理写的（`draft/91` §7 的 D106）。
        绑定之后每一实例一片（`<role>-<task_id>.jsonl`），一个写者一片。
        同时写一份存活标记（`secretary_alive` 读它）——"与它同生同死"的第一半。
        """
        self.task_id = str(task_id or "")
        if not self.task_id:
            return
        try:
            path = self.decisions_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            alive = self.alive_path()
            alive.write_text(json.dumps({"role": self.role, "task_id": self.task_id,
                                         "pid": __import__("os").getpid(),
                                         "at": _now_iso()}, ensure_ascii=False) + "\n",
                             encoding="utf-8", newline="\n")
        except OSError as exc:  # 留痕失败不许带走这一趟（但也不静默）
            self._log(f"秘书存活标记没写成：{type(exc).__name__}: {exc}")

    def close(self) -> dict[str, Any]:
        """收尾：注销存活标记，返回读数（"同生同死"的第二半）。失败也如实报。"""
        out: dict[str, Any] = {"checked": True, "closed": False, "reason": "", "task_id": self.task_id}
        if not self.task_id:
            out["checked"] = False
            out["reason"] = "这一名秘书没绑定实例（没有分片、也没有存活标记）"
            return out
        try:
            self.alive_path().unlink(missing_ok=True)
            out["closed"] = True
        except OSError as exc:  # 删不掉不影响"这一趟结束了"这个事实，但要留痕
            out["reason"] = f"{type(exc).__name__}: {exc}"
            self._log(f"秘书存活标记没删掉：{out['reason']}")
        return out

    def alive_path(self) -> Path:
        """存活标记的路径（按实例分片，与台账同一命名规则）。"""
        return Path(str(self.decisions_path()) + ".alive")

    def secretary_alive(self) -> dict[str, Any]:
        """这一名秘书"还活着吗"（三态）：`{"checked","alive","pid","at","reason"}`。

        口径：标记在 = 绑过；`pid` 还活着 = 真的在跑（进程死了但标记还在 ⇒
        `alive=False` 且 `stale=True`，"上次没善终"是看得见的事实）。读不到标记 ⇒
        `checked=False`（"没查成"与"没绑过"分开）。
        """
        out: dict[str, Any] = {"checked": False, "alive": False, "pid": 0, "at": "",
                               "stale": False, "reason": ""}
        try:
            raw = self.alive_path().read_text(encoding="utf-8")
        except FileNotFoundError:
            out["checked"] = True
            out["reason"] = "没有存活标记（没绑过实例，或已经注销）"
            return out
        except OSError as exc:
            out["reason"] = f"{type(exc).__name__}: {exc}"
            return out
        try:
            got = json.loads(raw.strip().splitlines()[0])
        except Exception as exc:  # noqa: BLE001 —— 标记坏了 = 没读成，不许折成"死"
            out["reason"] = f"标记读不成：{type(exc).__name__}: {exc}"
            return out
        out["checked"] = True
        out["pid"] = int(got.get("pid") or 0)
        out["at"] = str(got.get("at") or "")
        out["alive"] = _pid_alive(out["pid"])
        out["stale"] = not out["alive"]
        return out

    def decisions_path(self, task_id: str | None = None) -> Path:
        """这一名秘书的台账路径（S1m 起分片）：绑了实例 ⇒ 分片，没绑 ⇒ 老文件。

        `task_id` 显式给了就用它；不给就用 `self.task_id`（`bind_task` 绑的那个）。
        """
        return decisions_path(self.root, self.role, task_id if task_id is not None else self.task_id)

    def decisions(self) -> list[dict[str, Any]]:
        """本角色台账里的全部行（坏行读不出来 ⇒ 如实报，不折成"没有决定"）。

        `read_jsonl` 把坏行单独报出来；这里只交回行，坏行由 :meth:`decision_problems` 报。
        口径（S1m）：老文件 + 本实例分片（绑了才读第二份）—— 这是"这一名秘书"的视角；
        整角色的合并视图是 `merged_decisions`（WebUI 直接 glob 目录，读得到全部片）。
        """
        return self._read_ledger()[0]

    def merged_decisions(self) -> list[dict[str, Any]]:
        """整角色视图：老文件 + 全部 `<role>-*.jsonl` 分片（按 `at`/`seq` 排序）。

        为什么要它：分片之后"这个角色的秘书都决定过什么"需要一处读侧
        （`knowledge()` 与 WebUI 那一面都靠它），否则读的人会以为"分片 = 记录变少了"。
        坏行照样只报不折。
        """
        from . import jsonlfile as JF

        rows: list[dict[str, Any]] = []
        base = Path(self.root).joinpath(*SECRETARY_DIR)
        paths = []
        for name in (f"{self.role}.jsonl", *(p.name for p in
                                            sorted(base.glob(f"{self.role}-*.jsonl")))):
            p = base / name
            if p.is_file() and p not in paths:
                paths.append(p)
        for p in paths:
            got, _bad = JF.read_jsonl(p)
            rows.extend(got)
        rows.sort(key=lambda r: (str(r.get("at") or ""), int(r.get("seq") or 0)))
        return rows

    def decision_problems(self) -> list[str]:
        """台账里的坏行说明（空列表 = 全都读得出来）。"""
        return self._read_ledger()[1]

    def _read_ledger(self) -> tuple[list[dict[str, Any]], list[str]]:
        from . import jsonlfile as JF

        rows, problems = JF.read_jsonl(decisions_path(self.root, self.role))
        if self.task_id:
            got, bad = JF.read_jsonl(self.decisions_path())
            rows = rows + got
            problems = problems + bad
        return rows, problems

    def note_decision(self, *, duty: int, kind: str = KIND_DECISION, decision: str = "",
                      reason: str = "", basis: Sequence[str] = (), target: Any = None,
                      before: str = "", after: str = "", mid: str = "",
                      changes: Sequence[Mapping[str, Any]] = (),
                      negotiation: Sequence[Mapping[str, Any]] = (), fail_open: bool = False,
                      error: str = "", judge: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """追加一行台账（`draft/55` §5.3 的字段表）。

        原文与加工后并列（`before` / `after`）：只留结论会让复核无从下手 ——
        "过程"是这一层唯一能自证的东西。

        `changes`（S1g）：逐格写"洗了什么"（`[{"field","from","to","why"}]`）。
        只留 `before`/`after` 两份全文也能 diff 出来，但"哪几格是秘书动的"必须一眼可读
        —— 否则"模型写错了"与"秘书替它补对了"在纸上长得一样（`draft/90` §1.2）。

        写入走 `append_jsonl`（S1m）：锁内算 `seq`、进程内 + 跨进程两层锁。
        旧写法（先读全表算 `seq`、再裸 `open("a")`）在并发下会重号（D107）。
        """
        rec: dict[str, Any] = {
            "at": _now_iso(),
            "role": self.role,
            "task_id": self.task_id,
            "duty": int(duty),
            "kind": str(kind or KIND_DECISION),
            "from": f"secretary/{self.role}",
            "fail_open": bool(fail_open),
        }
        if target is not None:
            rec["target"] = target
        if before:
            rec["before"] = str(before)
        if after:
            rec["after"] = str(after)
        if decision:
            rec["decision"] = str(decision)
        if reason:
            rec["reason"] = str(reason)
        if basis:
            rec["basis"] = [str(x) for x in basis]
        if negotiation:
            rec["negotiation"] = [dict(x) for x in negotiation]
        if changes:
            # S1g：逐格写"秘书动了哪几格"。只留 before/after 两份全文也能 diff，
            # 但读的人要的是"哪几格是秘书动的"（否则模型写错与秘书补对分不开）。
            rec["changes"] = [dict(x) for x in changes]
        if judge is not None:
            # 判断类的那一格：`checked` / `decision` / `reason` 一起落台账 ——
            # 只落结论会让"没查成"与"查过了没问题"在纸上长得一样。
            rec["judge"] = dict(judge)
        if mid:
            rec["mid"] = str(mid)
        if error:
            rec["error"] = str(error)
        path = self.decisions_path()
        ok, problem = append_jsonl(path, rec)
        if not ok:
            # 台账写不成不许带走秘书的判断（fail-open 的第一层：留痕是手段不是目的）。
            # 但也不静默：日志口子与返回值两条路都留下这件事。
            self._log(f"秘书台账没写成：{problem}")
            rec["ledger_problem"] = problem
            return rec
        # 写成了：把锁内定的 `seq` 读回来（`append_jsonl` 返回的是"写成没写成"；
        # 这里再读一次只为把 `seq` 放进返回值 —— 与旧行为对齐，读侧仍然只认盘上的那一行）。
        rows, _bad = self._read_ledger()
        for row in reversed(rows):
            if (str(row.get("at") or "") == str(rec.get("at") or "")
                    and str(row.get("kind") or "") == str(rec.get("kind") or "")):
                rec["seq"] = int(row.get("seq") or 0)
                break
        return rec

    # ------------------------------------------------------------ 知识面（只读，§1）

    def knowledge(self) -> dict[str, Any]:
        """秘书能读什么（全部只读，`draft/55` §1）。

        四层：硬性要求 / 全角色的定位（组织图全开）/ 委托事实 / 读数。
        返回一个可读的事实表（不是权限授予）：`writes` 恒为 `∅`，
        `reads_narrative` 回答"它读不读研究叙事正文"（一般角色不读、V 更严）。
        """
        briefs: dict[str, dict[str, Any]] = {}
        emphasis: dict[str, Any] = {}
        for role in S.ROLES:
            one = self._role_brief(role)
            if one:
                briefs[role] = dict(one)
        actions = self._action_table()
        return {
            "roles": sorted(set(S.ROLES) | {S.CONDUCTOR_ROLE}),
            "briefs": briefs,
            "emphasis": emphasis,
            "actions": actions,
            "tools": self._tool_names(),
            "writes": self.writes,
            "reads_narrative": False,
            "ledger": str(decisions_path(self.root, self.role)),
            #: S1m 的两格：绑过实例 ⇒ 分片路径非空（"我这一名秘书"的账在这儿）；
            #: `ledger_legacy` 是历史那一份（老工作区里全部决定都在它里面）。
            #: 三格都给，是因为分片之后"这个角色的账在哪"必须读得出来（否则读侧会以为记录变少了）。
            "ledger_instance": str(self.decisions_path()) if self.task_id else "",
            "ledger_legacy": str(decisions_path(self.root, self.role)),
        }

    def may_read_narrative(self, role: str) -> bool:
        """本秘书能不能读 `role` 的叙述（研究数据面，不是定位面）。

        `draft/55` §1.5 ②：一般角色的秘书"数据面 ≤ 本体"；而 V 的秘书另有更严的
        隔离 —— 不读 F 的叙述、不读被审证明之外的上下文。理由逐字：
        I12 靠"冷启动不给 store 句柄、不给 F 的叙述"保证审校独立性 ⇒ 若 V 的秘书
        读全库（含 `handoffs` 正文、会话叙事），它就成了绕过 I12 的暗通道。

        本方法只回答"读不读得到"，不回答"读了要不要用" —— 后者是判断。
        """
        want = str(role or "")
        if self.role == "V":
            return False
        return want == self.role

    def _role_brief(self, role: str) -> Mapping[str, Any]:
        """某角色的六字段 brief（`agent_prompts.ROLE_BRIEFS` 真身；读不到 ⇒ 空表）。

        这里读的是定位（岗位定义），不是研究数据 —— 组织图对每名秘书全开
        （用户 2026-10-06 口径），而数据面另有约束（见 :meth:`may_read_narrative`）。

        `ROLE_BRIEFS` 的值是 `agent_prompts.RoleBrief`（dataclass，不是 Mapping）；
        两种形态都收，因为"它是 dataclass"是实现细节，而秘书要的是那六个字段。
        """
        try:
            from . import agent_prompts as AP

            got = (AP.ROLE_BRIEFS or {}).get(str(role))
        except Exception:  # noqa: BLE001 - 读不到定位不该让整条委托过不去
            return {}
        return _as_mapping(got)

    def _all_briefs(self) -> dict[str, dict[str, Any]]:
        """全部角色的 brief（组织图全开；读不到就空表 —— 空表 ≠ 没有角色）。"""
        try:
            from . import agent_prompts as AP

            table = AP.ROLE_BRIEFS or {}
        except Exception:  # noqa: BLE001 - 同上
            return {}
        out: dict[str, dict[str, Any]] = {}
        for role, got in dict(table).items():
            one = _as_mapping(got)
            if one:
                out[str(role)] = one
        return out

    def _action_table(self) -> dict[str, list[str]]:
        """每个角色声明了哪些动作（`capabilities.CAPABILITIES`：`{角色: (ActionSpec,…)}`）。"""
        out: dict[str, list[str]] = {}
        try:
            from . import capabilities as C

            table = getattr(C, "CAPABILITIES", None) or {}
            for role, specs in dict(table).items():
                names = [str(getattr(s, "action", "") or "") for s in specs]
                out[str(role)] = sorted({n for n in names if n})
        except Exception:  # noqa: BLE001 - 读不到声明 ⇒ 空表（"没读到"不许读成"没有动作"）
            return {}
        return out

    def _tool_names(self) -> list[str]:
        """注册表里的真名（判"工具名写错了没有"的唯一依据）。

        ## 口径：预筛的准确度取决于装配时给它的那份注册表

        秘书只用已有声明判（注册表的真名 + `specs/<role>.py` 的参数表），
        不新增机器判据（`draft/55` §4）。所以"这份真名表全不全"直接决定预筛对不对：
        给错一份残缺的注册表，就会把真名报成"不是真名"（假阳性）。

        ## 为什么 fallback 必须带 `store`（2026-10-04 主控探针实测的缺陷）

        没有 `registry` 时的 fallback 原先是 `build_registry()` —— 不带 `store`。
        实测：`build_registry()` 出 68 件真名且 `fs.read` 不在里面；
        `build_registry(store=...)` 出 81 件、`fs.read` 在里面。
        于是任何 `registry=None` 的调用方（`for_role(..., registry=None)` 是默认）
        都会对 `fs.read` 这种真名报警
        `'fs.read' 不是注册表里的真名；并列候选：['manuscripts.read','table.create']`
        （真名被判成错名 ⇒ 预筛的第一类假阳性，而 `self.store` 就在手边）。

        三态：`store` 也没有 ⇒ 保持"造不出来就给空表"的老行为（`[]`），
        空表在调用方那一侧只能是"没读到"，不许读成"没有真名"。
        """
        if self.registry is not None:
            try:
                return sorted(str(x) for x in self.registry.names())
            except Exception:  # noqa: BLE001 - 注册表坏了不该让委托过不去
                return []
        if self.store is None:
            # 空表在这里只有一个含义：这一格没读成（不是"没有真名"）。
            # 调用方 `prescreen` 只在真名表非空时才判错名 ⇒ 空表绝不会被读成
            # "这些名字都不存在"，所以这不是把"没做"折叠成"没有"。
            return []
        try:
            from .tools import build_registry

            return sorted(str(x) for x in build_registry(store=self.store).registry.names())
        except Exception:  # noqa: BLE001 - 造不出来 ⇒ 空表（"没读到"不许读成"没有真名"）
            return []

    # ------------------------------------------------------------ 机器预筛（§6）

    def prescreen(self, *, to: str, action: str, params: Mapping[str, Any],
                  tool: str = "") -> list[str]:
        """确定性预筛：返回"报警"清单（空 = 没有报警）。

        判据全部来自已有声明（`specs/<role>.py` 的参数表 / 注册表的真名），
        这里不新造机器判据（`draft/55` §4 末：秘书不新增机器判据）。
        它是"要不要叫秘书"的输入，不是判决 —— 报警之后仍然由秘书判断。
        """
        alarms: list[str] = []
        want_role = str(to or "")
        # 职责 2 的前提是读得到收件方的定位（`draft/55` §1.2：组织图全开）。
        # 读不到 ≠ 没问题：空 brief 与"这个角色没定位"是两件事，如实报成"这一格判不了"。
        if want_role and not self._role_brief(want_role) and self._all_briefs():
            alarms.append(f"读不到 {want_role} 的角色定位 ⇒ 『收件方真做得到吗』这一格判不了"
                          "（没读成不是没问题）")
        table = self._action_table()
        if table and want_role in table and str(action) not in table.get(want_role, []):
            close = declarations_candidates(str(action), table.get(want_role, []))
            alarms.append(f"{want_role} 的动作表里没有 {action!r}"
                          + (f"；并列候选：{close}" if close else ""))
        if tool:
            names = self._tool_names()
            if names and str(tool) not in names:
                close = declarations_candidates(str(tool), names)
                alarms.append(f"{tool!r} 不是注册表里的真名"
                              + (f"；并列候选：{close}" if close else ""))
        alarms += self._required_alarms(want_role, str(action), params)
        return alarms

    def _required_alarms(self, role: str, action: str, params: Mapping[str, Any]) -> list[str]:
        """必填字段：按 `specs/<role>.py` 的参数表核。

        三态（R002 的口径）：读不到参数声明不是"没有必填参数" —— 前者是"这一格
        判不了"，所以它返回一条 alarm，而不是空列表。空列表只有一个含义：读到了
        声明、而且必填项一个不缺。
        """
        problem = ""
        try:
            from . import capabilities as C

            spec = C.find_action(role, action)
        except Exception as exc:  # noqa: BLE001 - 读不到声明 ⇒ 这一格判不了
            spec, problem = None, f"{type(exc).__name__}: {exc}"
        else:
            if spec is None:
                problem = "能力表里没有这个动作"
        if problem:
            return [f"读不到 {role}.{action} 的参数声明（{problem}）⇒ 必填这一格判不了"]
        props = dict(getattr(spec, "params", None) or {}).get("properties") or {}
        required = list(dict(getattr(spec, "params", None) or {}).get("required") or [])
        got = set(params or {})
        missing = [k for k in required if k not in got]
        if not missing:
            return []
        return [f"{role}.{action} 缺必填参数 {missing}（声明里的键：{sorted(props)}）"]

    def should_engage(self, *, alarms: Sequence[str], duplicates: int = 0,
                      overdue: int = 0, novel: bool = False) -> bool:
        """要不要叫秘书（`draft/53` §6：花销与问题量成正比，不与委托量成正比）。

        四条任一成立就叫：预筛报警 / 出现重复候选 / 闭环逾期 / 首次遇见该形态。

        它有真调用点（否则"按需介入"就是一句空话）：:meth:`optimize_outbound`、
        :meth:`assess_delegation`、:meth:`remind_closure` 三处都是先算这四个数、
        再由本方法决定要不要走 :meth:`judge`（一次模型调用）。四个数全不成立 ⇒
        确定性路径直接给结论，一次模型调用都不发。
        """
        return bool(alarms) or int(duplicates) > 0 or int(overdue) > 0 or bool(novel)

    #: 三处"判断类"（`draft/55` §2 的 B 类；用户口径"切勿全写死成机器判据"）。
    JUDGE_KINDS = ("duplicate_retry", "tool_name", "rearrange")

    def judge(self, kind: str, context: Mapping[str, Any], *, task_id: str = "") -> dict[str, Any]:
        """判断类：用本智能体自己的缝做一次模型调用，把结论落台账。

        三处判断（`draft/53` §10 的三条"改判给秘书"）：

        - `duplicate_retry`：同 key 的既有终态行算重复还是正当重试（机器只摆出来）；
        - `tool_name`：错名映到哪一个候选（或一个都不映：那是"这次不该调工具"）；
        - `rearrange`：建议重排成什么（改派权仍在 M，这里只给建议）。

        三态（`R002`/P16 的口径）：

        | 结局 | 返回 |
        |---|---|
        | 判断做了 | `{"checked": True, "decision": …, "reason": …, "basis": […]}` |
        | 没缝 / 没开 / 超时 / 坏 JSON | `{"checked": False, "reason": …}` |

        "没查成"绝不被读成"可派"：调用方（:meth:`assess_delegation`）只在
        `checked=True` 时才采信 `decision`。

        每一次真的发起过调用的结局都带 `cost`（见 :meth:`last_judge_cost`）：
        "这次判断花了哪一笔钱"必须能从台账追回账本，否则它是一笔不可归因的花销。
        """
        if kind not in self.JUDGE_KINDS:
            return {"checked": False,
                    "reason": f"不认识的判断类别 {kind!r}（认 {list(self.JUDGE_KINDS)}）",
                    "cost": {"ledger": "", "reason": "没发调用（类别不认识）"}}
        if self.seam is None:
            return {"checked": False,
                    "reason": "没有装配模型缝（本智能体自己的 llmseam）⇒ 这一格没查成",
                    "cost": {"ledger": "", "reason": "没发调用（没有缝）"}}
        if not self.enable_model:
            return {"checked": False,
                    "reason": "enable_model=False（判断类的模型调用被显式关掉）⇒ 这一格没查成",
                    "cost": {"ledger": "", "reason": "没发调用（开关关着）"}}
        t0 = time.monotonic()
        try:
            data, call = self.seam.ask_json(_judge_prompt(kind, context),
                                            task_id=task_id, note=f"secretary:{kind}")
        except Exception as exc:  # noqa: BLE001 - fail-open：超时/出错 ⇒ 没查成 + 留痕
            return self._record_judge(kind, context, {
                "checked": False, "reason": f"调用失败：{type(exc).__name__}: {exc}",
                "cost": self.last_judge_cost(kind)})
        finally:
            self._last_judge_elapsed = round(time.monotonic() - t0, 3)
        cost = self.last_judge_cost(kind)
        if not getattr(call, "ok", False) or data is None:
            return self._record_judge(kind, context, {
                "checked": False,
                "reason": f"没查成（{getattr(call, 'problem', '') or 'no_reply'}）："
                          f"{str(getattr(call, 'detail', '') or '')[:200]}",
                "cost": cost})
        decision = str(data.get("decision") or "").strip()
        if decision not in DECISIONS:
            return self._record_judge(kind, context, {
                "checked": False,
                "reason": f"模型给的结论 {decision!r} 不在词表 {list(DECISIONS)} 里 ⇒ 不采信",
                "cost": cost})
        return self._record_judge(kind, context, {
            "checked": True, "decision": decision,
            "reason": str(data.get("reason") or "")[:500],
            "basis": [str(x) for x in (data.get("basis") or [])][:5],
            "elapsed_sec": self._last_judge_elapsed, "cost": cost})

    def _record_judge(self, kind: str, context: Mapping[str, Any],
                      result: dict[str, Any]) -> dict[str, Any]:
        """把这次判断自己记一行台账（主控裁定 A5 的第 ③ 条）。

        为什么判断要独立成行（而不是只搭在 `assess_delegation` 的提案行上）：
        那份花销的归因（`cost.ledger`）与三态只在这一刻是完整的，
        而"这次判断花了哪一笔钱"必须总能从台账追回账本 —— 不论调用方是谁
        （`optimize_outbound` / `assess_delegation` / 直接调用）。
        `before` 落的是判断的输入（材料摘要），`after` 落结论：人看过程、本体看结果。
        """
        basis = list(result.get("basis") or [])
        if result.get("cost"):
            basis = basis + [f"cost.ledger={result['cost'].get('ledger') or '查不到'}"]
        self.note_decision(
            duty=2, kind=KIND_DECISION,
            decision=str(result.get("decision") or "建议重排"),
            reason=str(result.get("reason") or ""),
            basis=basis, target={"judge": kind}, judge=result,
            before=json.dumps(dict(context), ensure_ascii=False, sort_keys=True,
                              default=str)[:2000],
            fail_open=False,
        )
        return result

    def last_judge_cost(self, kind: str) -> dict[str, Any]:
        """上一次该类别判断的花销归因（主控裁定 A5 的第 ③ 条）。

        权威来源是缝自己落的那条审计事件：`llmseam._land` 把"这次的钱记进账本了吗、
        记成哪一行"写进 `llm_call` 事件的 `ledger` 字段（`usage_id` / `reason`），
        所以这里读那条事件，而不是让秘书猜自己的花销。

        三态（取不到就如实写，不许折成"花了 0"）：

        | 情形 | 返回 |
        |---|---|
        | 入账了 | `ledger = "<usage_id>"` |
        | 没入账（`no_meter` / `duplicate` / 没发请求） | `ledger = ""` + `reason` 逐字来自事件 |
        | 读不到事件 / 读不出会话 | `ledger = ""` + `reason = "查不到：…"` |

        `call_index` 是与 `usage_id` 并列的第二归因口径（缝的幂等键就用它），
        两者都给，读的人才能把"账本行"与"第几次调用"对上。
        """
        from . import sessions as SS

        want = f"secretary:{kind}"
        try:
            events, problems = SS.read_session(self.root, self.sid)
        except Exception as exc:  # noqa: BLE001 - 归因读不到就如实报
            return {"ledger": "", "reason": f"查不到：{type(exc).__name__}: {exc}"}
        calls = [e for e in events if e.get("kind") == "llm_call"]
        hit = [e for e in calls if str(e.get("note") or "") == want]
        if not hit:
            extra = f"（会话读不出：{problems[0]}）" if problems else ""
            return {"ledger": "", "reason": f"查不到：会话里没有这次判断的 llm_call 事件{extra}",
                    "call_index": len(calls)}
        ev = hit[-1]
        led = ev.get("ledger") if isinstance(ev.get("ledger"), Mapping) else {}
        out: dict[str, Any] = {
            "ledger": str((led or {}).get("usage_id") or ""),
            "charged": bool((led or {}).get("charged")),
            "ledger_reason": str((led or {}).get("reason") or ""),
            "call_index": len(calls) - 1,
            "prompt_sha256": str(ev.get("prompt_sha256") or ""),
            "tokens": int(ev.get("tokens_in") or 0) + int(ev.get("tokens_out") or 0),
            "usd": ev.get("usd"),
        }
        if not out["ledger"]:
            out["reason"] = (f"取不到 usage_id（{out['ledger_reason'] or '未知'}）"
                             "⇒ 用 call_index 归因")
        return out

    # ------------------------------------------------------------ 职责 1 / 2（发件侧）

    def _message_alarms(self, payload: Mapping[str, Any], *, admission: Any = None) -> list[str]:
        """`message`（跨智能体的结构化交互）的预筛：准入判据 + 两个必填字段。

        三态纪律：判据没接上时如实报"这一格判不了（没查成不是没问题）"，
        绝不因为拿不到判据就当它通过。

        为什么不自己判协作边：判据本体只有一份（`agent_loop.message_admission`），
        由 `AgentLoop._outbound_hook` 通过 `admission=` 注入进来。本文件里再查一次
        协作边（`agent_prompts` 那一支）就是长出了第二份实现，而两份漂了没有任何东西会红
        （判据：`tests/test_secretary.py` 里那条 AST 扫描 —— 它扫的是调用，不是措辞）。

        缺 `subject`/`body` 只报警、不替它编内容（职责 1 的既有纪律：秘书给建议，
        不改实质、不代笔）。
        """
        out: list[str] = []
        to = str(payload.get("to") or "")
        reply_to = str(payload.get("reply_to") or "")
        if admission is None:
            out.append("message 的协作边准入判据没接上 ⇒ 这一格判不了（没查成不是没问题）")
        else:
            try:
                reason = str(admission(self.role, to, reply_to) or "")
            except Exception as exc:  # noqa: BLE001 - 判据自己坏了也是"判不了"
                reason = f"message 的准入判据自己出错了（{type(exc).__name__}: {exc}）⇒ 这一格判不了"
            if reason:
                out.append(reason)
        for field in ("subject", "body"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                out.append(f"message 的 `{field}` 要是非空字符串（缺了不替它编内容）")
        return out

    def optimize_outbound(self, shape: str, payload: Mapping[str, Any], *,
                          admission: Any = None, base: str = "") -> dict[str, Any]:
        """职责 1：格式与内容优化（发件前）。

        不改变实质主张：不替本体承诺、不改结论、不加证据（`draft/53` §2 的
        "不许做"）。所以这里的产物是"建议 + 并列候选"，而不是改写后的载荷：
        本体读到的仍是它自己那一份（改不改由它决定）。

        两段分得很清（这是"切勿全写死成机器判据"的落点）：

        - 第一段是预筛（确定性）：参数表 / 必填 / 工具真名的检查，来自既有声明；
        - 第二段是判断（只有 :meth:`should_engage` 说该介入时才走）：错名映到
          哪一个候选（:meth:`judge` 的 `tool_name` 一类，一次模型调用 + 台账）。
          判断没查成 ⇒ 结论仍是预筛那一份，且台账里 `judge.checked=False` 写明。

        fail-open：超时/自己出错 ⇒ 原样放行 + 台账留痕（`fail_open=True`）。
        """
        original = dict(payload)
        t0 = time.monotonic()
        try:
            if time.monotonic() - t0 > self.deadline_sec:
                raise TimeoutError("秘书超过单次调用上限")
            # ---- S1g：洗格式（E5 的落地）。位置：判"该不该介入"之前 ——
            # 预筛要核的是洗过之后那一份（否则"错名"永远是错的，洗了白洗）。
            # 内容面一个字不动（`wash_delegation` 的边界逐条写在它的 docstring 里）。
            wash = self.wash_delegation(shape, payload)
            if wash.get("refused"):
                # 硬拒也要把预筛读数算出来：这一趟是死了，但"它另外还把工具名写错了、
                # 候选是这几个"是有用的东西（真机上模型下一步就得靠它改）。
                # 只是不判（不叫模型）：没有可发的载荷，判断没有意义。
                r_to = str(original.get("to") or original.get("role") or "")
                r_params = (original.get("params") if isinstance(original.get("params"),
                                                                 Mapping) else {})
                r_tool = str(original.get("name") or original.get("tool") or "")
                alarms = self.prescreen(to=r_to, action=str(original.get("action") or ""),
                                        params=r_params or {}, tool=r_tool)
                rec = self.note_decision(
                    duty=1, kind=KIND_OPTIMIZED, decision="洗不动 ⇒ 受控拒绝",
                    reason="；".join([str(wash.get("reason") or ""), *alarms]).strip("；"),
                    basis=["specs/<role>.py 的参数表", "tools.build_registry() 的真名"],
                    target={"to": r_to, "action": str(original.get("action") or "")},
                    before=json.dumps(original, ensure_ascii=False, sort_keys=True)[:2000],
                    changes=list(wash.get("changes") or ()), fail_open=False)
                return {"problem": "；".join([str(wash.get("reason") or ""), *alarms]).strip("；"),
                        "payload": original, "after": original, "wash": wash, "changes": [],
                        "washed": False, "refused": True, "alarms": alarms,
                        "surface": self.surface_readings(shape, original, base=base),
                        "judge": {"checked": False, "reason": "硬拒：没有可判的载荷"},
                        "engaged": False, "fail_open": False, "seq": rec.get("seq")}
            washed = dict(wash.get("payload") or original) if wash.get("checked") else original
            to = str(washed.get("to") or washed.get("role") or "")
            action = str(washed.get("action") or "")
            params = (washed.get("params") if isinstance(washed.get("params"), Mapping) else {})
            tool = str(washed.get("name") or washed.get("tool") or "")
            if shape == "message":
                # `R8`：`message` 是跨智能体的结构化交互 ⇒ 秘书接管（所有者裁定逐字
                # "如果有些形状涉及到结构化交互，则需要秘书接管"）。接管 = 预筛报警 +
                # 建议 + 台账（不替代 `_do_message` 的硬闸，也不改载荷）。
                #
                # 为什么这一支不跑上面那条委派预筛：`message` 没有 `action`/`params`/`tool`
                # 三件，而预筛会把 `to` 当角色名去查能力表 —— 对 `to=#public` 会报出两条
                # "读不到 #public 的角色定位"的假警（频道名不是角色）。它的整个预筛面
                # 就是下面这两格：共用准入判据 + 两个必填字段。
                alarms = self._message_alarms(payload, admission=admission)
            else:
                alarms = self.prescreen(to=to, action=action, params=params or {}, tool=tool)
            # 预筛报警不是"判决"：它只说"照声明看不合规"，改法（映到哪个名字、
            # 补哪个字段）是判断 ⇒ 只有该介入时才叫模型。
            judged: dict[str, Any] = {"checked": False, "reason": "预筛没有报警 ⇒ 不必判断"}
            engage = self.should_engage(alarms=alarms, duplicates=0, overdue=0, novel=bool(tool))
            if engage and tool and any("真名" in a for a in alarms):
                judged = self.judge("tool_name", {"tool": tool, "to": to,
                                                  "candidates": declarations_candidates(
                                                      tool, self._tool_names())})
            decision = ("已优化" if not alarms else "建议重排")
            if judged.get("checked"):
                decision = str(judged.get("decision") or decision)
            changes = list(wash.get("changes") or ())
            rec = self.note_decision(
                duty=1, kind=KIND_OPTIMIZED, decision=decision,
                reason="；".join(alarms) or "没有触发预筛报警（原样放行）",
                basis=["specs/<role>.py 的参数表", "tools.build_registry() 的真名"],
                target={"to": to, "action": action}, judge=judged,
                before=json.dumps(original, ensure_ascii=False, sort_keys=True)[:2000],
                # S1g：洗过的那一份与原稿并列落账（`before`/`after` + 逐格 `changes`）。
                # 只有一份摆在那里时，"模型说错了"与"秘书替它补对了"在纸上分不开。
                after=json.dumps(washed, ensure_ascii=False, sort_keys=True)[:2000],
                changes=changes,
                fail_open=False,
            )
            return {"problem": "；".join(alarms), "payload": original, "after": washed,
                    "wash": wash, "changes": changes,
                    "washed": bool(wash.get("washed")), "refused": False,
                    "alarms": alarms, "judge": judged, "engaged": bool(engage),
                    "surface": self.surface_readings(shape, washed, base=base),
                    "fail_open": False, "seq": rec.get("seq")}
        except Exception as exc:  # noqa: BLE001 - fail-open：超时/出错一律放行
            self.note_decision(duty=1, kind=KIND_OPTIMIZED, decision="已优化",
                               reason="秘书没跑成 ⇒ 原样放行", fail_open=True,
                               error=f"{type(exc).__name__}: {exc}",
                               before=json.dumps(original, ensure_ascii=False, sort_keys=True)[:2000])
            self._log(f"秘书优化没跑成（原样放行）：{type(exc).__name__}: {exc}")
            return {"problem": f"{type(exc).__name__}: {exc}", "payload": original,
                    "after": original, "wash": {"checked": False, "washed": False,
                                                "refused": "", "changes": [],
                                                "reason": f"没跑成：{type(exc).__name__}"},
                    "changes": [], "washed": False, "refused": False,
                    "alarms": [], "fail_open": True,
                    "surface": {"checked": False, "fits": None,
                                "reason": "秘书没跑成 ⇒ 面这一维没查成（不是通过）"}}

    # ------------------------------------------------------------ 洗格式（S1g）

    #: 洗格式只管派活这两个形状（`draft/90` §1.2 的格式面）：
    #: `handoff` / `message` 的 `to` 是内容面（"派给谁"一个字不许动）⇒ 只报不改。
    WASH_SHAPES: tuple[str, ...] = ("summon", "summon_many")

    #: 形状自己的键（不是 `params` 的键）：顶层折叠时要跳过它们，
    #: 否则一个恰好叫 `name` 的动作参数会把名册那一格（S1k）偷走。
    _SHAPE_KEYS: tuple[str, ...] = ("role", "action", "params", "brief", "name", "reuse",
                                    "input_key", "instance", "targets", "notify", "why")

    def wash_delegation(self, shape: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """洗一遍格式面（S1g / E5），内容面一个字不动。

        返回（三态必须分得开，这是本仓最忌折平的一处）：

        | 结局 | 返回 |
        |---|---|
        | 洗过了、本来就是受控形状 | `{"checked": True, "washed": False, "changes": []}` |
        | 洗过了、改了格式格 | `{"checked": True, "washed": True, "changes": [...]}` |
        | 这一格没洗成 | `{"checked": False, "reason": …}`（原样发出去，闸门照旧） |
        | 硬拒 | `{"checked": True, "refused": "<受控理由码>"}`（调用方一行都不落） |

        ## 可以洗什么（`draft/90` §1.2，逐条）

        - 动作真名：`action` 不在该角色的动作表里、而 `declarations_candidates`
          只给出唯一候选 ⇒ 映过去（候选有多条 ⇒ 不猜，留给闸门拒）；
        - `params` 键名：声明里没有这个键、而候选唯一 ⇒ 改名（值原样跟着走）；
        - 顶层折叠：动作声明的参数被摆在了顶层（不在 `params` 里）⇒ 收进 `params`
          （这是真机上"出现未声明的参数"那一类的最常见成因）；
        - `input_key` 归一：去空白 + 内部空白并成一个空格（它是环检测键，不挪作他用）；
        - `name` / `reuse` / `instance` / `role` / `action`：去首尾空白。

        ## 一个字不许动什么（内容面）

        `params` 里任何值、`role`（派给谁）、`notify` 的正文与主张、证据与结论。
        所以这里只搬键、只去空白，从不把 `None`/缺键补成默认值。

        ## 硬拒只有一格（为什么这么窄）

        "洗不动 ⇒ 受控拒绝，一行都不落"（`draft/90` §1.2 步骤 1）落在
        `summon` 连"派给谁/做什么"都不全这一格：没有角色或没有动作时，
        一次派活在语义上不成立，洗也洗不出内容来。
        其余"洗不动"（缺必填参数、参数值不对）照旧交给 `conductor` 的闸门去拒 ——
        那一档今天会落一行 `refused` 并且可能转成"请主控代唤"（`_needs_relay`），
        秘书抢在它前面拒掉会把那条出路和那行证据一起弄丢。
        `summon_many` 不用硬拒：一批是 N 次派活，整批拒掉会把好的那几项一起带走
        （逐项 `refused` 行仍由闸门落）。

        为什么 `params` 只动顶层一层、且不深拷：噪声载荷里有自引用字典
        （`SELF_REF`）与 60 层深嵌套（`test_secretary_noise.py`），递归走一遍会当场炸掉
        这一次派活。只搬顶层键、只去字符串空白，永远碰不到那些结构。
        """
        before = dict(payload or {})
        out: dict[str, Any] = {"checked": False, "washed": False, "refused": "",
                               "reason": "", "payload": before, "before": before,
                               "changes": []}
        if shape not in self.WASH_SHAPES:
            out["reason"] = (f"{shape} 不在洗格式的面上（派活以外只报不改："
                             "`to` 是内容面）")
            return out
        try:
            if shape == "summon_many":
                return self._wash_summon_many(before, out)
            return self._wash_one(before, out, field="")
        except Exception as exc:  # noqa: BLE001 —— 洗不动不许打断这一次派活
            out.update(checked=False, washed=False, refused="", payload=before,
                       reason=f"洗格式没跑成（{type(exc).__name__}: {exc}）⇒ 原样发出去")
            return out

    def _wash_one(self, payload: dict[str, Any], out: dict[str, Any],
                  *, field: str, refuse: bool = True) -> dict[str, Any]:
        """洗一次派活的格式面（`field` 给了就把这一份摆在那个字段名下，用于批量）。"""
        where = f"{field}：" if field else ""
        after = dict(payload)
        changes: list[dict[str, Any]] = list(out.get("changes") or [])
        for key in ("role", "action", "name", "reuse", "instance"):
            got = after.get(key)
            if isinstance(got, str):
                stripped = got.strip()
                if stripped != got:
                    after[key] = stripped
                    changes.append({"where": field, "field": key, "why": "去首尾空白"})
        key_val = after.get("input_key")
        if isinstance(key_val, str):
            folded = " ".join(key_val.split())
            if folded != key_val:
                after["input_key"] = folded
                changes.append({"where": field, "field": "input_key", "why": "归一（空白并一个）"})
        # 角色那一格有两个写法（`role` 是派活形状的、`to` 是老调用方的）：
        # `optimize_outbound` 与 `prescreen` 都认两个 ⇒ 这里也认两个，
        # 否则一个用 `to=` 的调用方会被判成"没给角色"（真机判据当场抓出来的）。
        role = after.get("role")
        if not (isinstance(role, str) and role.strip()):
            role = after.get("to") if isinstance(after.get("to"), str) else ""
        else:
            role = role.strip()
        action = after.get("action") if isinstance(after.get("action"), str) else ""
        if not role or not action:
            missing = "角色（派给谁）" if not role else "动作（做什么）"
            # 理由码与闸门那一侧同名（`schema.REFUSAL_REASONS`）：空动作名字在
            # 闸门那里就是 `unknown_action`（红前读数见 S1g 的提交信息），这一档只是
            # "不落行"、码不改 —— 换一个码会让读了半年日志的人以为另出了一类拒绝。
            code = "unknown_role" if not role else "unknown_action"
            if refuse:
                out.update(payload=payload, changes=changes, checked=True, washed=False,
                           refused=code,
                           reason=f"{where}没给{missing} ⇒ 一次派活在语义上不成立（不落行）")
                return out
            out.update(payload=after, changes=changes, checked=True,
                       washed=bool(changes), reason=f"{where}没给{missing} ⇒ 这一项洗不了")
            return out
        spec = self._action_spec(role, action)
        table = self._action_table().get(role, [])
        note = ""
        if spec is None:
            close = declarations_candidates(action, table) if table else []
            if len(close) == 1:
                after["action"] = close[0]
                changes.append({"where": field, "field": "action",
                                "from": action, "to": close[0], "why": "动作真名（唯一候选）"})
                action = close[0]
                spec = self._action_spec(role, action)
            elif table:
                note = (f"{where}动作表里没有 {action!r}"
                        + (f"；并列候选 {close} ⇒ 不猜（留给闸门拒）" if close
                           else "（没有候选 ⇒ 不猜，留给闸门拒）"))
        # ---- `params` 键名归一 + 顶层折叠 —— 一次做完，因为它们是同一件事的两半：
        # 值在哪一格不重要，重要的是它得落在声明的那个键下面。
        props = self._param_props(spec)
        raw_params = after.get("params")
        if props and (raw_params is None or isinstance(raw_params, Mapping)):
            fixed = dict(raw_params or {})
            for key in list(fixed):
                if key in props:
                    continue
                cand = declarations_candidates(str(key), props)
                if len(cand) == 1 and cand[0] not in fixed:
                    # 目标键已经在 `params` 里 ⇒ 不改（改名会覆盖一个真值：
                    # 那是动内容面，不是洗格式）。
                    fixed[cand[0]] = fixed.pop(key)
                    changes.append({"where": field, "field": f"params.{key}",
                                    "to": f"params.{cand[0]}", "why": "键名归一（唯一候选）"})
            for key in list(after):
                if key in fixed or key in self._SHAPE_KEYS or key == "params":
                    continue
                if key in props:
                    fixed[key] = after.pop(key)
                    changes.append({"where": field, "field": f"<顶层>.{key}",
                                    "to": f"params.{key}", "why": "顶层折叠"})
                    continue
                # 顶层的错名键：候选唯一 ⇒ 改名并收进 `params`（与 `params` 里
                # 那一支同一条口径）；候选不唯一 ⇒ 一个字节都不动，留在顶层
                # （它照样落在步骤记录里，"没洗"看得见）。
                cand = declarations_candidates(str(key), props)
                if len(cand) == 1 and cand[0] not in fixed:
                    fixed[cand[0]] = after.pop(key)
                    changes.append({"where": field, "field": f"<顶层>.{key}",
                                    "from": str(key), "to": f"params.{cand[0]}",
                                    "why": "顶层折算：键名归一（唯一候选）"})
            if fixed or raw_params is not None:
                if fixed != dict(raw_params or {}):
                    after["params"] = fixed
        elif raw_params is not None and not isinstance(raw_params, Mapping):
            note = note or f"{where}params 不是键值对 ⇒ 这一格没洗（原样发出去）"
        # 三态：读到了声明（表非空）就是"查过了"；表读不到才是"这一格没读成"。
        checked = bool(spec or table)
        out.update(payload=after, changes=changes, checked=checked,
                   washed=bool(changes), refused="",
                   reason=note if not changes else "")
        return out

    def _wash_summon_many(self, payload: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
        """批量：逐项洗，不整批硬拒（一批是 N 次派活）。"""
        targets = payload.get("targets")
        after = dict(payload)
        changes: list[dict[str, Any]] = []
        bad: list[str] = []
        if not isinstance(targets, (list, tuple)):
            out.update(reason="targets 不是数组 ⇒ 这一格没洗（原样发出去）", payload=payload)
            return out
        washed: list[Any] = []
        for i, item in enumerate(targets):
            if not isinstance(item, Mapping):
                washed.append(item)
                bad.append(f"targets[{i}] 不是键值对")
                continue
            sub: dict[str, Any] = {"changes": [], "washed": False}
            got = self._wash_one(dict(item), sub, field=f"targets[{i}]", refuse=False)
            if got.get("reason") and not got.get("washed"):
                bad.append(str(got["reason"]))
            changes.extend(list(got.get("changes") or []))
            washed.append(dict(got.get("payload") or {}))
        after["targets"] = washed
        out.update(payload=after, changes=changes, checked=True, washed=bool(changes),
                   refused="",
                   reason="；".join(bad[:3]) if bad else "")
        return out

    def _action_spec(self, role: str, action: str) -> Any:
        """该角色该动作的声明（读不到 ⇒ `None`，调用方按"这一格没洗成"处理）。"""
        try:
            from . import capabilities as C

            return C.find_action(role, action)
        except Exception:  # noqa: BLE001 —— 声明读不到不是"没有这个动作"
            return None

    def _param_props(self, spec: Any) -> list[str]:
        """该动作声明的参数键名（空列表 = 这一格判不了，绝不读成"没有参数"）。"""
        try:
            props = dict(getattr(spec, "params", None) or {}).get("properties") or {}
        except Exception:  # noqa: BLE001
            return []
        return [str(k) for k in props]

    def assess_delegation(self, *, to: str, action: str, params: Mapping[str, Any],
                          input_key: str = "", duplicates: Sequence[Mapping[str, Any]] = (),
                          novel: bool = False, reuse: str = "", base: str = "") -> dict[str, Any]:
        """职责 2：委派评估（"收件方真做得到吗、该不该派"）。

        结论 ∈ :data:`DECISIONS` 的四档（`draft/55` §2 的 B 类）+ 理由 + 依据。
        不擅自改派（改派权在 M）：它只给建议，本体可拒绝并写明理由。

        同 key 的既有终态行是最重要的一条输入（`draft/53` §10：派活去重归发件方
        秘书，"该不该派"含"是不是重复"）—— 机器只把那些行摆出来，判"算重复
        还是正当重试"由秘书做。

        不止"任务是否符合角色设计"（业主 2026-10-09）：`surface` 那一格是
        "这件活在被派人的读写面里做不做得成"（`draft/90` §1.11）。`reuse` 给了
        一个名册名（复用已有子代理）时它的面是已知的 ⇒ 判得最准；新起一个时槽位
        还没分，但"越界"与"父视角有、面内没有"两档仍判得出来。`fits=False` 时
        它进 `reason`（当成一条"该不该派"的理由），但不拦（处置权在父）。
        """
        dups = [dict(r) for r in duplicates]
        alarms = self.prescreen(to=to, action=action, params=params)
        mismatch = [a for a in alarms if "动作表里没有" in a or "缺必填参数" in a]
        face = self._face_of_name(owner=str(self.task_id or ""), name=reuse) if reuse else ""
        surface = self.surface_readings("summon", {"action": action, "params": dict(params or {})},
                                        face=face, base=base)
        face_bad = surface.get("fits") is False
        if dups and not mismatch:
            decision, reason = "建议重排", (f"同 (role={to}, action={action}, "
                                          f"input_key={input_key}) 已有 {len(dups)} 条终态行"
                                          "（先看一眼是不是同一件事的重试）")
        elif mismatch:
            decision, reason = "建议重排", "；".join(mismatch)
        elif not self._can_take(to, action):
            decision, reason = "建议改派", (f"{to} 的能力面里没有 {action}"
                                          "（改派权在 M：这只是建议）")
        elif face_bad:
            # 面这一维与"能力面"是两回事：能力面说"这个动作你能做"，面说"那块盘
            # 不在你手里"—— 后者今天没有任何别的地方能在派活那一刻看出来。
            decision, reason = "建议改派", (f"{to} 这趟的面里做不成这一件："
                                          f"{surface.get('reason')}"
                                          "（要它做，就把它要用的那一块切进它的面，"
                                          "或者把这一件记成『职责之外』那一档）")
        else:
            decision, reason = "可派", "没有发现重复候选，能力面与参数都对得上"
        basis = ["specs/<role>.py 的动作表", "tasks: 同 key 的既有终态行"]
        if surface.get("checked"):
            basis.append("out/surfaces/<父>/<槽位>：这件活点名的路径在不在里面")
        # ---- 判断类：只有该介入时才叫模型（"切勿全写死成机器判据"的落点）。
        # 两条判断分开问，因为它们是两个问题：同 key 那些行算不算重复（`duplicate_retry`）、
        # 以及该把这条委托重排成什么（`rearrange`）。
        judged: dict[str, Any] = {"checked": False, "reason": "预筛没有报警、也没有重复候选 ⇒ 不必判断"}
        engaged = self.should_engage(alarms=alarms, duplicates=len(dups), overdue=0,
                                    novel=bool(novel))
        if engaged:
            kind = "duplicate_retry" if dups else "rearrange"
            judged = self.judge(kind, {"to": to, "action": action, "params": dict(params or {}),
                                       "input_key": input_key, "duplicates": dups[:5],
                                       "alarms": alarms,
                                       "preliminary": decision})
            if judged.get("checked"):
                # 模型的结论覆盖"预筛给的初步结论"，但它只能给建议（改派权在 M），
                # 而且只在 `checked=True` 时才被采信 —— "没查成"不冒充"可派"。
                decision = str(judged.get("decision") or decision)
                if judged.get("reason"):
                    reason = f"{reason}；判断：{judged['reason']}"
                basis = list(basis) + list(judged.get("basis") or [])
        rec = self.note_decision(
            duty=2, kind=KIND_PROPOSAL, decision=decision, reason=reason, basis=basis,
            target={"to": to, "action": action, "input_key": input_key},
            judge=judged, fail_open=False,
        )
        return {"decision": decision, "reason": reason, "basis": basis,
                "duplicates": dups, "alarms": alarms, "novel": bool(novel),
                "surface": surface,
                "judge": judged, "engaged": bool(engaged), "seq": rec.get("seq")}

    def _can_take(self, role: str, action: str) -> bool:
        """`role` 的动作表里有没有 `action`（读不到声明 ⇒ 判"能"：不冤枉）。"""
        table = self._action_table()
        if not table or str(role) not in table:
            return True
        return str(action) in table[str(role)]

    # ------------------------------------------------------------ 职责 4 / 3（收件侧）

    def rework_inbound(self, item: Mapping[str, Any]) -> dict[str, Any]:
        """职责 4：按本角色定位把收到的委托加工成贴切版本。

        不加码不减码（`draft/53` §2 的"不许做"）：只改"怎么说"，不改"要什么"。
        所以产物是"补上下文 + 明确产出物与验收口径"的补充段，原文一字不动
        （并列留痕：`draft/55` §5.1 第 3 条）。
        """
        original = dict(item)
        try:
            brief = self._role_brief(self.role)
            tail = []
            deliverable = str(brief.get("deliverable") or "").strip()
            if deliverable:
                tail.append(f"我的产出物口径：{deliverable}")
            duty = str(brief.get("duty") or "").strip()
            if duty:
                tail.append(f"我在本条线上的位置：{duty}")
            note = "\n".join(tail)
            problem = ""
            if not tail:
                problem = ("读不到本角色的 `deliverable`/`duty` ⇒ 这一格判不了"
                           "（没读成不是没问题）")
            self.note_decision(duty=4, kind=KIND_OPTIMIZED, decision="已优化",
                               reason=problem or "按本角色定位补上下文（不加码不减码）",
                               basis=["agent_prompts.ROLE_BRIEFS"],
                               before=json.dumps(original, ensure_ascii=False, sort_keys=True)[:2000],
                               after=note[:2000])
            return {"item": original, "addendum": note, "problem": problem, "fail_open": False}
        except Exception as exc:  # noqa: BLE001 - fail-open
            self.note_decision(duty=4, kind=KIND_OPTIMIZED, fail_open=True,
                               error=f"{type(exc).__name__}: {exc}",
                               reason="秘书没跑成 ⇒ 原样交给本体")
            return {"item": original, "addendum": "", "problem": f"{type(exc).__name__}: {exc}",
                    "fail_open": True}

    def inbox_todos(self, *, limit: int = 20) -> dict[str, Any]:
        """F-05 的消费端：把"还没有处理 / 还没有反馈"的委托摆出来（只读）。

        `draft/53` §10 的口径：F-05 待办/待核队列的生产端是机器
        （`search_requests` / `reprocess_requests` 的 pending，以及降级/待核那些三态行），
        消费端是各角色自己的秘书（自己的收件箱）+ M 的秘书（全局）。
        本方法只做"摆出来"这一半，判断归 :meth:`remind_closure`。

        三态（R002 的口径）：`checked=False` + `reason` 表示"这一格没读成"
        （没有 store / 表读不出来），与 `todos=[]`（读成了、确实没有待办）分开报。

        返回值：`{"checked", "reason", "todos": [...], "count", "by_kind"}`，
        每条 `todo` 是 `{"kind", "id", "who", "state", "since"}` —— `state` 说的是
        "为什么它算待办"（`pending` 没做完 / `unclaimed` 没人接 / `running` 没有终态）。
        """
        if self.store is None:
            return {"checked": False, "reason": "没有 store ⇒ 收件箱这一格没读成",
                    "todos": [], "count": 0, "by_kind": {}}
        todos: list[dict[str, Any]] = []
        problems: list[str] = []
        for table, kind in (("search_requests", "search_request"),
                            ("reprocess_requests", "reprocess_request")):
            try:
                rows = self.store.rows(table)
            except Exception as exc:  # noqa: BLE001 - 读不出来如实报，不折成"没有待办"
                problems.append(f"{table}: {type(exc).__name__}: {exc}")
                continue
            for row in rows:
                if row.get("done"):
                    continue
                who = str(row.get("claimed_by") or "")
                todos.append({
                    "kind": kind,
                    "id": str(row.get("request_id") or ""),
                    "who": who or S.CONDUCTOR_ROLE,
                    "state": "pending" if who else "unclaimed",
                    "since": str(row.get("timestamp") or ""),
                    "attempts": int(row.get("attempts") or 0),
                })
        excluded_top = 0
        try:
            for row in self.store.rows("tasks"):
                if str(row.get("status") or "") not in ("pending", "running"):
                    continue
                # 顶趟行（`action="run"`，F1 加的）不算待办：它是"用户发起的那一趟
                # 正在跑"，不是"有人提交了却没人接手"——后者才是这份收件箱要摆出来的东西。
                # 排除了几行要留在读数里（`excluded_top_level`），否则"少了几行"会被读成
                # "本来就没有"（静默漂移的另一种形态）。
                if str(row.get("action") or "") == "run":
                    excluded_top += 1
                    continue
                todos.append({"kind": "task", "id": str(row.get("task_id") or ""),
                              "who": str(row.get("role") or ""), "state": "running",
                              "since": str(row.get("started_at") or "")})
        except Exception as exc:  # noqa: BLE001 - 同上
            problems.append(f"tasks: {type(exc).__name__}: {exc}")
        todos = todos[:max(1, int(limit))]
        by_kind: dict[str, int] = {}
        for t in todos:
            by_kind[t["kind"]] = by_kind.get(t["kind"], 0) + 1
        return {"checked": not problems, "reason": "；".join(problems),
                "excluded_top_level": excluded_top,
                "todos": todos, "count": len(todos), "by_kind": by_kind}

    #: `pending_inbox` 认的既有标记（不许新造字段/词表/工具）。
    PENDING_KINDS = ("missing_bit", "missing_proof", "unverified_quote")

    def pending_inbox(self, *, scope: str = "self", window_sec: int = 86400,
                      limit: int = 50) -> dict[str, Any]:
        """F-05 的消费端：待办/待核队列（只读扫表；落进决定台账）。

        `draft/53:181` 逐字："消费端 = 各角色秘书（自己的收件箱）+
        M 的秘书（全局）" ⇒ 这就是那两个口径：

        | `scope` | 看什么 |
        |---|---|
        | `"self"` | 与本角色有关的那些行（按接手方过滤） |
        | `"global"` | 全部（M 的秘书的全局视图） |

        条目只来自既有标记（不新增表/字段/工具/`status` 取值，主控裁定）：

        1. `missing_bit`：`statements` 行的 `bits` 里那一位没有值（等级由
           `evidencebits.derive_grade` 现算，所以缺位 = 等级会降，不是"没有等级"）；
        2. `missing_proof`：`origin="own_result"` 而 `proof_text` 空
           （自产命题没有证明 ⇒ 现算等级是"猜想"而不是证明级）；
        3. `unverified_quote`：`quote_verified is None` 且这一行已经过了窗口
           （够久了还"没核"= 待核；`quote_reason` 是它自己写的"为什么还没核"）。

        每条给出 `(表, 行 id, 缺什么, 谁该接手)`：接手方从声明派生
        （`capabilities.WRITE_SETS` 里谁能写这张表 / `evidencebits.BIT_OWNERS`），
        不另造一张路由表。

        三态（R002 口径）：`checked=False` + `reason` = 这一格没读成（表读不出来），
        与"读成了、确实没有待办"（`items=[]`）分开报。有内容时逐条落
        :meth:`note_decision` —— 只记录，不写任何库表。
        """
        if str(scope) not in ("self", "global"):
            return {"checked": False, "reason": f"scope 只能是 'self' / 'global'，收到 {scope!r}",
                    "items": [], "count": 0, "by_kind": {}}
        if self.store is None:
            return {"checked": False, "reason": "没有 store ⇒ 收件箱这一格没读成",
                    "items": [], "count": 0, "by_kind": {}}
        try:
            from . import evidencebits as EB

            bit_names = tuple(EB.BIT_NAMES)
            bit_owners = dict(EB.BIT_OWNERS or {})
            #: 位的已定取值（`evidencebits.BIT_STATES`）：`na` / `failed` / `verified`
            #: 都是"这一位问过了、有结论" ⇒ 不是待办；只有 `pending`（以及没写）才待办。
            #: 这一格如果不看状态而只看"有没有值"，`na`（不适用）会被误报成待办。
            resolved = tuple(s for s in tuple(EB.BIT_STATES) if s != "pending")
        except Exception:  # noqa: BLE001 - 位表读不到 ⇒ 那一条判据不做（不许猜位的含义）
            bit_names, bit_owners, resolved = (), {}, ()
        try:
            from . import capabilities as C

            writers: dict[str, list[str]] = {}
            for role, tables in dict(C.WRITE_SETS or {}).items():
                for table in tables:
                    writers.setdefault(str(table), []).append(str(role))
        except Exception:  # noqa: BLE001 - 同上：不知道谁接手就如实写空串
            writers = {}

        def _who(table: str, bit: str = "") -> str:
            if bit and bit_owners.get(bit):
                return str(bit_owners[bit])
            cands = sorted(writers.get(table) or [])
            return cands[0] if cands else ""

        try:
            rows = self.store.rows("statements")
        except Exception as exc:  # noqa: BLE001 - 读不出来如实报，不折成"没有待办"
            return {"checked": False,
                    "reason": f"statements 读不出来：{type(exc).__name__}: {exc}",
                    "items": [], "count": 0, "by_kind": {}}
        now = _now_iso()
        items: list[dict[str, Any]] = []
        for row in rows:
            sid = str(row.get("stmt_id") or "")
            bits = row.get("bits") if isinstance(row.get("bits"), Mapping) else {}
            for bit in bit_names:
                state = (bits or {}).get(bit)
                if isinstance(state, Mapping):
                    state = state.get("state", state.get("value"))
                if str(state or "") in resolved:
                    continue
                who = _who("statements", bit)
                if scope == "self" and who and who != self.role:
                    continue
                items.append({"kind": "missing_bit", "table": "statements", "id": sid,
                              "missing": bit, "who": who, "state": "pending",
                              "since": str(row.get("created_at") or ""),
                              "why": f"证据位 {bit!r} 没有值 ⇒ 等级现算会降（`derive_grade`）"})
            if str(row.get("origin") or "") == "own_result" \
                    and not str(row.get("proof_text") or "").strip():
                who = _who("statements")
                if not (scope == "self" and who and who != self.role):
                    items.append({"kind": "missing_proof", "table": "statements", "id": sid,
                                  "missing": "proof_text", "who": who, "state": "pending",
                                  "since": str(row.get("created_at") or ""),
                                  "why": "自产命题没有证明 ⇒ 现算等级是『猜想』而不是证明级",
                                  "quote_reason": str(row.get("quote_reason") or "")})
            if row.get("quote_verified") is None and _older_than(row.get("created_at"), now,
                                                                int(window_sec)):
                who = _who("statements")
                if not (scope == "self" and who and who != self.role):
                    items.append({"kind": "unverified_quote", "table": "statements", "id": sid,
                                  "missing": "quote_verified", "who": who, "state": "pending",
                                  "since": str(row.get("created_at") or ""),
                                  "why": "过了窗口还没核（`quote_verified is None`）⇒ 待核",
                                  "quote_reason": str(row.get("quote_reason") or "")})
        items = items[:max(1, int(limit))]
        by_kind: dict[str, int] = {}
        for it in items:
            by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
        if items:
            # 职责 3 的闭环提醒就从这里取活：只记录，不改任何库表。
            self.note_decision(
                duty=3, kind=KIND_NOTICE, decision="已提醒",
                reason=f"F-05 待办 {len(items)} 条（scope={scope}，分档 {by_kind}）",
                basis=["statements.bits / proof_text / quote_verified（只读扫表）",
                       "capabilities.WRITE_SETS 派生接手方"],
                target={"scope": str(scope), "items": items[:10]}, fail_open=False)
        return {"checked": True, "scope": str(scope), "items": items,
                "count": len(items), "by_kind": by_kind}

    def remind_closure(self, items: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
        """职责 3：闭环提醒（收件方盯自己的收件箱；经 M）。

        判据只有"有没有处理、有没有反馈"两条事实（`draft/53` §2 的"不许做"：
        不替本体做事、不伪造反馈）。异步、不阻塞本体；
        一次最多 :data:`MAX_REMINDERS` 条（默认 5，避免刷屏）。

        `items=None` ⇒ 自己读待办（:meth:`inbox_todos`，F-05 的消费端）；
        给了就按给的那一份判 —— "谁盯哪个收件箱"由调用方决定（M 的秘书看全局）。
        """
        if items is None:
            got = self.inbox_todos()
            items = list(got["todos"])
            if not got["checked"]:
                # 读不成不是"没有待办"：如实留痕，绝不当成清零。
                self.note_decision(duty=3, kind=KIND_NOTICE, decision="已提醒",
                                   reason=f"待办那一格没读成：{got['reason']}",
                                   basis=["tasks / search_requests / reprocess_requests"],
                                   target={"role": self.role}, fail_open=True,
                                   error=str(got["reason"]))
                return []
        out: list[dict[str, Any]] = []
        for it in list(items)[:MAX_REMINDERS]:
            task_id = str(it.get("task_id") or it.get("id") or "")
            state = str(it.get("state") or "")
            if state in ("handled", "feedback_seen", "closed"):
                continue
            if not state:
                state = "unknown"
            out.append({"task_id": task_id, "state": state,
                        "kind": str(it.get("kind") or ""),
                        "to": str(it.get("by") or it.get("who") or S.CONDUCTOR_ROLE),
                        "note": "这一条委托没有终态 / 没有反馈 ⇒ 提醒本体（经 M）"})
        if out:
            self.note_decision(duty=3, kind=KIND_NOTICE, decision="已提醒",
                               reason=f"{len(out)} 条未闭环（留痕 ≠ 被处理）",
                               basis=["tasks: 无终态行 / sessions: 无 task_end"],
                               target={"role": self.role}, fail_open=False)
            # 逐条落台账（2026-10-04 主控裁定的第 1 条："每条进决定台账"）：
            # 只落一行摘要的话，"提醒了谁、什么事、什么状态"在纸上查不到 ——
            # 而这一层唯一能自证的就是台账（`draft/55` §5.3）。
            for one in out:
                self.note_decision(
                    duty=3, kind=KIND_NOTICE, decision="已提醒",
                    reason=f"未闭环：{one['state']}（{one['task_id'] or '无 id'}）",
                    basis=["tasks: 无终态行 / sessions: 无 task_end"],
                    target={"task_id": one["task_id"], "state": one["state"],
                            "kind": one["kind"], "to": one["to"]},
                    fail_open=False)
            # 闭环提醒是异步的（`draft/55` §5.2）：不阻塞本体，所以这一格只记
            # "该不该叫秘书"的读数（要不要真叫由调用方按 `should_engage` 走）。
        self._last_closure_engage = self.should_engage(alarms=[], duplicates=0,
                                                      overdue=len(out), novel=False)
        return out

    def negotiate(self, *, with_role: str, point: str,
                  rounds: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
        """秘书 ⇄ 秘书协商（`draft/53` §3）：最多 2 轮，之后上报本体、再上报 M。

        本方法只记录协商这件事本身（轮次 + 结论）：真正的来回由两侧真身驱动，
        而"协商结论必须抄送本体"是硬要求（`draft/55` §5.1 第 2 条）——
        否则"任务是变过形的"这件事对本体不可见。
        """
        done = [dict(x) for x in rounds]
        if len(done) >= MAX_NEGOTIATION_ROUNDS:
            outcome, escalate = "上报本体", True
        else:
            outcome, escalate = "待回应", False
        rec = {"round": len(done) + 1, "with": f"secretary/{with_role}",
               "point": str(point), "outcome": outcome, "escalate_to_body": escalate}
        self._negotiations.append(rec)
        self.note_decision(duty=2, kind=KIND_NEGOTIATION, decision="建议重排",
                           reason=f"与 secretary/{with_role} 协商：{point}",
                           basis=["draft/53 §3"], negotiation=done + [rec],
                           target={"with": f"secretary/{with_role}"}, fail_open=False)
        return rec

    # ------------------------------------------------------------ 手稿通道（增 / 改 / 查）

    def handoff_add(self, *, to: str, summary: str, body: str, refs: Iterable[str] = (),
                    task_id: str = "", sid: str = "", note: str = "") -> dict[str, Any]:
        """增：替本体执笔一行交接手稿（`manuscripts.write`）。

        这一格不许 fail-open：写失败必须报错留痕（`draft/55` §5.2）。
        静默放行的后果是"手稿缺行"，而缺行与"没交接"在账本上长得一样 ——
        那会让下一次"这条是不是已经交接过"判错。所以这里 `raise` 之后再留痕。
        """
        try:
            rec = MS.write(self.root, sender=self.role, recipient=str(to).upper(),
                           summary=str(summary), body=str(body), refs=list(refs),
                           task_id=str(task_id), sid=str(sid), note=str(note))
        except Exception as exc:
            self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                               reason="手稿执笔失败（这一格不许静默放行）",
                               basis=["draft/55 §5.2"], mid="", fail_open=False,
                               error=f"{type(exc).__name__}: {exc}",
                               target={"to": str(to)})
            raise
        self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                           reason="替本体执笔一行交接手稿（sender 仍是被服务的角色）",
                           basis=["draft/55 §4 归属与审计"], mid=str(rec.get("id") or ""),
                           target={"to": str(to)}, fail_open=False)
        return rec

    def handoff_revise(self, *, mid: str, summary: str = "", body: str = "",
                       task_id: str = "", reason: str = "", note: str = "") -> dict[str, Any]:
        """改：追加一条修订行（`manuscripts.revise`，旧行保留）。

        与 :meth:`handoff_add` 同一条纪律：写失败必须报错留痕。
        `task_id`（2026-10-08 晚补）：一实例一秘书之后，每一行都要能对回实例 ——
        真机读数（`draft/89` §3）是 1562 行里 593 行没有这一格，而它们正是走
        `agent_loop._do_handoff` 那条路的（形参本来就在 `handoff_add` / `manuscripts.revise`
        上，缺的是调用点不传）。
        """
        try:
            rec = MS.revise(self.root, mid=str(mid), summary=str(summary), body=str(body),
                            task_id=str(task_id),
                            reason=str(reason), note=str(note))
        except Exception as exc:
            self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                               reason="手稿订正失败（这一格不许静默放行）",
                               basis=["draft/55 §5.2"], mid=str(mid), fail_open=False,
                               error=f"{type(exc).__name__}: {exc}")
            raise
        self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                           reason=f"追加修订行（订正 {mid}，旧行保留）",
                           basis=["draft/53 §2.1 改", "draft/55 §3.1"],
                           mid=str(rec.get("id") or ""), target={"revises": str(mid)})
        return rec

    def handoff_query(self, *, mid: str = "", to: str = "", sender: str = "",
                      refs: str = "", revises: str = "") -> list[dict[str, Any]]:
        """查：判"这条是不是重复委派 / 是不是已经交接过"（用户点名的"至少要能读 handoffs"）。

        纯只读；`revises` 非空时只回"订正过某一号"的那些行。
        """
        if revises:
            return MS.revisions_of(self.root, revises)
        if mid:
            got = MS.row_of(self.root, mid)
            return [got] if got else []
        out = MS.list_all(self.root, to=str(to), sender=str(sender), limit=50)
        if refs:
            out = [r for r in out if any(str(refs) in str(x) for x in (r.get("refs") or []))]
        return out

    def handoffs_digest(self, *, limit: int = 5) -> str:
        """一小段读数：最近几份交接（判重复时的起点，进提示词用）。"""
        return MS.digest(self.root, limit=limit)

    # ------------------------------------------------------------ 名册 / 对照表 / 退役（S1k）

    def _conductor(self) -> Any:
        """能读台账的那个句柄（`store` 造一个只读用的 `Conductor`）。

        为什么不要求调用方传：秘书的读面本来就是"`store` + 手稿 + registry"
        （`draft/91` §2），名册要读台账里的代理行 ⇒ 用同一把 `store` 现造一个即可。
        造不出来 ⇒ 返回 `None`，调用方按三态如实报（不许当"名下没有子代理"）。
        """
        if self.store is None:
            return None
        from .conductor import Conductor, LocalBackend

        try:
            return Conductor(self.store, policy=None, backend=LocalBackend({}))
        except Exception:  # noqa: BLE001
            return None

    def roster_rows(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """名册的折叠后状态（`(项列表, 坏行)`）：一项 = 名字 / 角色 / 简介 / 状态。

        事件流折叠口径：`add` 建项；`bind` 只推当前调用；`retire` 标退役；
        `keep_alive` 只改那一格读数。只追加、不物理删（`draft/92` I-8）。
        """
        from . import jsonlfile as JF

        rows, bad = JF.read_jsonl(roster_path(self.root, owner))
        return _fold_roster(rows), bad

    def roster_index(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """对照表（电话簿）的折叠后状态：一项 = 名字 → `first_task_id` / `task_id`（当前）。"""
        from . import jsonlfile as JF

        rows, bad = JF.read_jsonl(roster_index_path(self.root, owner))
        return _fold_index(rows), bad

    def retired_names(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """销号名单（业主 B1）：名字一经退役永久不复用。`(行列表, 坏行)`。"""
        from . import jsonlfile as JF

        return JF.read_jsonl(retired_path(self.root, owner))

    def next_name(self, owner: str, role: str) -> tuple[str, str]:
        """下一个可用的本地名（`<角色><序号>`；退役不回收）。返回 `(名字, 问题)`。

        序号 = 该 owner 名下该角色出现过的最大序号 + 1（含已退役的项 —— 这正是
        "不回收"的落点：`D1` 退役之后下一个是 `D2`，绝不把 `D1` 给另一个人）。
        """
        rows, bad = self.roster_rows(owner)
        if bad:
            return "", f"名册有 {len(bad)} 行读不出来 ⇒ 不猜序号（{bad[0]}）"
        used = []
        for r in rows:
            name = str(r.get("name") or "")
            if name.startswith(role) and name[len(role):].isdigit():
                used.append(int(name[len(role):]))
        return f"{role}{max(used, default=0) + 1}", ""

    def roster_add(self, *, owner: str, role: str, task_id: str, brief: str,
                   task_id_first: str = "", want_name: str = "", reuse: str = "",
                   surface: str = "") -> dict[str, Any]:
        """名册登记（增那一支）：`{"name","role","task_id","problem"}`。

        - `reuse` 给了名字 ⇒ 只推进对照表的当前调用，名册项不动（复用不是增）；
        - 否则：`want_name` 给了就用它（已被用过的名字一律拒，含已退役的 ⇒ "已销号"），
          没给就用 `next_name`；
        - 名册行与对照表行一笔写：任一写失败 ⇒ 返回 problem 并不留下半份
          （先写对照表再写名册；前者失败就不写后者。反过来会造出"有名字没电话"的项）。
        - `brief` 为空 ⇒ 拒（内容面：那句话是退役时认人的唯一依据，秘书不替它编）。
        """
        text = str(brief or "").strip()
        if not text:
            return {"name": "", "role": str(role), "task_id": str(task_id),
                    "problem": "没给一句任务简介（它进名册：退役时读的人靠它认人）"}
        if len(text) > 60 or "\n" in text:
            return {"name": "", "role": str(role), "task_id": str(task_id),
                    "problem": "任务简介必须是单行、不超过 60 字（超长属于内容，秘书不替它删）"}
        at = _now_iso()
        if reuse:
            name = str(reuse)
            if not self._name_exists(owner, name):
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "problem": f"名册里没有 {name} ⇒ 不猜（复用必须父先看活跃名册）"}
            if self._is_retired(owner, name):
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "problem": f"{name} 已销号（退役的名字永久不复用，业主 B1）"}
            ok, why = append_jsonl(roster_index_path(self.root, owner),
                                   {"kind": "bind", "owner": owner, "name": name,
                                    "role": str(role), "task_id": str(task_id), "at": at})
            if not ok:
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "problem": f"对照表没写成：{why}"}
            return {"name": name, "role": str(role), "task_id": str(task_id), "problem": ""}

        if want_name:
            name = str(want_name)
            if self._name_exists(owner, name):
                problem = (f"{name} 已经用过（{'已销号' if self._is_retired(owner, name) else '在用'}）"
                           "⇒ 受控拒绝：不许静默改名（业主 B2）")
                return {"name": name, "role": str(role), "task_id": str(task_id),
                        "problem": problem}
        else:
            name, problem = self.next_name(owner, role)
            if problem:
                return {"name": "", "role": str(role), "task_id": str(task_id),
                        "problem": problem}
        # S1n（业主 T23 / B2）：造一个新子代理时同时预订一个读写面（父可以点名要哪个槽位）。
        # 拿不到面 ⇒ 受控拒绝（不许先给名字后没有面：那会造出一个"能说话但不能干活"的项）。
        got_surface = self.surface_alloc(owner=owner, want=str(surface or ""), name=name)
        if got_surface.get("problem"):
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"读写面没定下来：{got_surface['problem']}"}
        ok, why = append_jsonl(roster_index_path(self.root, owner),
                               {"kind": "bind", "owner": owner, "name": name,
                                "role": str(role), "task_id": str(task_id), "at": at,
                                "first": True})
        if not ok:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"对照表没写成：{why}"}
        ok2, why2 = append_jsonl(roster_path(self.root, owner),
                                 {"kind": "add", "owner": owner, "name": name,
                                  "role": str(role), "task_id": str(task_id),
                                  "first_task_id": str(task_id_first or task_id),
                                  "brief": text, "surface": str(got_surface.get("slot") or ""),
                                  "at": at})
        if not ok2:
            return {"name": name, "role": str(role), "task_id": str(task_id),
                    "problem": f"名册没写成（对照表那一行已经落了 ⇒ 读侧会报'半份登记'）：{why2}"}
        return {"name": name, "role": str(role), "task_id": str(task_id),
                "surface": str(got_surface.get("slot") or ""), "problem": ""}

    # ---- 读写面与槽位池（S1n）

    def surface_rows(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """池的折叠视图（`(槽位列表, 坏行)`）。"""
        from . import jsonlfile as JF

        rows, bad = JF.read_jsonl(surfaces_path(self.root, owner))
        return _fold_surfaces(rows), bad

    def surface_state(self, owner: str) -> dict[str, Any]:
        """池的三态读数：`{"checked","in_use":[{slot,name}],"free":[…],"pending_release":[…],"reason"}`。

        读不成 ⇒ `checked=False`（不许返回空池冒充"都空闲"）。
        """
        try:
            rows, bad = self.surface_rows(owner)
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "in_use": [], "free": [], "pending_release": [],
                    "reason": f"{type(exc).__name__}: {exc}"}
        if bad:
            return {"checked": False, "in_use": [], "free": [], "pending_release": [],
                    "reason": f"池事件有 {len(bad)} 行读不出来：{bad[0]}"}
        return {"checked": True,
                "in_use": [{"slot": r["slot"], "name": r["name"]} for r in rows
                           if r["state"] == "在用"],
                "free": [r["slot"] for r in rows if r["state"] == "空闲"],
                "pending_release": [{"slot": r["slot"], "name": r["name"],
                                     "reason": r.get("reason", "")} for r in rows
                                    if r["state"] == "待释放"],
                "reason": ""}

    def surface_alloc(self, *, owner: str, want: str = "", name: str = "") -> dict[str, Any]:
        """从池里取一个干净的槽位给 `name` 用（派活那一刻，与 `roster_add` 同一趟）。

        - `want` 给了 ⇒ 要求它是空闲的（在用 / 待释放 ⇒ 受控拒绝，不静默换一个）；
        - 没给 ⇒ 取"空闲里最小的"；池里没有空闲 ⇒ 新建一个（`S<两位数>`，序号只增不减）；
        - 返回 `{"slot","path","problem"}`；拿不到 ⇒ `problem` 非空（调用方按受控拒绝处理）。
        """
        state = self.surface_state(owner)
        if not state.get("checked"):
            return {"slot": "", "path": "", "problem": f"池没读成（{state.get('reason')}）"}
        in_use = {str(x["slot"]) for x in state["in_use"]}
        pend = {str(x["slot"]) for x in state["pending_release"]}
        if want:
            slot = str(want)
            if slot in in_use or slot in pend:
                return {"slot": slot, "path": "",
                        "problem": f"槽位 {slot} 不在空闲池里（在用或待释放）⇒ 受控拒绝"}
        else:
            free = sorted(state["free"])
            if free:
                slot = free[0]
            else:
                used = in_use | pend | {str(x) for x in state["free"]}
                n = 1
                while f"S{n:02d}" in used:
                    n += 1
                slot = f"S{n:02d}"
        path = surface_dir(self.root, owner, slot)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"slot": slot, "path": "", "problem": f"面建不出来：{type(exc).__name__}: {exc}"}
        ok, why = append_jsonl(surfaces_path(self.root, owner),
                               {"kind": "alloc", "owner": owner, "slot": slot,
                                "name": str(name), "at": _now_iso()})
        if not ok:
            return {"slot": slot, "path": str(path), "problem": f"池事件没写成：{why}"}
        return {"slot": slot, "path": str(path), "problem": ""}

    def surface_release(self, *, owner: str, name: str, slot: str) -> tuple[str, str]:
        """归还一个槽位：先归档面里的东西，再写 `release`；归档失败 ⇒ `archive_failed`
        （槽位停在"待释放"、不入池）。返回 `(落成的状态, 问题)`。"""
        src = surface_dir(self.root, owner, slot)
        dst = archive_dir(self.root, owner, name)
        state = "空闲"
        if src.is_dir() and any(src.iterdir()):
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    import shutil

                    shutil.rmtree(dst)
                import shutil

                shutil.move(str(src), str(dst))
                src.mkdir(parents=True, exist_ok=True)
            except Exception as exc:  # noqa: BLE001 —— 没归档干净就不许放回池
                state, why = "待释放", f"{type(exc).__name__}: {exc}"
                append_jsonl(surfaces_path(self.root, owner),
                             {"kind": "archive_failed", "owner": owner, "slot": slot,
                              "name": str(name), "reason": why, "at": _now_iso()})
                return state, why
        ok, why2 = append_jsonl(surfaces_path(self.root, owner),
                                {"kind": "release", "owner": owner, "slot": slot,
                                 "name": str(name), "at": _now_iso()})
        if not ok:
            return "待释放", f"池事件没写成：{why2}"
        return state, ""

    def surface_of(self, *, owner: str, task_id: str) -> dict[str, Any]:
        """某个调用行「此刻」该用的读写面：`{"checked","name","slot","path","reason"}`。

        为什么必须两步查（实测踩过）：`task_id` 的当前值在对照表里（`_fold_index`
        认 `bind`），而名册的 `add` 行记的是第一次那个调用 ⇒ 只读名册会把
        "复用过的名字"（`draft/92` I-12）判成"这一行没有面"，于是那一趟静默不切面。
        顺序：对照表 `task_id → name`，再名册 `name → surface`。

        已退役 ⇒ `checked=False`：退役时槽位已经归还池里，可能已经分给别人了，
        照旧读出那个槽位就等于让两个人的面重叠（跨代理写同一份文件）。
        读不成一律 `checked=False`（调用方按"没切面"处理，不许假装切过）。
        """
        name, why = self.name_of(owner=owner, task_id=str(task_id))
        if not name:
            return {"checked": False, "name": "", "slot": "", "path": "",
                    "reason": why or f"对照表里没有 {task_id!r}"}
        rows, bad = self.roster_rows(owner)
        if bad:
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"名册有 {len(bad)} 行读不出来：{bad[0]}"}
        item = next((r for r in rows if str(r.get("name") or "") == name), None)
        if item is None:
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"名册里没有 {name}（对照表里有 ⇒ 半份登记）"}
        if item.get("retired"):
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"{name} 已退役 ⇒ 面已归还池里（不照旧读，免得与别人重叠）"}
        slot = str(item.get("surface") or "")
        if not slot:
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"{name} 名下没登记读写面（老项或补登记）"}
        return {"checked": True, "name": name, "slot": slot,
                "path": str(surface_dir(self.root, owner, slot)), "reason": ""}

    # ------------------------------------------------------------ 面适配（S1g-2）

    def surface_fit(self, *, action: str, params: Mapping[str, Any],
                    face: str = "", base: str = "") -> dict[str, Any]:
        """这件活落在被派人的读写面里做不做得成（三态读数，只报不改）。

        业主 2026-10-09 逐字：「"超越职责"的一个主要可能是无法在被分配的读写面内
        完成任务，这个秘书也要帮忙看，不只是看任务是否符合角色设计」
        （`draft/90` §1.11；符号级规格见 `draft/92` §3.3 的 S1g-2 块）。

        ## 判什么

        只判声明里给出的盘上路径（参数名由 :func:`surface_path_args` 一处给出，
        与执行期硬拦同一张表）。逐条给"这一句话在两边的所指是不是同一个文件"：

        | `verdict` | 判据 | 意思 |
        |---|---|---|
        | `escapes` | 解析结果落在面外 | 越界：面内做不成 |
        | `in_face` | 解析结果在面里（面已知时才给这一档） | 做得到 |
        | `not_in_face` | 父视角那一份（`base/<raw>`）盘上有，而面内那一份盘上没有 | 错位：同一句路径在两边不是同一个文件 |
        | `unknown` | 面未定 / 盘上两边都没有 / 解析不了 | 判不了（不许折成 in_face） |

        ## 为什么 `not_in_face` 不需要知道槽位

        新起一个子代理时槽位还没分（`surface_alloc` 与 `roster_add` 同一趟），所以
        "落点在这一族的面里的哪一格"判不了。但 `escapes` 与 `not_in_face` 两档的判据是
        "两份所指不是同一个文件"，与槽位无关 —— 它们正是"面内做不成"的主体，
        于是这条读数在派活那一刻就有用（不必等子的第 1 步撞墙）。

        ## 为什么只报不改

        路径值是内容面（`draft/90` §1.2 那条红线）：把它改写成另一条路径 = 替父决定
        "这件事该在哪儿做"。秘书的活是把它变成看得见的事，处置权在父
        （切一块面给子 / 派给已经有那块盘的实例 / 记成"职责之外"那一档）。

        ## 参数

        - `face`：收件方这趟的面（复用/续跑时已知，`surface_of` 读得出）；
        - `base`：本实例自己的根（父视角的基准）—— 不给 ⇒ 用 `self.root`
          （顶层那一趟两者相同；子代理那一趟它自己的根是它的面，调用方要传进来）。
        """
        out: dict[str, Any] = {"checked": False, "fits": None, "paths": [],
                               "reason": ""}
        names = surface_path_args(action)
        if not names:
            out["reason"] = (f"{action or '（没给动作）'} 不是 fs 动作 ⇒ 面这一维不适用"
                             "（不适用不是通过）")
            return out
        try:
            root = Path(str(base or self.root))
            face_dir = Path(str(face)).resolve() if str(face or "") else None
        except Exception as exc:  # noqa: BLE001 —— 读不成 ⇒ 判不了（不是"没问题"）
            out["reason"] = f"面/基准读不成（{type(exc).__name__}: {exc}）⇒ 判不了"
            out["checked"] = True
            return out
        rows: list[dict[str, Any]] = []
        for key in names:
            raw = (params or {}).get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue                       # 没给这一格 ⇒ 没有可判的路径（如实记在 reason 里）
            rows.append(self._judge_one_path(key, raw.strip(), root=root, face_dir=face_dir))
        if not rows:
            out.update(checked=True,
                       reason=f"{action} 这一件没给路径参数（{'/'.join(names)}）⇒ 判不了"
                              "（不是通过）")
            return out
        verdicts = {str(r.get("verdict") or "") for r in rows}
        fits: bool | None
        if verdicts & {"escapes", "not_in_face"}:
            fits = False
        elif verdicts == {"in_face"}:
            fits = True
        else:
            fits = None                        # 全是 unknown ⇒ 判不了（三态不许折平）
        bad = [r for r in rows if str(r.get("verdict") or "") in ("escapes", "not_in_face")]
        reason = ""
        if fits is False:
            reason = "；".join(
                f"{r['where']}={r['value']!r} {r['why']}" for r in bad)
        elif fits is None:
            reason = "；".join(str(r.get("why") or "") for r in rows) or "没有可判的路径 ⇒ 判不了"
        out.update(checked=True, fits=fits, paths=rows, reason=reason)
        return out

    def _judge_one_path(self, where: str, raw: str, *, root: Path,
                        face_dir: Path | None) -> dict[str, Any]:
        """一条路径的判决（纯计算；`surface_fit` 的逐条那一半）。

        分两种情形（`face_dir` 有没有给），判据都只有一条：这一句话在两边指的是不是
        同一个文件。
        """
        row: dict[str, Any] = {"where": where, "value": raw, "face": "", "ws": "",
                               "face_exists": None, "ws_exists": None,
                               "verdict": "unknown", "why": ""}
        try:
            p = Path(raw)
            ws_path = (p if p.is_absolute() else (root / raw)).resolve()
        except Exception as exc:  # noqa: BLE001 —— 解析不了 ⇒ unknown（不许猜）
            row["why"] = f"路径解析不了（{type(exc).__name__}: {exc}）"
            return row
        row["ws"] = str(ws_path)
        if face_dir is not None:
            try:
                face_path = (p if p.is_absolute() else (face_dir / raw)).resolve()
            except Exception as exc:  # noqa: BLE001
                row["face"] = str(face_dir)
                row["why"] = f"面内落点算不出来（{type(exc).__name__}: {exc}）"
                return row
            row["face"] = str(face_path)
            row["face_exists"] = bool(face_path.exists())
            row["ws_exists"] = bool(ws_path.exists())
            try:
                face_path.relative_to(face_dir)
            except ValueError:
                row["verdict"] = "escapes"
                row["why"] = "越出了收件方这趟的读写面（面外一律不做）"
                return row
            if row["face_exists"] or face_path == ws_path:
                # 面里就有这一份（父已经把它切进面了），或两边算出来是同一个文件
                # ⇒ 做得到。面内的新文件也走这一档（T23："若子代理想新写文件，
                # 这个是允许的"）—— 见下面"两边都没有"那一格。
                row["verdict"] = "in_face"
                row["why"] = "落在面内（面内的新文件本来就允许）"
                return row
            if row["ws_exists"]:
                # 父视角那一份在工作区里（父指的就是它），而面内的落点不是同一个
                # 文件、且面里没有这一份 ⇒ 子在它那边找的是另一条路径：错位。
                row["verdict"] = "not_in_face"
                row["why"] = ("这一份在工作区里（父的视角指得到它），而收件方那趟的根是"
                              "它的面 ⇒ 子在它那边找的是另一条路径：面内做不成（要么把"
                              "这一份切进它的面，要么这一件就是『职责之外』那一档）")
                return row
            row["verdict"] = "unknown"
            row["why"] = ("两边都没有这一份 ⇒ 判不了（面内新建是允许的；若父要的是工作区"
                          "那一份，它现在还不存在）")
            return row
        # ---- 面未定（新起一个子代理）：判"父视角那一份在不在面可能覆盖的范围内"
        family = (root / "out" / "surfaces" / str(self.task_id or "")).resolve()
        try:
            ws_path.relative_to(root.resolve())
            in_workspace = True
        except ValueError:
            in_workspace = False
        row["ws_exists"] = bool(ws_path.exists())
        if not in_workspace:
            row["verdict"] = "escapes"
            row["why"] = ("落点在整个工作区之外（面是工作区里的一个子目录）⇒ 面内做不成")
            return row
        try:
            ws_path.relative_to(family)
            in_family = True
        except ValueError:
            in_family = False
        if in_family:
            row["verdict"] = "unknown"
            row["why"] = ("落点在这一族的面里，但槽位要到派活那一刻才分 ⇒ 判不了"
                          "（不是通过）")
            return row
        if row["ws_exists"]:
            row["verdict"] = "not_in_face"
            row["why"] = ("这一份在工作区里（父的视角指得到它），而收件方那趟的根是它的面"
                          "⇒ 子在它那边找的是另一条路径：面内做不成（要么把这一份切进它的"
                          "面，要么这一件就是『职责之外』那一档）")
            return row
        row["verdict"] = "unknown"
        row["why"] = "盘上没有这一份、也不在这一族的面里 ⇒ 判不了（新文件本来就允许）"
        return row

    def surface_readings(self, shape: str, payload: Mapping[str, Any],
                         *, face: str = "", base: str = "") -> dict[str, Any]:
        """派活形状 → 面适配读数（`summon` 一条；`summon_many` 逐项）。

        不派活的形状（`handoff` / `message` / `retire` / `roster`）⇒ 这一维不适用，
        如实说清（不适用不是通过）。
        """
        try:
            if shape == "summon":
                got = self.surface_fit(action=str(payload.get("action") or ""),
                                       params=(payload.get("params")
                                               if isinstance(payload.get("params"),
                                                             Mapping) else {}),
                                       face=face, base=base)
                return {**got, "shape": shape}
            if shape == "summon_many":
                targets = payload.get("targets")
                if not isinstance(targets, (list, tuple)):
                    return {"shape": shape, "checked": False, "fits": None, "items": [],
                            "reason": "targets 不是数组 ⇒ 面这一维判不了"}
                items = []
                for i, item in enumerate(targets):
                    sub = item if isinstance(item, Mapping) else {}
                    items.append({"index": i,
                                  **self.surface_fit(action=str(sub.get("action") or ""),
                                                     params=(sub.get("params")
                                                             if isinstance(
                                                                 sub.get("params"), Mapping)
                                                             else {}),
                                                     face=face, base=base)})
                fits: bool | None
                if any(x.get("fits") is False for x in items):
                    fits = False
                elif items and all(x.get("fits") is True for x in items):
                    fits = True
                else:
                    fits = None
                bad = [x for x in items if x.get("fits") is False]
                return {"shape": shape, "checked": True, "fits": fits, "items": items,
                        "reason": "；".join(f"targets[{x['index']}]：{x.get('reason')}"
                                            for x in bad)}
        except Exception as exc:  # noqa: BLE001 —— 面这一维没查成不许打断派活
            return {"shape": shape, "checked": False, "fits": None,
                    "reason": f"面适配没跑成（{type(exc).__name__}: {exc}）"}
        return {"shape": shape, "checked": False, "fits": None,
                "reason": f"{shape} 不派活 ⇒ 面这一维不适用（不适用不是通过）"}

    def _face_of_name(self, *, owner: str, name: str) -> str:
        """名册名 → 它此刻的面目录（读不成 / 已退役 / 没登记 ⇒ 空串 + 不假装查过）。"""
        want = str(name or "")
        if not want:
            return ""
        try:
            rows, bad = self.roster_rows(owner)
            if bad:
                return ""
            item = next((r for r in rows if str(r.get("name") or "") == want), None)
            if item is None or item.get("retired"):
                return ""
            slot = str(item.get("surface") or "")
            if not slot:
                return ""
            return str(surface_dir(self.root, owner, slot))
        except Exception:  # noqa: BLE001
            return ""

    def roster_repair(self, *, owner: str) -> tuple[int, str]:
        """补登记（自愈）：把"台账里有、名册里没有"的代理行补上。返回 `(补了几条, 问题)`。

        只在写路径被调用（`draft/92` I-15：查只报不修）。补的时候按 `task_id` 升序，
        于是两个并发修复不会重复分配（名字在 `next_name` 里按已用最大序号推）。
        """
        cond = self._conductor()
        if cond is None:
            return 0, "没有 store ⇒ 读不到台账，补不了"
        try:
            rows = [r for r in cond._tasks()
                    if r.get("parent_task_id") == owner and not str(r.get("kind") or "")]
        except Exception as exc:  # noqa: BLE001
            return 0, f"台账读不成（{type(exc).__name__}: {exc}）"
        index, bad = self.roster_index(owner)
        if bad:
            return 0, f"对照表有 {len(bad)} 行读不出来 ⇒ 不补（免得重名）"
        known = {str(r.get("task_id") or "") for r in index}
        todo = sorted(str(r.get("task_id") or "") for r in rows
                      if str(r.get("task_id") or "") not in known)
        fixed = 0
        for tid in todo:
            row = next((r for r in rows if str(r.get("task_id") or "") == tid), {})
            role = str(row.get("role") or "")
            name, problem = self.next_name(owner, role)
            if problem:
                return fixed, problem
            ok, why = append_jsonl(roster_index_path(self.root, owner),
                                   {"kind": "bind", "owner": owner, "name": name, "role": role,
                                    "task_id": tid, "at": _now_iso(), "repaired": True})
            if not ok:
                return fixed, f"补登记没写成：{why}"
            ok2, why2 = append_jsonl(roster_path(self.root, owner),
                                     {"kind": "add", "owner": owner, "name": name, "role": role,
                                      "task_id": tid, "first_task_id": tid,
                                      "brief": "（补登记：这一条当时没写进名册）",
                                      "at": _now_iso(), "repaired": True})
            if not ok2:
                return fixed, f"名册补写没成：{why2}"
            fixed += 1
        return fixed, ""

    def resolve_down(self, *, owner: str, name: str) -> tuple[str, str]:
        """下行译码：我名下名册里的名字 → 当前调用行。"""
        return self._resolve(owner, name)

    def resolve_up(self, *, my_task_id: str, name: str) -> tuple[str, str]:
        """上行译码：我父名册里的名字 → 当前调用行（父的代号从我那一行读）。"""
        cond = self._conductor()
        if cond is None:
            return "", "没有 store ⇒ 读不到我那一行（不知道父是谁）"
        try:
            row = cond._task(str(my_task_id or ""))
        except Exception as exc:  # noqa: BLE001
            return "", f"台账读不成（{type(exc).__name__}: {exc}）"
        if not row:
            return "", f"台账里没有我这一行（{my_task_id!r}）"
        parent = str(row.get("parent_task_id") or "")
        if not parent:
            return "", "我是顶层发起 ⇒ 没有父名册（上行只能发给用户/主控）"
        return self._resolve(parent, name)

    def name_of(self, *, owner: str, task_id: str) -> tuple[str, str]:
        """反查：某个调用行属于这个名册里的哪一个名字。"""
        index, bad = self.roster_index(owner)
        if bad:
            return "", f"对照表有 {len(bad)} 行读不出来"
        for r in index:
            if str(r.get("task_id") or "") == str(task_id):
                return str(r.get("name") or ""), ""
        return "", f"对照表里没有 {task_id}（未登记）"

    def roster_view(self, *, owner: str) -> dict[str, Any]:
        """名册视图（只读，不许修补 —— I-15）：`{"checked","rows","reason"}`。

        每一行：`name` / `role` / `brief` / `state`（活跃 / 待命 / 已停 / 已退役）/
        `retirable`（按 `conductor.retire_ready` 的三分支）/ `items_open`（只报不拦）/
        `task_id`（当前调用）。
        规模：默认只回 20 项 + `more`（与 `inbox_digest` 的窗口同族口径）。
        """
        cond = self._conductor()
        rows, bad = self.roster_rows(owner)
        if bad:
            return {"checked": False, "rows": [], "more": 0,
                    "reason": f"名册有 {len(bad)} 行读不出来：{bad[0]}"}
        if cond is None:
            return {"checked": False, "rows": [], "more": 0,
                    "reason": "没有 store ⇒ 读不到台账（状态判不了）"}
        try:
            ready = cond.retire_ready(owner)
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "rows": [], "more": 0,
                    "reason": f"就绪读数没读成（{type(exc).__name__}: {exc}）"}
        if not ready.get("checked"):
            return {"checked": False, "rows": [], "more": 0,
                    "reason": f"就绪读数没读成（{ready.get('reason')}）"}
        by_child = {str(r["task_id"]): r for r in ready.get("ready", [])}
        out: list[dict[str, Any]] = []
        for r in rows:
            tid = str(r.get("task_id") or "")
            branch = str((by_child.get(tid) or {}).get("branch") or "")
            state = _state_from(branch, bool(r.get("retired")), cond, tid)
            out.append({"name": str(r.get("name") or ""), "role": str(r.get("role") or ""),
                        "brief": str(r.get("brief") or ""), "state": state,
                        "retirable": branch == "waiting_no_children",
                        "items_open": int(((by_child.get(tid) or {}).get("reading") or {})
                                          .get("items_open") or 0),
                        "task_id": tid})
        more = max(0, len(out) - 20)
        return {"checked": True, "rows": out[:20], "more": more, "reason": ""}

    def latest_report_of(self, *, task_id: str, role: str = "") -> dict[str, Any]:
        """某个实例最近的工作报告（退役第①支要端给父的东西）。

        口径：优先 `handoffs` 里 `task_id == 该实例` 的那些行；一条都没有时退回
        "发信人是该角色"的最新一行（历史 595 行没有 `task_id`，`draft/94` §3 ——
        这条退路要写明，否则那段历史读起来像"它从没报过"）。
        体积：默认只给摘要 + 编号 + 正文前 300 字（全文由父自己 `manuscripts.read`）。
        """
        try:
            rows, bad = MS.read_rows(self.root)
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "reason": f"手稿读不成（{type(exc).__name__}: {exc}）"}
        mine = [r for r in rows if str(r.get("task_id") or "") == str(task_id)]
        source = "task_id"
        if not mine and role:
            mine = [r for r in rows if str(r.get("sender") or "") == str(role)]
            source = "sender"
        if not mine:
            return {"checked": True, "handoff_id": "", "summary": "",
                    "head": "", "at": "", "source": "", "bad_rows": len(bad),
                    "reason": "这个实例名下没有找到报告行"}
        mine.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or "")))
        last = mine[-1]
        return {"checked": True, "handoff_id": str(last.get("id") or ""),
                "summary": str(last.get("summary") or ""),
                "head": _clip_text(str(last.get("body") or ""), 300),
                "at": str(last.get("created_at") or ""), "source": source,
                "bad_rows": len(bad), "reason": ""}

    def active_children_of(self, *, task_id: str) -> dict[str, Any]:
        """退役第②支：它自己名下的活跃子代理（代理轴，不是父的）。"""
        cond = self._conductor()
        if cond is None:
            return {"checked": False, "rows": [], "reason": "没有 store ⇒ 读不到台账"}
        try:
            return cond.active_children(task_id)
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "rows": [],
                    "reason": f"{type(exc).__name__}: {exc}"}

    def retire(self, *, owner: str, name: str, by_task_id: str = "") -> dict[str, Any]:
        """退役（业主 §1.9 的三分支，`draft/90` §1.9 逐字）。返回：

        `{"ok","action":"retired"|"reported"|"refused","report":{…},"why":[…], "reading":{…}}`

        - `active` ⇒ `reported`：把最近的工作报告端给父，不退役；
        - `waiting_with_children` ⇒ `reported`：把那些子代理在它名册里的任务简介端给父；
        - `waiting_no_children` ⇒ `retired`：写退役事件 + 销号名单 + 对照表标退役 +
          `conductor.note_edge_release`（父侧那一笔幂等落痕）；
        - 未登记 / 读不成 / 已销号 ⇒ `refused`（没读成 ≠ 可以退役）。
        """
        cond = self._conductor()
        if cond is None:
            return {"ok": False, "action": "refused", "report": {},
                    "why": ["没有 store ⇒ 读不到台账（没读成，不是'不在跑'）"]}
        tid, problem = self.resolve_down(owner=owner, name=str(name))
        if problem:
            if self._is_retired(owner, str(name)):
                return {"ok": False, "action": "refused", "report": {},
                        "why": [f"{name} 已经销号过（业主 B1：名字永久不复用）"]}
            return {"ok": False, "action": "refused", "report": {}, "why": [problem]}
        if self._is_retired(owner, str(name)):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"{name} 已经销号过（业主 B1）"]}
        try:
            ready = cond.retire_ready(owner)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"就绪读数没读成（{type(exc).__name__}: {exc}）"]}
        if not ready.get("checked"):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"就绪读数没读成（{ready.get('reason')}）"]}
        row = next((r for r in ready.get("ready", []) if str(r.get("task_id")) == tid), None)
        if row is None:
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"{name}（{tid}）不在就绪清单里（已经退过，或它不在这个父名下）"]}
        branch = str(row.get("branch") or "")
        reading = dict(row.get("reading") or {})
        if branch == "active":
            report = self.latest_report_of(task_id=tid, role=str(row.get("role") or ""))
            return {"ok": False, "action": "reported", "report": report,
                    "why": [f"{name} 还在跑 ⇒ 先看它最近报了什么，不退役"],
                    "reading": reading}
        if branch == "waiting_with_children":
            kids = self.active_children_of(task_id=tid)
            if not kids.get("checked"):
                return {"ok": False, "action": "refused", "report": {},
                        "why": [f"{name} 名下的活跃子代理没读成（{kids.get('reason')}）"]}
            briefs = []
            for k in kids.get("rows", []):
                kid_name, _why = self.name_of(owner=tid, task_id=str(k.get("task_id") or ""))
                child_rows, _bad = self.roster_rows(tid)
                brief = next((str(x.get("brief") or "") for x in child_rows
                              if str(x.get("name") or "") == kid_name), "")
                briefs.append({"name": kid_name or "（未登记）",
                               "role": str(k.get("role") or ""),
                               "brief": brief, "state": str(k.get("state") or "")})
            return {"ok": False, "action": "reported", "report": {"children": briefs},
                    "why": [f"{name} 名下还有活跃子代理 ⇒ 不退役（它还在干什么活见 report）"],
                    "reading": reading}
        ok, why = cond.note_edge_release(owner, child_task_id=tid, attempt=1)
        if not ok and "已经记过" not in why:
            return {"ok": False, "action": "refused", "report": {}, "why": [why],
                    "reading": reading}
        at = _now_iso()
        wrote_roster, why_r = append_jsonl(roster_path(self.root, owner),
                                           {"kind": "retire", "owner": owner, "name": str(name),
                                            "task_id": tid, "branch": branch, "by": str(by_task_id),
                                            "reading": reading, "at": at})
        wrote_index, why_i = append_jsonl(roster_index_path(self.root, owner),
                                          {"kind": "retire", "owner": owner, "name": str(name),
                                           "task_id": tid, "at": at})
        wrote_retired, why_x = append_jsonl(retired_path(self.root, owner),
                                            {"owner": owner, "name": str(name), "task_id": tid,
                                             "role": str(row.get("role") or ""), "at": at,
                                             "branch": branch})
        if not (wrote_roster and wrote_index and wrote_retired):
            return {"ok": False, "action": "refused", "report": {},
                    "why": [f"退役没写全（名册={wrote_roster}/{why_r} 对照表={wrote_index}/{why_i} "
                            f"销号={wrote_retired}/{why_x}）"],
                    "reading": reading}
        # S1n（业主补充）：退役 ⇒ 面归还"可分配池"（名字不回收、面回收）。
        # 归还前先归档；归档失败 ⇒ 槽位停在"待释放"，读数里如实写（不入池）。
        surface_note = ""
        slot = next((str(r.get("surface") or "") for r in self.roster_rows(owner)[0]
                     if str(r.get("name") or "") == str(name)), "")
        if slot:
            state, why_s = self.surface_release(owner=owner, name=str(name), slot=slot)
            surface_note = (f"面 {slot} 已归还池里" if state == "空闲"
                            else f"面 {slot} 停在待释放（{why_s}）")
        return {"ok": True, "action": "retired", "report": {},
                "why": [f"{name} 退役：{branch}（子已停 + 它名下无活跃子代理）"]
                       + ([surface_note] if surface_note else []),
                "surface": slot, "reading": reading}

    # ---- 名册的内部小工具

    def _resolve(self, owner: str, name: str) -> tuple[str, str]:
        index, bad = self.roster_index(owner)
        if bad:
            return "", f"对照表有 {len(bad)} 行读不出来 ⇒ 不译（{bad[0]}）"
        for r in index:
            if str(r.get("name") or "") == str(name) and not r.get("retired"):
                return str(r.get("task_id") or ""), ""
        return "", f"对照表里没有 {name!r}（未登记或已退役）"

    def _name_exists(self, owner: str, name: str) -> bool:
        rows, _bad = self.roster_rows(owner)
        return any(str(r.get("name") or "") == str(name) for r in rows)

    def _is_retired(self, owner: str, name: str) -> bool:
        rows, _bad = self.retired_names(owner)
        return any(str(r.get("name") or "") == str(name) for r in rows)

    # ------------------------------------------------------------ 内部

    def _log(self, message: str) -> None:
        if self.log is None:
            return
        try:
            self.log(message)
        except Exception:  # noqa: BLE001 - 日志口子坏了不该带走秘书的判断
            pass


def _judge_prompt(kind: str, context: Mapping[str, Any]) -> str:
    """三类判断的提示词（`draft/55` §2 的 B 类）。

    契约三句：① 只回一个 JSON 对象；② `decision` 必须取自 :data:`DECISIONS` 的词表
    （词表外的结论一律不采信，见 :meth:`Secretary.judge`）；③ `basis` 写"你凭什么"。
    为什么把词表写进提示词：模型给的自由文本结论无法与台账的 `decision` 栏对齐，
    而"结论栏里出现第八种写法"正是同一件事两个名字的老毛病。
    """
    head = (f"你是「秘书」的判断面（类别：{kind}）。只回一个 JSON 对象，字段："
            f'decision（必须取自 {list(DECISIONS)}）、reason（一句话）、basis（字符串数组，'
            "写清你凭什么，例如 `specs/d.py` 的哪一条或 `tasks` 里的哪一行）。")
    body = json.dumps(dict(context), ensure_ascii=False, sort_keys=True, default=str)[:4000]
    if kind == "duplicate_retry":
        ask = ("问题：同一个 (role, action, input_key) 已经有下面这些终态行。这一次是"
               "正当的重试，还是重复委托？判『可派』= 这次该照派；判『建议不派』= 别重复派。")
    elif kind == "tool_name":
        ask = ("问题：本体写的工具名不在注册表里。要映到下面哪一个候选吗？"
               "判『建议重排』= 映到某一个（在 reason 里写清是哪一个）；"
               "判『建议不派』= 一个都不映（这次不该调工具）。")
    else:
        ask = ("问题：这条委托照声明看不合规（或与收件方的角色定位不匹配）。"
               "该重排成什么？判『建议重排』并在 reason 里给出重排后的说法；"
               "判『建议改派』= 换一个收件方更合适；判『建议不派』= 别派这条。")
    return f"{head}\n\n{ask}\n\n材料：\n{body}\n"


def for_role(role: str, *, root: str | Path, **kw: Any) -> Secretary:
    """造一名某角色的秘书（`draft/53` §5 的"批量给 A–H 装"：批量 = 配置 + 测试）。

    装配点只有两个：`agent_loop.run_role`（所有角色共用的驱动，经
    `agent_loop._secretary_for`）与 `conductor.Conductor`（M 的派活路径）——
    两者都不在 FC-27 名册。生产路径会传 `seam=<本角色自己的 LlmSeam>` 与
    `enable_model=True`（主控裁定 A5），于是三条判断真的发生、花销记在本体账上。
    """
    return Secretary(str(role), root=Path(str(root)), **kw)


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _older_than(stamp: Any, now: str, window_sec: int) -> bool:
    """`stamp` 比 `now` 早了超过 `window_sec` 秒吗（"够久了还没核"的判据）。

    三个"不知道"都回 `False`（不列，而不是"列成待核"）：没有时间戳 / 解析不了 /
    时钟反了。理由：待核队列一旦把"判不了"也列进去，它就会变成"什么都往里塞"的
    假阳性来源（主控点名的那条负控）。
    """
    raw = str(stamp or "").strip()
    if not raw:
        return False
    try:
        then = _dt.datetime.fromisoformat(raw)
        reference = _dt.datetime.fromisoformat(str(now))
    except ValueError:
        return False
    try:
        return (reference - then).total_seconds() > float(window_sec)
    except (TypeError, ValueError):
        return False


def selftest() -> int:
    """最小自检：台账分角色、手稿增改查、fail-open 与"执笔失败必须报错"。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="secretary_selftest_"))
    checks: list[tuple[str, bool]] = []
    s = Secretary("D", root=root)
    rec = s.handoff_add(to="F", summary="把猜想交给你", body="证明它。")
    checks.append(("执笔的 sender 是被服务的角色", rec.get("sender") == "D"))
    rev = s.handoff_revise(mid=rec["id"], summary="交接（订正）", body="证明它（第二版）。",
                           reason="引错了一处")
    checks.append(("旧行还在", MS.row_of(root, rec["id"]) is not None))
    checks.append(("订正指回旧行", (MS.row_of(root, rev["id"]) or {}).get("revises") == rec["id"]))
    checks.append(("查得到订正", [r["id"] for r in s.handoff_query(revises=rec["id"])] == [rev["id"]]))
    checks.append(("台账分角色", decisions_path(root, "D").is_file()
                   and not decisions_path(root, "M").exists()))
    # S1m：分片之后"台账分角色"这一条要按两种落点都认（老文件 / 实例分片），
    # 并且保留一条"老文件仍可读"的反负控 —— 否则分片会悄悄改掉历史工作区的读侧口径。
    shard = Secretary("E", root=root)
    shard.bind_task("t-0007")
    shard.note_decision(duty=1, kind=KIND_OPTIMIZED, decision="已优化", reason="自检：分片写入")
    checks.append(("台账按实例分片", shard.decisions_path().is_file()
                   and shard.decisions_path().name == "E-t-0007.jsonl"))
    checks.append(("分片读得回来（且老文件仍可读）",
                   len(shard.decisions()) == 1
                   and str(shard.decisions()[0].get("task_id")) == "t-0007"
                   and decisions_path(root, "E").exists() is False))
    checks.append(("存活读数三态", shard.secretary_alive().get("checked") is True
                   and shard.secretary_alive().get("alive") is True
                   and shard.close().get("closed") is True
                   and shard.secretary_alive().get("alive") is False))
    loud = False
    try:
        s.handoff_add(to="F", summary="", body="")
    except ValueError:
        loud = True
    checks.append(("执笔失败必须报错（不静默放行）", loud))
    checks.append(("写集恒为 ∅", s.writes == frozenset()))
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())

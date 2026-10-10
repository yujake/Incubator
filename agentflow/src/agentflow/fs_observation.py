"""文件观察台账：没读过就不许改（DSH `dsh-fs-observation-policy` 的搬运）。

## 为什么有它（业主 2026-10-10 裁定 9甲）

`fs.write` 今天没有"你读过它吗"这一格，于是静默覆盖一个从没看过的文件是允许的 ——
而那是本文具面上唯一"代价不可逆"的坏法。DSH 那侧把它做成一条强制判据，
本模块就是那条判据搬过来之后的样子（业主的方法指示：「多搬运代码然后改，少自己从零写」）。

## 搬的是什么（逐条对着 `dsh-fs-observation-policy/lib/index.js` 与 `dsh-fs-local/lib/index.js`）

- 架构照搬：DSH 的策略层不持有服务、也不做 I/O，它只是"一张表 + 三个入口"
  （`POL:85-95`），原子的版本核对由 provider 做（`FSL:821-857`）。本模块是纯状态机；
  观察由 `fs_read`/`fs_write`/`fs_edit` 登记，核对由 `fs_write`/`fs_edit` 自己做。
  我们没有事件总线，所以不发明 policy 服务 —— 直接同步调用（DSH 的三个事件在这里退化成三个方法）。
- 三个状态（判据是"条目在不在" + `kind`，`POL:19-20`、`:32-34`）：
  S0 未观察（没有条目）/ S1 确认缺失（`absent`）/ S2 存在（`present` + 版本）。
- 版本令牌是 stat 元组，不是摘要（逐字照 `FSL:142-143`）：
  `dev:ino:size:mtime_ns:ctime_ns`。DSH 这条路上没有任何 digest；
  它被明确定义为不透明的（`MUST NOT interpret`，`FST:29-36`），所以它既不进模型可见文本，
  也不进工具的 `returns=` 声明。
- 两个意图（`POL:51-58`、`:64-70`）：
  `write` ⇒ 见过 S2 就"按版本替换"，否则（S0 / S1 / 没有 owner）"缺失才创建"；
  `edit` ⇒ 没有 owner 或 S0 ⇒ 拒、S1 ⇒ 拒（不存在）、S2 ⇒ 给出该版本作依据。
- owner：DSH 用 `actor?.agent?.session`（`POL:29-31`）；我们用它取
  `(current_caller_role(), current_task_id())`。两者都空 ⇒ 没有 owner ⇒
  状态写入被丢弃（`POL:73-74`）+ 编辑一律拒（`POL:67`）—— 这个分支是照搬的，不是遗漏。
- 两个 `NOT_OBSERVED` 出处必须归一化：DSH 的 policy 层文案与 provider 层文案不同，
  工具层再把两者改写成同一句给模型看（`TFS:547`）；陈旧那一档则是
  "保留 provider 的理由 + 追加一句补救"（`TFS:548`）。
- 成功之后要重新观察"写完之后"的版本（写后重新 stat，`FSL:831`/`:850`/`:860-862`）——
  否则同一步里"写 → 再写"会被自己拒掉。
- 只在这三处登记观察：读成功、写成功、改成功（DSH 只在 `TFS:276,430,657,810,1098` 五处 emit）。
  `stat` / `list` / `search` 不登记（`README:128`：「直接读不走 read 工具的，仍然是未观察」）。

## 一处刻意的不逐字（如实登记）

DSH 的文案是英文，我们按本仓的中文口径改写（结构、两个受控码、破折号与"再试一次"的补救句照搬）。
理由：本工具面其余文案都是中文，混一套英文会让模型在同一份结果里看到两种语气；
判据钉的是结构与两个码，不是那串英文字母。

## 与 DSH 的一处已知差异（不是遗漏）

DSH 的 provider 用"按 targetKey 的 FIFO 锁"串行化"stat → 比对 → 写"（`FSL:716-736`），
所以并发写是"一个赢、其余看到陈旧"。我们的 `_atomic_write_bytes` 没有那把锁 ⇒
同进程内两个并发写可以同时通过版本核对（TOCTOU；跨进程也一样，观察表是进程内的）。
这一格本轮不做：`fs_edit` 既有的 `sha256` 参数仍在（第二道更强的闸），
而并发写同一文件在本框架里不是当前形态（一次一个委托）。要补时照 `FSL:726-736` 搬。
"""  # noqa: R001 —— 依赖为纯 stdlib

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: 观察的两档（逐字照 `FST:42-47` 的 `present` / `absent`）。
OBS_PRESENT = "present"
OBS_ABSENT = "absent"

#: 受控码：与 DSH 的 `FS_NOT_OBSERVED` / `FS_STALE_VERSION` / `FS_NOT_FOUND` 一一对应。
#: 它们进 `ToolResult.meta["kind"]`（机器可路由的那一半），文案只给人/模型读。
CODE_NOT_OBSERVED = "not_observed"
CODE_STALE_VERSION = "stale_version"
CODE_NOT_FOUND = "not_found"


def version_of(st: os.stat_result) -> str:
    """一个文件此刻的版本令牌（逐字照 `FSL:142-143` 的拼法）。

    为什么是 stat 元组而不是内容哈希：① O(1)，不需要把文件读第二遍；
    ② 不受读取上限影响（DSH 那条路上大文件照样能被授权）；③ 不透明 ⇒ 不会被下游当数据解析。
    代价（照抄 DSH 的语义）：内容相同的重写也会让版本变化（size/mtime/ctime 会动）。
    """
    return f"{st.st_dev}:{st.st_ino}:{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}"


def version_of_path(target: Path) -> str:
    """盘上此刻的版本；文件不在 ⇒ 空串（调用方按三态处置，不许把它当成一个正常版本）。"""
    try:
        return version_of(os.stat(target))
    except OSError:
        return ""


#: 不在任何委托里时用的那个桶。为什么不是照 DSH 的"没有 owner 就丢弃"（`POL:73-74`）：
#: 我们的工具面有"委托之外"的合法调用者 —— 模块自检、发布门、`cli` 直调、以及本批的判据 ——
#: 而 DSH 那条路上没有这种路径（它的工具只从 agent 的 exec 里进）。
#: 丢弃会让这些调用者连"先读后改"都做不到，那不是本裁定要的（要的是"没读过不许改"）。
#: 所以退化成一个桶：隔离性照旧（不同 owner 之间互不可见），只是"没有身份的调用者"共用一格。
DIRECT_OWNER: tuple[str, str] = ("", "")


def current_owner() -> tuple[str, str]:
    """这一趟工具调用属于谁：`(角色, 委托号)`；不在委托里 ⇒ `DIRECT_OWNER` 那一格。

    为什么不用 `FsContext.actor`：那是 `register()` 时定死的常量（一次装配一个值），
    而 DSH 的 owner 是每次调用的（它拿 `exec` 上的 agent）。我们的对应物是
    `conductor.calling_as(...)` 挂进 ContextVar 的那两个值 —— `agent_loop` 已经把每次工具调用
    包在里面了。不用 `role` 单独当 owner：同角色的并发委托会互相串味。
    """
    from . import conductor as C  # 延迟 import：本模块被 tools 包引用，模块级 import 会成环

    return (C.current_caller_role(), C.current_task_id())


@dataclass(frozen=True)
class Observation:
    """一条观察：`present` 带版本，`absent` 不带（S1 的信息量就是"我确认过它不在"）。"""

    kind: str
    version: str = ""


class ObservationRefusal(Exception):
    """一次"按权限拒"（不是故障）：调用方把它翻成 `ToolResult.fail(kind=code)`。

    为什么用异常而不是返回三态：闸门有两个调用点、判定分支有四种，
    用返回值会让每个调用点各写一遍 if；这里是判据，不是业务结果。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ObservedGate:
    """观察台账：`{owner: {target_key: Observation}}`（照 `POL:15-76` 的结构）。"""

    def __init__(self) -> None:
        self._by_owner: dict[tuple[str, str], dict[str, Observation]] = {}

    # ---------------------------------------------------------------- 表
    def get(self, owner: tuple[str, str] | None, key: str) -> Observation | None:
        """这个 owner 对这个目标有没有观察（`None` = S0 未观察，是一个正常状态）。"""
        if owner is None:
            return None
        return self._by_owner.get(owner, {}).get(key)

    def observe(self, owner: tuple[str, str] | None, key: str, obs: Observation) -> None:
        """登记一条观察（没有 owner ⇒ 静默丢弃，逐字照 `POL:73-74` 的 `if (owner)`）。"""
        self.set(owner, key, obs)

    def set(self, owner: tuple[str, str] | None, key: str, obs: Observation) -> None:
        """登记一条观察（没有 owner ⇒ 静默丢弃，照 DSH）。"""
        if owner is None:
            return
        self._by_owner.setdefault(owner, {})[key] = obs

    def clear(self) -> None:
        """清空整张表（照 `POL:87-89` 的 `gate.clear()`）。

        调用点：装配一个新注册表时（`fs_tools.register`）、以及需要"恢复的会话从零开始"时。
        不持久化是刻意的：DSH 明确"恢复的会话必须重读"（`README:12/82`）。
        """
        self._by_owner.clear()

    # ---------------------------------------------------------------- 两个意图
    def write_intent(self, owner: tuple[str, str] | None, key: str) -> tuple[str, str]:
        """`write` 的意图：`("replace_if_version", 版本)` 或 `("create_if_absent", "")`。

        逐字照 `POL:51-58`：只有见过 S2 才算"替换"；S0、S1、以及"没有 owner"三种情形
        都落进"缺失才创建"（于是"覆盖一个已存在的文件"会被 provider 那一步拒掉）。
        """
        prior = self.get(owner, key)
        if prior is not None and prior.kind == OBS_PRESENT:
            return ("replace_if_version", prior.version)
        return ("create_if_absent", "")

    def edit_intent(self, owner: tuple[str, str] | None, key: str, rel: str) -> str:
        """`edit` 的意图：返回可依据的版本；不该改就抛 `ObservationRefusal`。

        逐字照 `POL:64-70` 的三支：没 owner / S0 ⇒ `not_observed`；S1 ⇒ `not_found`；S2 ⇒ 给版本。
        """
        prior = self.get(owner, key)
        if owner is None or prior is None:
            raise ObservationRefusal(CODE_NOT_OBSERVED, remedy_not_observed(rel))
        if prior.kind == OBS_ABSENT:
            raise ObservationRefusal(CODE_NOT_FOUND, f'不能改 "{rel}"：它不存在'
                                                      "（你读到的是「它不在」，不是「它是空的」）")
        return prior.version

    def note_absent(self, owner: tuple[str, str] | None, target: Path) -> None:
        """记一条 S1（"我确认它不在"）—— 照 `TFS:276`：先记、再抛/再拒。"""
        self.set(owner, str(target), Observation(OBS_ABSENT))

    def note_present(self, owner: tuple[str, str] | None, target: Path) -> None:
        """记一条 S2，版本取此刻盘上的（写/改之后要重新取，照 `FSL:860-862`）。"""
        version = version_of_path(target)
        if version:
            self.set(owner, str(target), Observation(OBS_PRESENT, version))
        else:
            # 写完却 stat 不到（被旁路删了）：如实记 absent，而不是留一个假版本。
            self.note_absent(owner, target)


def remedy_not_observed(rel: str) -> str:
    """`NOT_OBSERVED` 的归一化文案（两个出处共用这一句，照 `TFS:547`）。"""
    return (f'不能改 "{rel}"：这个文件还没被读过 —— 先读一次，再重试'
            "（这一条防的是「静默覆盖一个你从没看过的文件」）")


def remedy_stale(message: str) -> str:
    """`STALE_VERSION` 的补救句：保留 provider 的理由 + 追加"重读再试"（照 `TFS:548`）。"""
    return f"{message} —— 重新读一遍，再重试"


#: 全进程一张表（DSH 是 per-session 的 WeakMap；我们的进程边界就是"一趟"的边界，
#: 而 `sessions`/`run_role` 每趟新建 AgentLoop ⇒ 语义等价）。不持久化。
_GATE = ObservedGate()


def observed_gate() -> ObservedGate:
    """取那张表（唯一入口；`fs_tools` 与判据都从这里拿，不各建一张）。

    名字里带 `observed_` 是 R003 逼出来的：裸叫 `gate` 会与 `deliver.gate` 撞公开名，
    而那条规则问的是"同名的是不是同一件事"——这两件不是（一个是交付闸门、一个是观察台账），
    所以改的是名字，不是判据。
    """
    return _GATE


def clear() -> None:
    """清空观察表（新装配 / 新会话边界调它）。"""
    _GATE.clear()


def stat_version(target: Path) -> str:
    """`version_of_path` 的别名出口（判据与工具层都用这一处，避免两套拼法）。"""
    return version_of_path(target)


__all__ = [
    "CODE_NOT_FOUND",
    "CODE_NOT_OBSERVED",
    "CODE_STALE_VERSION",
    "OBS_ABSENT",
    "OBS_PRESENT",
    "Observation",
    "ObservationRefusal",
    "ObservedGate",
    "clear",
    "current_owner",
    "observed_gate",
    "remedy_not_observed",
    "remedy_stale",
    "stat_version",
    "version_of",
    "version_of_path",
]

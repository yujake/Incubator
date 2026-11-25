# -*- coding: utf-8 -*-
"""进工作区 + 用户对 M 说话的唯一实现（CLI 与网页共用）。

## 为什么要有这一层

业主 2026-11-25 的口径只有一句：「用户发话起真机，以及用户插话，这两件事都是用户对
M 说话，实现上不该有区别。」此前两条入口各写一套：CLI 的 `start --task` 直接把任
务交给 `run-agent M`，网页的 `/api/run` 与 `/api/task` 各自判"要不要起、要不要投"。
两份实现漂移的形态是：网页把话投进收件箱了、CLI 又起一趟，或者反过来 —— 而两个主控
抢同一个工作区不会有任何一层报错。

这一层只回答两个问题：

- :func:`ensure_workspace`：这个目录能不能当工作区用（该 init 就 init；本框架自己写
  在根上的那几个文件放行，别的外来条目仍然拒，并给一条照着改的说明）；
- :func:`speak`：这句话要不要变成一趟新的运行 —— 台账里有正在跑的 M ⇒ 投进它的收件
  箱（与智能体之间的留言同一条投递）；没有 ⇒ 用这句话起一趟。

CLI 的 `cli.cmd_start` 与网页的 `webui.writes.handle_start_run` /
`handle_interject` 都只调 :func:`speak`。判据
`tests/test_cli_speaks_to_conductor.py` 用打桩断言两侧走的是同一个函数，不靠肉眼。

## 起一趟由谁执行

:func:`speak` 不自己起进程：它把"起一趟"交给调用方给的 `launch(argv) -> Launch`。
网页交的是 detached 子进程（`webui.writes._spawn_detached`），CLI 交的是同进程的
`cli._run_spec`（这样 `--resume` / 预算耗尽 / 用户叫停那几档的退出码仍是原来那三态）。
两边不同的只有"进程怎么起"；"要不要起、起什么"是同一份判断。

## 为什么不是把 `web-actions.jsonl` 加进 `store` 的白名单

`store.py` 的 `_WORKSPACE_ROOT_ENTRIES` 是禁改区（FC-27 的 schema-migration）里那道
「别在别人的目录里凭空建库」的守卫。网页自己在根上写的 `web-actions.jsonl` 是白名单
之外的正常形态，但放宽 `store` 的守卫等于拆掉那道判据本身。所以这里用 `store` 自己
明写的出口：先落 `.agentflow-workspace`（`store.init` 认它），再 init；列出根上哪几
个文件是本框架自己写的，只是决定"要不要落那个标记"，守卫本体一个字没改。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from . import schema as S
from . import tty
from .budget import REGISTER_NAME
from .stopctl import STOP_FILE_NAME
from .store import Store, StoreError

#: 工作区标记文件名：`store._foreign_dir_guard_should_refuse` 的白名单出口之一
#: （`projects.classify` 也认它）。
WORKSPACE_MARKER = ".agentflow-workspace"

#: 「这个目录里已经有用户的投料，仍然按工作区初始化」那条开关。
#: 拒绝文案里教的就是它（`init_workspace` 的 except 分支）。
ALLOW_FOREIGN_FLAG = "--allow-foreign-entries"


def _own_root_files() -> frozenset[str]:
    """工作区根上"本框架自己写的"那几个文件（出现在未 init 的目录里也要放行）。

    只列文件、不列目录：目录那份白名单的真身是 `store._WORKSPACE_ROOT_ENTRIES`，
    在这里再抄一遍就是第二份口径。这三个文件都不在那张白名单里，而它们确实是本框架
    落的（`webui.audit` 的操作台账 / `budget` 的寄存器 / `stopctl` 的停机开关）。
    名字从各自的定义处取，不在本文件写第二份字符串。

    为什么是函数而不是模块常量：`webui` 包在导入期会 `from ..cli import ...`，而
    `cli` 在导入期会导入本模块 —— 顶层取 `webui.audit` 会绕成一个环。这里按调用期取。
    """
    from .webui import audit

    return frozenset({audit.LEDGER_NAME, REGISTER_NAME, STOP_FILE_NAME})


def _foreign_entries(root: Path) -> list[str]:
    """root 里不属于本框架的条目名。

    白名单从 `store._WORKSPACE_ROOT_ENTRIES` 读（唯一一份），不在这里再抄一遍 ——
    两份白名单的漂移形态是"CLI 认为可以、`Store.init()` 认为不可以"，
    而判据只会照着其中一份红。
    """
    from .store import _WORKSPACE_ROOT_ENTRIES

    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.name not in _WORKSPACE_ROOT_ENTRIES)


def _marker_text(root: Path, *, by: str) -> str:
    """标记文件的内容：谁落的、什么时候落的、认了几个外来条目。"""
    foreign = _foreign_entries(root)
    lines = ["agentflow workspace",
             f"created_at={S.now_iso()}",
             f"created_by={by}",
             f"accepted_foreign_entries={len(foreign)}"]
    if foreign:
        head = ", ".join(foreign[:10]) + (" ..." if len(foreign) > 10 else "")
        lines.append(f"accepted_entries={head}")
    return "\n".join(lines) + "\n"


def init_workspace(st: Store, root: Path, *, allow_foreign_entries: bool,
                   cmd: str, force: bool = False,
                   seed_literature: bool = False) -> int:
    """`Store.init()` 的 CLI 外壳：把 `R-32` 那一档的拒绝翻成「照着改」的话。

    为什么要有这一层：`R-32` 的判据本身
    是对的（它挡的是"在别人的目录里凭空建库"），缺的是一条
    「我认这个目录，里面那些文件是我自己投的料」的出口。`--force` 不是那条出口：
    它是"清空重建"。所以这里补第四条路 —— 带 `allow_foreign_entries` 时先落
    `.agentflow-workspace`（`store.init` 自己明写的白名单出口），再照常 init；
    判据本体一个字没改（它在禁改区 `schema-migration` 里）。

    `seed_literature=True`（默认关）只对"这一次真的是新建"生效：`data/` 已经在了就是
    热启动，不投。投放只写输入区 `reference/`（含其中的 `SEED-README.md`），不写任何
    `data/*.json`，也不往已登记书架 `library/` 里放文件 —— 见 :mod:`agentflow.seedinject`。

    返回退出码：0 = 建成了；2 = 拒绝了（文案里教那条开关）或没查成。
    两个值都有调用方（`main` 的 StoreError 那一档也是 2），所以不许折成布尔。
    """
    fresh = not (Path(root) / "data").exists()
    if allow_foreign_entries:
        marker = Path(root) / WORKSPACE_MARKER
        if not marker.exists():
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(_marker_text(Path(root), by=f"cli {cmd} {ALLOW_FOREIGN_FLAG}"),
                              encoding="utf-8", newline="\n")
    try:
        st.init(force=force)
    except StoreError as e:
        # 原样打出判据的话（它是"为什么拒"的唯一出处），再补一句"照着改"。
        # 那句只在"拒绝的理由确实是外来条目"时才打：root 是个文件、或者写者锁超时
        # 那些形态教这条开关会把人教错方向。
        print(f"[{cmd}] {e}", file=sys.stderr)
        foreign = _foreign_entries(Path(root))
        if foreign:
            print(tty.paint(
                f"[{cmd}] {Path(root)} 里那 {len(foreign)} 个条目要么是用户自己投的料"
                f"（例如一篇 PDF）、要么是这个目录本来就不干净。若它就是要用的工作区："
                f"加 {ALLOW_FOREIGN_FLAG} 再跑一次 —— 它会先落 "
                f"{WORKSPACE_MARKER}（`store` 的白名单出口），再按工作区初始化；"
                f"那些文件不删、不改，只是从此算这个工作区的条目。",
                "grey"), file=sys.stderr)
        return 2
    if seed_literature:
        if not fresh:
            print(tty.paint(
                f"[{cmd}] 这里已经是工作区（data/ 在盘上）⇒ 不投种子："
                "种子只在新建工作区时投，热启动不重复投。", "grey"), file=sys.stderr)
        else:
            from . import seedinject as SI

            got = SI.seed_workspace(Path(root))
            _report_seed_landing(cmd, got)
    return 0


def _report_seed_landing(cmd: str, got: dict) -> None:
    """把一次种子投放的读数印成一行人话（只印读数，不改任何退出码）。"""
    if got.get("problem"):
        print(tty.paint(
            f"[{cmd}] 种子文献没投成：{got['problem']}", "yellow"), file=sys.stderr)
        return
    print(tty.paint(
        f"[{cmd}] 种子文献：{got.get('copied', 0)} 份投到 {got.get('destination')}"
        f"（输入区，未入库、未判收；见 {got.get('marker')}）", "grey"))


# ---------------------------------------------------------------- 进工作区

@dataclass(frozen=True)
class Prep:
    """一次"进工作区"的结论：`code` 非 0 时 `message` 是那句照着改的说明。"""

    code: int
    message: str = ""


def ensure_workspace(root: Path, *, cmd: str, allow_foreign_entries: bool = False,
                     seed_literature: bool = False) -> Prep:
    """把 root 准备成可用的工作区（幂等：data/ 已在就什么都不做）。

    判据顺序：

    1. `data/` 已在 ⇒ 0（热启动 / 半成品工作区都按已有工作区补表，`Store.init` 自己
       负责补缺失的表）；
    2. 根上只有本框架自己的文件（见 :func:`_own_root_files`）⇒ 落标记 + init；
    3. 根上还有别的条目且调用方没给 `--allow-foreign-entries` ⇒ 2 + 一句说明，一个字节
       都不写；
    4. 其余 ⇒ `init_workspace`（它自己 fail-closed）。

    为什么 `data/` 已在就直接返回、不先跑一遍外来条目检查：`store.init` 的守卫本来就
    只在"没有 data/、没有标记、又不是空目录"时拒；有 data/ 的目录它一律按工作区补表。
    这里提前返回只是不重复那道判据，不改它的宽严。
    """
    root = Path(root).resolve()
    if (root / "data").is_dir():
        return Prep(0)
    entries = _foreign_entries(root)
    ours = _own_root_files()
    foreign = [name for name in entries if name not in ours]
    if foreign and not allow_foreign_entries:
        head = "、".join(foreign[:5]) + (" …" if len(foreign) > 5 else "")
        return Prep(2, (
            f"[{cmd}] 没查成：{root} 里那 {len(foreign)} 个条目不属于本框架（{head}）—— "
            "在别人的目录里凭空建出整套 data/ 与 library/ 是不可逆的，所以先停在这里。"
            f"若它就是要用的工作区：加 {ALLOW_FOREIGN_FLAG} 再跑一次（会先落 "
            f"{WORKSPACE_MARKER}，再把该目录按工作区初始化；那些文件不删、不改，"
            "只是从此算这个工作区的条目）。"
            "若你只是想换个落点：给 --project <名字>（项目工作区），或 --root <空目录>；"
            "只想先看看会发生什么就加 --dry-run。"))
    # 根上有我们自己的文件（例如网页的 web-actions.jsonl）时也要落标记：
    # `store.init` 的白名单出口认它，否则 `web-actions.jsonl` 会被当成外来条目。
    code = init_workspace(Store(root), root,
                          allow_foreign_entries=bool(allow_foreign_entries or entries),
                          cmd=cmd, seed_literature=seed_literature)
    if code != 0:
        return Prep(2, f"[{cmd}] 没查成：{root} 这个目录没能按工作区初始化（见上面一行）")
    return Prep(0)


# ---------------------------------------------------------------- 用户对 M 说话

@dataclass(frozen=True)
class Launch:
    """一次"起一趟"的返回值（进程怎么起由调用方决定，形状在这里统一）。

    `code` 是起跑那一趟自己的退出码（网页起的是 detached 进程、当场只能给 0；
    CLI 起的是同进程的执行体，给的是 0 / 1 / 2 / 3 / 4 / 5 那六档）。
    """

    code: int = 0
    pid: int = 0
    log: str = ""
    detail: str = ""


@dataclass(frozen=True)
class Speech:
    """一次"对 M 说话"的结论。`action` 四档：interjected / started / planned / refused。

    `code` 是"这一条入口做成没做成"（0 = 投成或起成；2 = 没查成）；
    `start_code` 只有 `started` 那一档有意义（那一趟自己的退出码）。
    """

    action: str
    code: int
    message: str
    origin: str = ""
    owner: str = ""
    interjection_id: str = ""
    argv: tuple[str, ...] = ()
    pid: int = 0
    log: str = ""
    start_code: int = 0


def conductor_running(root: Path) -> str:
    """台账里正在跑的主控台账号（空串 = 没在跑 / 读不成）。

    与 :func:`agent_loop._deliver_interjection_to_inbox` 读的是同一张 `tasks` 表、
    同一个判据（`role == M` 且 `status == running`）：一处判"有没有收件箱"，
    这里判"要不要另起一趟"，两处必须同源。读不成按"没在跑"处理，由调用方如实说。
    """
    try:
        rows = Store(root).rows("tasks")
    except Exception:  # noqa: BLE001 - 读不成 = 不知道，按"没在跑"交给下一层
        return ""
    owner = ""
    for row in rows:
        if (str(row.get("role") or "") == S.CONDUCTOR_ROLE
                and str(row.get("status") or "") == "running"):
            owner = str(row.get("task_id") or "")
    return owner


def run_argv(root: Path, task: str, *, sid: str = "",
             resume: bool = False) -> list[str]:
    """起一趟要跑的那条命令行（网页 detached 子进程用；判据也拿它比对）。

    `--allow-foreign-entries` 在 argv 里是刻意的：网页自己会在这个目录里写
    `web-actions.jsonl`，对 `run-agent` 来说那就是一个外来条目；不放行的话空目录上
    的网页起跑永远失败。CLI 那一侧由 :func:`ensure_workspace` 先处理同一个问题。
    """
    argv = [sys.executable, "-B", "-m", "agentflow", "--root", str(root),
            "run-agent", S.CONDUCTOR_ROLE, "--task", task, "--subagents",
            ALLOW_FOREIGN_FLAG]
    if sid.strip():
        argv += ["--sid", sid.strip()]
    if resume:
        argv.append("--resume")
    return argv


def speak(root: Path, body: str, *, sid: str = "", subject: str = "用户指令",
          sender: str | None = None, resume: bool = False, dry_run: bool = False,
          origin: str = "", launch=None, allow_foreign_entries: bool = False,
          seed_literature: bool = False) -> Speech:
    """用户对 M 说话：M 在跑就投进它收件箱，没在跑就用这句话起一趟。

    参数就是两条入口的全部差异，差异只许落在这里：

    - `subject` / `sid`：网页 `/api/task` 的插话主题与"哪一段会话"，`/api/run` 的
      "用户指令"；CLI 的 `start` 用"用户指令"；
    - `resume`：续跑是"接着那一段"，不是插话；M 正好在跑时这是一个矛盾，
      拒绝（不另起第二趟），要说话就不带 `--resume` 再发一次；
    - `dry_run`：只回 argv，一个字节都不写、也不起进程；
    - `launch`：网页是 detached 子进程，CLI 是同进程的执行体；
    - `allow_foreign_entries`：网页一直按"这个目录是本页面的工作区"放行自己的文件
      （与它起跑 argv 里的同名开关同义）；CLI 默认 stricter，用户显式给了才放行。

    返回 :class:`Speech`。起一趟时 `launch` 抛出的异常不吞：那是"没起成"，
    由调用方按自己的状态码口径如实报（网页 500 / CLI 由执行体自己给）。
    """
    from . import agent_loop as AL
    from . import userio as U

    root = Path(root).resolve()
    body = str(body or "")
    sender = U.USER if sender is None else str(sender)
    if not dry_run:
        prep = ensure_workspace(root, cmd=("web" if origin == "web" else "start"),
                                allow_foreign_entries=allow_foreign_entries,
                                seed_literature=seed_literature)
        if prep.code != 0:
            return Speech("refused", 2, prep.message, origin=origin)
    owner = "" if dry_run else conductor_running(root)
    if owner and resume:
        return Speech("refused", 2, (
            f"主控正在跑（{owner}）：--resume 是给闲着的那一段会话用的 —— "
            "要接着对它说话就不带 --resume 再发一次（这句话会投进它的收件箱，"
            "不另起第二趟）"), origin=origin, owner=owner)
    if owner:
        iid, problem = AL.send_interjection(root, sender=sender, subject=subject,
                                            body=body, sid=sid or None)
        if problem:
            return Speech("refused", 2, f"没投进去：{problem}",
                          origin=origin, owner=owner)
        return Speech("interjected", 0, (
            f"主控已经在跑（{owner}）：这句话已投进它的收件箱（{iid}），没有另起一趟"),
            origin=origin, owner=owner, interjection_id=iid)
    argv = tuple(run_argv(root, body, sid=sid, resume=resume))
    if dry_run:
        return Speech("planned", 0, "试运行：没有起任何进程", origin=origin, argv=argv)
    if launch is None:
        return Speech("refused", 2,
                      "没查成：这条入口没有给「起一趟」的实现（内部错）",
                      origin=origin, argv=argv)
    got = launch(list(argv))
    return Speech("started", 0, got.detail or "主控没在跑 ⇒ 已用这句话起一趟",
                  origin=origin, argv=argv, pid=got.pid, log=got.log,
                  start_code=int(got.code))

# -*- coding: utf-8 -*-
"""秘书的实例台账读写（一实例一片，从 secretary.py 的 U13 逐字搬出）。

我保证哪条不变式：一个实例一片台账、一片只有一个写者；`bind_task` 是 `task_id` 的唯一写点。

## 为什么它能单独成文件（依赖方向）

它只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from pathlib import Path
import json

from .secretary_ledger import (  # noqa: F401 — 这些名字由 secretary_ledger 定义
    SECRETARY_DIR,
    append_jsonl,
    append_jsonl_stamped,
    decisions_path,
)

from .secretary_time import (  # noqa: F401 — 这些名字由 secretary_time 定义
    _now_iso,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    KIND_DECISION,
)


class SessionMixin:
    """实例台账读写（一实例一片）（从 secretary.py 搬出的混入类）。"""

    def bind_task(self, task_id: str, *, mark_alive: bool = True) -> None:
        """把这一名秘书绑到它服务的实例上。绑上之后台账分片。

        为什么必须有这一步：秘书的台账若只有角色维度
        （`out/secretary/<role>.jsonl`），同角色的并发实例（`summon_many` 的多 `instance`）
        会写进同一个文件 —— 读的人分不出哪一行是哪一个代理写的。
        绑定之后每一实例一片（`<role>-<task_id>.jsonl`），一个写者一片。
        同时写一份存活标记（`secretary_alive` 读它）——"与它同生同死"的第一半。

        `mark_alive=False` 是"代表别人"那一档（全仓只有 :meth:`_peer_secretary` 用）：
        转发链的下一跳不是"这一趟循环"，替它写标记等于伪造"它活着"（标记的语义见
        :meth:`secretary_alive`：标记在 = 绑过，pid 活着 = 真的在跑）。这一档只拿分片，
        不碰存活标记；它是 `bind_task` 的一个分支，不是第二个写点 ——
        `_task_id` 全仓只有这一处能写。
        """
        self._task_id = str(task_id or "")
        if not self._task_id or not mark_alive:
            return
        try:
            path = self.decisions_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            alive = self.alive_path()
            alive.write_text(json.dumps({"role": self.role, "task_id": self.task_id,
                                         "pid": __import__("os").getpid(),
                                         "at": _now_iso()}, ensure_ascii=False, default=str) + "\n",
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
                      error: str = "", judge: Mapping[str, Any] | None = None,
                      proposal: str | None = None,
                      fingerprint: str = "") -> dict[str, Any]:
        """追加一行台账（`draft/55` §5.3 的字段表）。

        原文与加工后并列（`before` / `after`）：只留结论会让复核无从下手 —— "过程"是这一层唯一能自证的东西。
        `changes`（S1g）：逐格写"洗了什么"（`[{"field","from","to","why"}]`）。只留 `before`/`after` 两份全文也能
        diff 出来，但"哪几格是秘书动的"必须一眼可读 —— 否则"模型写错了"与"秘书替它补对了"在纸上长得一样
        （`draft/90` §1.2）。`proposal`（两段式）：三态，不许折平 ——
        | 值 | 这一行是什么 | `proposal_id` 那一格 |
        |---|---|---|
        | `None`（默认） | 普通台账行（老行为逐字不变，不多一个键） | 不写 |
        | `""` | 一条新请示 ⇒ 编号由本秘书在锁内发（与这一行的 `seq` 同源） | `W-<role>-<task>-<seq>` |
        | `"<id>"` | 确认/拒绝那一行 ⇒ 指向原来那条请示 | 原样记 `"<id>"` |
        为什么编号必须在这里发（而不是调用方拼）：见 :func:`_append_locked` 的 docstring —— 拼号都在锁外取值，
        并发下重号的请示意味着"接受 A 的编号、执行 B 的洗"。`fingerprint`（两段式）：这一行是对哪一份载荷发的
        （12 hex），它让"接受/拒绝"那一步在台账里就能核"这个编号是不是对这份载荷发的" —— 不给的话，接受方可以
        拿 A 的编号去确认 B 的载荷。空串 = 不写这一格（老行逐字不变）。写入走 `append_jsonl`（S1m）：锁内算
        `seq`、进程内 + 跨进程两层锁；旧写法（先读全表算 `seq`、再裸 `open("a")`）在并发下会重号（D107）。
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
        if fingerprint:
            rec["proposal_fingerprint"] = str(fingerprint)
        path = self.decisions_path()
        resolved = str(proposal or "")
        if proposal == "":
            # 新请示：编号在锁内发（与写这一行同一个临界区）⇒ 发号与落行不可能分叉。
            ok, problem, resolved = append_jsonl_stamped(
                path, rec, field="proposal_id", prefix=self.proposal_prefix())
            if resolved:
                rec["proposal_id"] = resolved
            else:
                self._log(f"秘书台账没发成号（请示没有编号）：{problem}")
        else:
            if resolved:
                rec["proposal_id"] = resolved
            ok, problem = append_jsonl(path, rec)
        if not ok:
            # 台账写不成不许带走秘书的判断（fail-open 的第一层：留痕是手段不是目的）。
            # 但也不静默：日志口子与返回值两条路都留下这件事。
            self._log(f"秘书台账没写成：{problem}")
            rec["ledger_problem"] = problem
            if resolved:
                rec["proposal_id"] = resolved
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

    def _log(self, message: str) -> None:
        if self.log is None:
            return
        try:
            self.log(message)
        except Exception:  # noqa: BLE001 - 日志口子坏了不该带走秘书的判断
            pass


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

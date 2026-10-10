# -- coding: utf-8 --
"""停机的唯一实现（`draft/37` §128）：优雅停止与强制停止，以及"把子进程一起停掉"。

## 为什么要有这一个模块

用户口径（2026-10-04）：

> 优雅停止还要提醒那些 Agent 把发起的进程一起停掉，还要写个强制停止是直接杀掉
> 优雅停止和强制停止应该是主控 M 的 tool

在这之前，"停机"这件事散在三处、且「没有一处管得住子进程」：

- `conductor.stop`（工具，M 专用）：优雅停止 —— 喊停 → 有界收尾 → 合成终态 → 落续跑简报，
  但它「不停 M 自己的步循环」，也「不管 E 起的那条实验子进程」（真机实测：一个 600 s 的
  枚举实验会继续把这 600 s 跑完）；
- `--stop-file`：单趟 `run-agent` 此前根本不看它（§125 已修：步循环顶上看一眼）；
- 多轮自主跑：`autonomy._stop_before_round` 在每轮之间看一次。

现在三处共用本模块的「一个停机文件 + 一份子进程登记」：

```text
<工作区>/.agentflow-stop           停机开关（JSON：谁在什么时候、因为什么、是不是强制）
<工作区>/runs/<role>-<sid>.pid     这一趟起的进程（pid + 启动时间 + 角色 + sid）
```

## 三态纪律（这个模块的每一格都要能分开）

| 状态 | 读数 |
|---|---|
| 没人叫停 | `stop_state()` 返回 `None`（不是 `{}`、不是"空文件"） |
| 叫停、优雅 | `{"force": false, "reason": …, "by": …}` |
| 叫停、强制 | `{"force": true, …}` —— 强制那条路会「先落记录再杀进程树」 |

## 子进程为什么要登记而不是"随父进程一起死"

在 Windows 上杀掉父进程「不会」带走子进程（真机实测：`job_kill` 之后 python 子进程照旧把
那一趟跑完，见 §127）。所以：① 起进程时登记 pid；② 强制停止时按登记逐个 `taskkill /T /F`
（`/T` 连子孙一起）；③ 优雅停止时把停机文件给子进程看见 —— E 的脚本等待循环每 0.2 s 看一次它。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

#: 停机开关的文件名（在工作区根下）。
STOP_FILE_NAME = ".agentflow-stop"
#: 子进程登记的目录（`<工作区>/runs/`）。
PID_DIR_NAME = "runs"
#: 停机开关缺省的理由码（与 `conductor` 的取消词表同源，见 `CANCEL_CODES`）。
DEFAULT_REASON = "user"


def stop_path(root: str | Path, explicit: str | Path | None = None) -> Path:
    """停机开关落在哪：显式给了就用它，否则 `<工作区>/.agentflow-stop`。"""
    if explicit:
        return Path(explicit)
    return Path(root) / STOP_FILE_NAME


# ====================================================================== 写路径上的可选钩子
#
# 与 `sessions.py` / `userio.py` 同一族（`sse.attach()` 把三个模块的钩子接成
# "发对应 kind 的事件"），同三条纪律：
#
# 1. 缺省 `None` ⇒ 既有行为逐字节不变；
# 2. 监听器是旁路：它坏掉不许把停机路径带坏（接住异常并记进 `stop_hook_problem()`，
#    不是静默吞掉 —— 三态纪律：不许把"没查成"折成"没发生"）；
# 3. 只有开关真的变了才通知 —— `created`（新写）与 `upgraded`（升级成强制）算变，
#    `existing`（盘上已有一把、这次什么都没改）与"没开关可撤"不算。
#    理由与 `request_stop_detail` 把"结局"单独返回是同一条：把"喊了一声但什么都没变"
#    也报成变化，读的人就分不出"谁真的叫停过"。
#
#: 停机开关变化后的监听器：`(root, action, payload) -> None`；
#: `action` 是 `"created"` / `"upgraded"` / `"cleared"` 三档，`payload` 是开关里那份内容
#: （`cleared` 时是那次撤掉之前读到的那一份，读不到就是 `{}`）。
_STOP_HOOK: "Callable[[Any, str, Mapping[str, Any]], None] | None" = None
#: 上一次监听器抛出的问题（空串 = 没出过问题）。
_STOP_HOOK_PROBLEM: str = ""


def set_stop_hook(hook: "Callable[[Any, str, Mapping[str, Any]], None] | None"
                  ) -> "Callable[[Any, str, Mapping[str, Any]], None] | None":
    """装上/撤掉"停机开关变化之后"的监听器；返回被替换掉的那一个。"""
    global _STOP_HOOK  # noqa: PLW0603 - 一个进程一个槽，与 sessions 那一族同形
    previous, _STOP_HOOK = _STOP_HOOK, hook
    return previous


def stop_hook_problem() -> str:
    """监听器上一次抛出的问题（空串 = 没出过问题）。"""
    return _STOP_HOOK_PROBLEM


def _notify_stop(root: str | Path, action: str,
                 payload: Mapping[str, Any]) -> None:
    """把"开关变了"交给监听器（没装 ⇒ 立刻返回）；接住异常并记一条读数。"""
    global _STOP_HOOK_PROBLEM  # noqa: PLW0603 - 只记最近一条
    hook = _STOP_HOOK
    if hook is None:
        return
    try:
        hook(root, action, payload)
    except Exception as exc:  # noqa: BLE001 - 旁路：见上面那一节的第 2 条
        _STOP_HOOK_PROBLEM = f"{type(exc).__name__}: {exc}"
    else:
        _STOP_HOOK_PROBLEM = ""


def request_stop_detail(root: str | Path, *, reason: str = DEFAULT_REASON, by: str = "user",
                        force: bool = False, sid: str | None = None,
                        explicit: str | Path | None = None,
                        root_task_id: str = "") -> tuple[dict[str, Any], str]:
    """写下停机开关，并回答"这把开关是谁的"（`draft/39` §3.11 D25）。

    返回 `(负载, 结局)`，结局三态：

    - `"created"` —— 这次调用新写了开关（调用方可以清）；
    - `"upgraded"` —— 盘上已有一把别人写的开关，这次只追加了 `force` 升级（不许清）；
    - `"existing"` —— 盘上已有的开关原样返回（这次什么都没改，不许清）。

    为什么要把"结局"与"负载"分开返回（而不是塞进负载）：负载是写进开关文件的内容，
    它是"谁在什么时候为什么叫停"的审计面；把调用方的结局塞进去会让下一次读它的人
    把"上一次是谁写的"与"这一次是谁在问"混起来。驱动器按这个结局决定要不要清：
    只有 `created` 才清（`3`/`4` 一律不动别人的痕迹）。

    ## `root_task_id`（S4，`draft/90` E7 / `draft/84` §2.2）：这把开关管哪一支

    缺省（空串）= 全工作区（老行为逐字不变）；给了台账里的一个实例号 ⇒ 只对
    那一支（它自己 + 它的子孙）生效 —— 于是"停 D 那一支"不必停掉整个工作区。

    只在给了的时候写这一格（与 S6-a 的 `from_task_id` 同一条纪律：恒为空的键会让
    "谁都没写"与"特意写了空"在记录上长得一样）。已有开关在场时先到先得
    （与 `reason` 同一口径）：升级只加 `force`，不改作用面 —— 否则"后来的人"能悄悄
    把一把子树开关变成全工作区开关。
    """
    path = stop_path(root, explicit)
    existing = read_stop(root, explicit=explicit)
    if existing is not None:
        # 幂等：理由取第一次那份。「但 `force` 可以升级」（`draft/37` §128）：
        # 先有人说了"优雅停"、随后用户要求"直接杀掉"，那次强制必须生效 ——
        # 否则"我现在就要它停"会被一个更早的软请求挡掉。升级只在 false→true 一个方向，
        # 并把"什么时候升级的"写进负载（可复核）。
        if force and not bool(existing.get("force")) and "unreadable" not in existing:
            upgraded = dict(existing)
            upgraded.update({"force": True, "escalated_at": _now_iso(),
                             "escalated_by": str(by or "user")})
            path.write_text(json.dumps(upgraded, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
            _notify_stop(root, "upgraded", upgraded)
            return upgraded, "upgraded"
        return existing, "existing"
    payload = {"reason": str(reason or DEFAULT_REASON), "by": str(by or "user"),
               "force": bool(force), "at": _now_iso(), "sid": str(sid or ""),
               "path": str(path)}
    if str(root_task_id or ""):
        payload["root_task_id"] = str(root_task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    _notify_stop(root, "created", payload)
    return payload, "created"


def stop_scope(state: Mapping[str, Any] | None) -> dict[str, Any]:
    """这把开关的作用面：`{"checked","scope","root_task_id","reason"}`。

    - `scope="all"`：全工作区（老行为；缺省那一档）；
    - `scope="subtree"`：只管 `root_task_id` 那一支（S4）；
    - `checked=False`：读不成（`state` 不是 Mapping）⇒ 判不了，不许折成"全工作区"
      （那会把一把子树开关变成全停）。
    """
    if not isinstance(state, Mapping):
        return {"checked": False, "scope": "", "root_task_id": "",
                "reason": "没有开关负载 ⇒ 作用面判不了"}
    rid = str(state.get("root_task_id") or "")
    return {"checked": True, "scope": "subtree" if rid else "all", "root_task_id": rid,
            "reason": ""}


# ============================================================ 单个子代理的中断信号（S-H）
#
# 为什么它不与上面那把开关共用一个文件（这是一处刻意的落位差异，理由要说清）：
# 工作区那把开关的语义是"先到先得、后来者原样返回 existing"
# （`request_stop_detail` 的注释逐字：「第一次写下的那份不许被后来的请求覆盖」）。
# 一个文件只能装一个目标 ⇒ 第二个被叫停的孩子会被读成 `existing` 而静默不停，
# 那正是"报告没写成"与"不用报告"长得一样的那一族。
# 所以"停某一个孩子"是一份信号一个目标：`runs/interrupts/<台账号>.json`，N 个目标 N 份。
# 三态照旧：读不懂 ⇒ `unreadable`（不许当成"没人叫停"）。

#: 中断信号目录（`<工作区>/runs/interrupts/`）。
INTERRUPT_DIR_NAME = "interrupts"
#: 中断信号的审计流水（与 `stop-history.jsonl` 同一个 `runs/` 目录）。
INTERRUPT_HISTORY_NAME = "interrupt-history.jsonl"
#: 逐子代理中断的理由码：它就是循环里那条停止理由的逐字同一个词（`agent_loop` 读它）。
INTERRUPT_REASON = "interrupted_by_parent"


def interrupt_dir(root: str | Path) -> Path:
    """中断信号目录。"""
    return Path(root) / PID_DIR_NAME / INTERRUPT_DIR_NAME


def interrupt_path(root: str | Path, task_id: str) -> Path:
    """某一个子代理的中断信号落在哪（一个目标一份文件，见上面那段理由）。"""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(task_id or ""))
    return interrupt_dir(root) / f"{safe or '_'}.json"


def request_interrupt(root: str | Path, task_id: str, *,
                      reason: str = INTERRUPT_REASON, by: str = "",
                      by_task_id: str = "") -> dict[str, Any]:
    """写下"停这一个孩子当前那一轮"的信号。返回信号里那份负载。

    幂等（同一个目标已有一份 ⇒ 原样返回 `existing`）：与工作区那把开关同一条纪律 ——
    "谁在什么时候为什么叫停"只能有第一次那一份。
    """
    path = interrupt_path(root, task_id)
    existing = read_interrupt(root, task_id)
    if existing is not None and "unreadable" not in existing:
        return existing
    payload = {"reason": str(reason or INTERRUPT_REASON), "by": str(by or "?"),
               "by_task_id": str(by_task_id or ""), "target_task_id": str(task_id or ""),
               "at": _now_iso(), "path": str(path)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return payload


def read_interrupt(root: str | Path, task_id: str) -> dict[str, Any] | None:
    """读某一个目标的中断信号：没叫停 ⇒ `None`；叫停了但读不懂 ⇒ 带 `unreadable` 的负载。"""
    path = interrupt_path(root, task_id)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            raise ValueError(f"顶层不是对象（{type(data).__name__}）")
    except Exception as exc:  # noqa: BLE001 —— 读不懂就是读不懂（三态：不许折成"没叫停"）
        return {"reason": INTERRUPT_REASON, "by": "?", "by_task_id": "",
                "target_task_id": str(task_id or ""), "at": "", "path": str(path),
                "unreadable": f"{type(exc).__name__}: {exc}"}
    data.setdefault("reason", INTERRUPT_REASON)
    data.setdefault("by", "?")
    data.setdefault("target_task_id", str(task_id or ""))
    data.setdefault("path", str(path))
    return data


def interrupt_applies(state: Mapping[str, Any] | None, my_task_id: str) -> dict[str, Any]:
    """这份信号管不管我：`{"checked","applies","reason"}`。

    只有精确的那一个目标才停（DSH `interrupt_agent` 的授权面：目标必须是后代，
    而停止只落在目标自己那一轮）。别人名字的信号对我不适用，而且那是"查过了、
    不适用"，不是"没查成" —— 两者分得开正是这个函数存在的理由。
    """
    if not isinstance(state, Mapping):
        return {"checked": False, "applies": False, "reason": "没有信号负载 ⇒ 判不了"}
    target = str(state.get("target_task_id") or "")
    me = str(my_task_id or "")
    if not target or not me:
        return {"checked": False, "applies": False,
                "reason": "没有目标编号或我没有台账号 ⇒ 判不了（判不了 ≠ 适用）"}
    return {"checked": True, "applies": target == me,
            "reason": "" if target == me else f"这份信号是给 {target} 的，不是我（{me}）"}


def consume_interrupt(root: str | Path, task_id: str, *, sid: str | None = None,
                      level: str = INTERRUPT_REASON) -> dict[str, Any]:
    """撤走这一份信号并把审计写进 `runs/interrupt-history.jsonl`（一次性信号，§140 同族）。"""
    path = interrupt_path(root, task_id)
    state = read_interrupt(root, task_id) or {}
    entry = {"at": _now_iso(), "level": str(level), "target_task_id": str(task_id or ""),
             "sid": str(sid or ""), "reason": str(state.get("reason") or ""),
             "by": str(state.get("by") or ""), "by_task_id": str(state.get("by_task_id") or "")}
    try:
        hist = interrupt_dir(root) / INTERRUPT_HISTORY_NAME
        hist.parent.mkdir(parents=True, exist_ok=True)
        with hist.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass        # 审计写不成不改变"信号已撤走"这件事（返回到调用方去读 `removed`）
    try:
        if path.is_file():
            path.unlink()
            return {**entry, "removed": True}
    except OSError:
        return {**entry, "removed": False}
    return {**entry, "removed": False}


def interrupt_history(root: str | Path, limit: int = 5) -> list[dict[str, Any]]:
    """最近几条中断审计（读不成返回空表 —— 调用方要自己判"没有"与"读不到"）。"""
    hist = interrupt_dir(root) / INTERRUPT_HISTORY_NAME
    if not hist.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in hist.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    except Exception:  # noqa: BLE001 —— 坏行不许让整个历史读不出来
        return out
    return out[-max(1, int(limit)):]


def request_stop(root: str | Path, *, reason: str = DEFAULT_REASON, by: str = "user",
                 force: bool = False, sid: str | None = None,
                 explicit: str | Path | None = None,
                 root_task_id: str = "") -> dict[str, Any]:
    """写下停机开关（幂等：已经有了就原样返回，不改第一次的理由）。

    返回开关里那份负载（`{reason, by, force, at, sid, path}`，给了子树根时多一格
    `root_task_id`）。
    为什么把理由与"谁说的"写进「文件内容」而不是只建一个空文件：
    "谁在什么时候为什么叫停"是事后唯一能回答"这一趟为什么停"的东西，
    而空文件只能回答"停过"。第一次写下的那份不许被后来的请求覆盖
    （同一趟里 M 与用户都可能叫停，先到先得 —— 与 `conductor` 的终态口径一致）。

    需要知道"这把开关是不是我写的"（退出码 `0/3/4`）时用 :func:`request_stop_detail`：
    这里刻意保持旧签名与旧返回，免得调用方为了一个读数去改一遍。
    """
    return request_stop_detail(root, reason=reason, by=by, force=force, sid=sid,
                               explicit=explicit, root_task_id=root_task_id)[0]


def read_stop(root: str | Path, *, explicit: str | Path | None = None) -> dict[str, Any] | None:
    """读停机开关。没叫停 ⇒ `None`；叫停了但读不懂 ⇒ 带 `unreadable` 的负载（不许读成"没叫停"）。

    第三态为什么要单列：一个坏掉的开关文件被读成"没人叫停"，等于「停机请求消失」 ——
    而"没查成"与"查过了没问题"必须分得开（本项目的三态纪律）。

    开关的生命周期见 `consume_stop`（`draft/37` §140 修的 bug）：它是一份"信号"，
    被一趟运行消费之后就撤走，审计留在 `runs/stop-history.jsonl` 里。
    """
    path = stop_path(root, explicit)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            raise ValueError(f"顶层不是对象（{type(data).__name__}）")
    except Exception as exc:  # noqa: BLE001 —— 读不懂就是读不懂，不许当成"没叫停"
        return {"reason": DEFAULT_REASON, "by": "?", "force": False,
                "at": "", "sid": "", "path": str(path),
                "unreadable": f"{type(exc).__name__}: {exc}"}
    data.setdefault("reason", DEFAULT_REASON)
    data.setdefault("by", "?")
    data.setdefault("force", False)
    data.setdefault("path", str(path))
    return data


def history_path(root: str | Path) -> Path:
    """停机历史（每一次"被消费掉的叫停"一行 JSON）——审计记录不随开关一起消失。"""
    return Path(root) / PID_DIR_NAME / "stop-history.jsonl"


def consume_stop(root: str | Path, *, sid: str | None = None, level: str = "stop_file",
                 explicit: str | Path | None = None, remove: bool = True) -> dict[str, Any]:
    """消费掉这一把开关：把"谁在什么时候为什么叫停、被哪一趟用掉"记进历史，然后撤掉它。

    ## 为什么必须撤（`draft/37` §140 的 bug，实测 `temp/_stop_probe.py`）

    改前：`conductor.stop` 停了一趟之后开关留在盘上 ⇒ 紧接着的 `--resume` 在第 0 步
    就被同一把开关停掉（0 步、0 次模型调用），而同一个工具的产物里写着"可续跑的步检查点 +
    续跑简报" —— 两件事互相拆台；连带 E 的实验子进程也会一出现就被它杀掉。
    改后：开关是一次性信号（停一趟、记一笔、撤走），下一次叫停要重新写一份
    （`request_stop` 于是不会把"用户第二次叫停"当成幂等请求吃掉）。

    ## `remove=False`（S4，子树开关）：记一笔但不撤

    子树开关（`stop_scope` = `"subtree"`）要一支上多个循环各自读到，所以只有
    那一支的根（`my_task_id == root_task_id`）撤它；别的成员只记一笔（`level` 里带
    自己是哪一档）—— 否则"先读到的那个把开关吃掉"，后面的成员静默不停
    （与 §140 那个 bug 同一族，只是方向反过来）。
    撤不掉/写不进历史都不改变"这一趟已收工"这个事实（照旧返回负载）。

    ## 为什么审计不丢

    历史行落在 `runs/stop-history.jsonl`（append-only）：`{…开关负载…, consumed_at,
    consumed_by_sid, level, removed}`；`agentflow stop --status` 在开关不在时会把它读出来。
    """
    path = stop_path(root, explicit)
    state = read_stop(root, explicit=explicit)
    if state is None:
        # 没有开关可消费 ⇒ 空表（这不是"记了一笔空的"：什么都没发生，
        # 调用方据此知道"没有人叫停过"；要区分的那一档是"读了但读不懂"，
        # 那一支不返回 None 而是带 `unreadable` 的负载，照常被消费掉）。
        return {}
    record = dict(state)
    record.update({"consumed_at": _now_iso(), "consumed_by_sid": str(sid or ""),
                   "level": str(level or "stop_file"), "removed": bool(remove)})
    try:
        hist = history_path(root)
        hist.parent.mkdir(parents=True, exist_ok=True)
        with hist.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass                      # 历史写不下去也不许让"停下"这件事失效
    if remove:
        try:
            path.unlink()
        except OSError:
            pass                  # 撤不掉（被别的进程占着）也要把"这一趟已收工"返回去
    return record


def stop_history(root: str | Path, *, limit: int = 5) -> list[dict[str, Any]]:
    """读停机历史（最近 `limit` 条，按时间正序）。坏行如实跳过（读不出来不算"没有"）。"""
    path = history_path(root)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out[-int(limit):] if limit else out


def clear_stop(root: str | Path, *, explicit: str | Path | None = None) -> bool:
    """撤掉停机开关（返回"撤掉了没有"）。

    `draft/37` §140 之后不再需要为了续跑而显式撤：开关被消费（停一趟）时就撤走了。
    这条命令仍然有用：在开关生效之前撤销这次叫停（例如刚写完发现写错了）。

    真的撤掉了才通知 `set_stop_hook` 装上的监听器（action=`"cleared"`）：
    "本来就没有开关可撤"什么都没变，不该报成一次变化。
    """
    path = stop_path(root, explicit)
    if not path.is_file():
        return False
    before = read_stop(root, explicit=explicit) or {}
    path.unlink()
    _notify_stop(root, "cleared", before)
    return True


# ---------------------------------------------------------------- 子进程登记


def pid_dir(root: str | Path) -> Path:
    return Path(root) / PID_DIR_NAME


def pid_path(root: str | Path, role: str, sid: str | None = None, pid: int | None = None) -> Path:
    """一个进程的登记文件：`runs/<role>-<sid>.pid`（同一 (角色, 会话) 只登记一条）。"""
    tag = str(sid or "nosid")
    return pid_dir(root) / f"{role}-{tag}.pid"


def register_pid(root: str | Path, role: str, sid: str | None = None,
                 pid: int | None = None) -> Path:
    """登记"这一趟起的进程"（父进程自己）。返回登记文件路径。"""
    me = int(pid if pid is not None else os.getpid())
    path = pid_path(root, role, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": me, "role": str(role), "sid": str(sid or ""),
                                "started_at": _now_iso(),
                                "ppid": int(os.getppid())},
                               ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return path


def unregister_pid(root: str | Path, role: str, sid: str | None = None) -> bool:
    """注销登记（正常收工时调用；进程被杀时它自然留在盘上，`live_pids` 会把它判成死的）。"""
    path = pid_path(root, role, sid)
    if not path.is_file():
        return False
    path.unlink()
    return True


def alive(pid: int) -> bool:
    """这个 pid 还活着吗。

    实现按平台分两条（都实测过，别换成"看起来能用"的写法）：

    - Windows：`OpenProcess(SYNCHRONIZE)` + `WaitForSingleObject(h, 0) == WAIT_TIMEOUT`。
      为什么不用 `tasklist`：沙箱里它拿不到读数（本机实测：登记了自己的 pid 也判"不活着"，
      于是"还活着的进程"整个消失）；为什么不用 `os.kill(pid, 0)`：Windows 上那不是探活，
      它会 `TerminateProcess`（把被探测的进程杀掉）。
    - 其它平台：`os.kill(pid, 0)`（POSIX 的探活语义）。
    """
    pid = int(pid)
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = ctypes.c_void_p
            k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = k32.OpenProcess(0x00100000, 0, pid)     # SYNCHRONIZE
            if not handle:
                return False
            try:
                return k32.WaitForSingleObject(handle, 0) == 0x102   # WAIT_TIMEOUT
            finally:
                k32.CloseHandle(handle)
        except Exception:  # noqa: BLE001 —— 探不了就说"不活着"（调用方据此不杀它）
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def live_pids(root: str | Path, *, role: str = "") -> list[dict[str, Any]]:
    """登记在盘上、且「真的还活着」的进程（逐条带 `pid/role/sid/started_at`）。

    文件在而进程没了 ⇒ 不返回它（那是"被杀过/退过"的残留），但也不删它 ——
    "这里死过一个进程"本身就是读数（`--force` 的收尾会把它清掉）。
    """
    out: list[dict[str, Any]] = []
    d = pid_dir(root)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.pid")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 —— 读不懂的登记不当成"活进程"
            continue
        if not isinstance(data, dict):
            continue
        if role and str(data.get("role") or "") != role:
            continue
        if alive(int(data.get("pid") or 0)):
            out.append({**data, "path": str(p)})
    return out


def kill_tree(pid: int, *, timeout: float = 60) -> dict[str, Any]:
    """「直接杀掉」这个进程及其子孙（`taskkill /T /F` / `kill -9`）。

    返回值如实给出用了哪条路与命令输出 —— "杀没杀掉"必须能复核，
    不许写成"应该杀掉了"。`/T` 是关键：只杀父进程会留下子进程继续跑
    （§127 的真机读数：包装进程被 kill 之后 python 子进程又跑了 12 分钟）。

    受限环境里 `taskkill` 可能被拒（本机沙箱实测 `ERROR: Access denied`，rc=1）
    ⇒ 返回值里 `killed=False` + 原样理由，「由调用方补刀」（`Popen.kill()`），
    而不是在这里假装杀掉了。
    """
    pid = int(pid)
    if os.name == "nt":
        cmd = ["taskkill", "/PID", str(pid), "/T", "/F"]
    else:
        cmd = ["kill", "-9", str(pid)]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=max(1.0, float(timeout)))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"pid": pid, "killed": False, "via": cmd[0],
                "detail": f"{type(exc).__name__}: {exc}"}
    return {"pid": pid, "killed": done.returncode == 0, "via": cmd[0],
            "detail": (done.stdout or done.stderr or "").strip()[:300]}


def _kill_via_job(pid: int) -> dict[str, Any]:
    """把这条登记进程放进一个临时作业对象、宽限一小会儿、然后收掉整棵树。

    为什么能对"已经跑起来的进程"用：作业对象允许事后 `AssignProcessToJobObject`
    （只要它还没在别的作业里）。于是 `agentflow stop --force` 不必知道进程是怎么起的
    —— 它只需要 pid，剩下交给 OS。

    返回与 `kill_tree` 同形的读数（`killed`/`via`/`detail`）；用不了作业对象时
    `killed=False` + `via=""`（调用方照旧退回 `taskkill`）。
    """
    from . import jobobject as JB

    if not JB.available():
        return {"pid": int(pid), "killed": False, "via": "",
                "detail": f"作业对象用不了：{JB.unavailable_reason()}"}
    try:
        job = JB.create_job(f"agentflow-stop-{int(pid)}")
    except JB.JobObjectUnavailable as exc:
        return {"pid": int(pid), "killed": False, "via": "", "detail": str(exc)}
    try:
        # 作业归属不向前追溯（E14 实测）：只 assign 根，不会把它此前已经生出来的
        # 子进程带进来 ⇒ 必须把现有后代逐个也放进去（新生的才自动继承）。
        placed = JB.assign_tree(job, int(pid))
        if not placed.get("assigned"):
            return {"pid": int(pid), "killed": False, "via": "job",
                    "detail": "AssignProcessToJobObject 失败（可能它已在别的作业里）"}
        got = JB.grace_then_kill(job, grace_sec=1.5, poll_sec=0.2)
        return {"pid": int(pid), "killed": bool(got.get("killed")) or not alive(int(pid)),
                "via": "job",
                "detail": (f"作业对象：{got.get('note')}；放进作业的 {placed['assigned']}"
                           + (f"（没放进去的 {placed['failed']}）" if placed.get("failed") else "")
                           + f"；宽限结束时还挂着 {got.get('stragglers')}；"
                             f"收尾后 left={got.get('left')}")}
    finally:
        try:
            JB.close(job)
        except Exception:  # noqa: BLE001 —— 关句柄失败不该带走调用方
            pass


def kill_registered(root: str | Path, *, role: str = "",
                    exclude_pid: int | None = None, prefer_job: bool = True) -> dict[str, Any]:
    """把登记在盘上、还活着的进程「连子孙一起」杀掉，并清掉登记文件。

    `exclude_pid`：M 在「自己这一趟里」调强制停止时要把自己排除掉 ——
    杀掉自己的进程树会让这次工具调用永远回不去（返回值、台账、续跑简报全丢）。
    调用方（M 自己）随后由步循环的停机判据收工（停机开关里 `force=true` ⇒
    `stop_reason="force_stop"`）；「外部」的 `agentflow stop --force` 不给 `exclude_pid`，
    于是连父进程一起杀 —— 那正是"直接杀掉"的语义。

    `prefer_job=True`（缺省）时优先走作业对象（`draft/39` §3.21 五 I13）：受限环境里
    `taskkill /T /F` 会被拒（实测 `Access denied`），而"把进程放进作业对象再关句柄"
    由 OS 收掉整棵传递树 —— 不依赖那条命令能不能成功。作业对象这条路不通时照旧
    退回 `taskkill`（并在结果里记 `via`），所以这条改动只增不减。
    """
    victims = [v for v in live_pids(root, role=role)
               if exclude_pid is None or int(v["pid"]) != int(exclude_pid)]
    results = []
    kept: list[int] = []
    for v in victims:
        pid = int(v["pid"])
        # 自己的 pid 不走作业对象那一路（`draft/39` §6.12 的实测教训）：
        # 把自己放进作业再关句柄，会把调用者连同它的返回值、台账、续跑简报一起收掉
        # —— 而"要不要把自己排除"本来就是调用方的显式决定（`exclude_pid`）。
        # 于是 pid == 本进程时只用 `taskkill` 那条退路（成败照实报，登记该留就留）。
        use_job = prefer_job and pid != os.getpid()
        got = _kill_via_job(pid) if use_job else {"pid": pid, "killed": False, "via": ""}
        if not bool(got.get("killed")):
            fallback = kill_tree(pid)
            if got.get("via"):
                # 作业对象那条路没成：把两条路的结果都留下（"为什么没杀掉"要能复核）
                fallback = dict(fallback)
                fallback["job_attempt"] = got
                fallback["via"] = str(fallback.get("via") or "")
            got = fallback
        results.append(got)
        # 只有"确实杀掉了"或"它本来就死了"才注销登记。
        #
        # `draft/37` §140 的真机读数（这条改前是反的）：受限环境里 `taskkill /T /F`
        # 会被拒（`ERROR: Access denied`，`os.kill(SIGTERM)` 同样 `WinError 5`），
        # 而改前照删登记 ⇒ `agentflow stop --status` 随后报"登记着的活进程：0 个"，
        # 而那个进程还活着 —— 一个把"没杀成"折叠成"没有活进程"的假绿
        # （三态纪律里最忌的那一类）。杀不成就把登记留着：status 会照实报它在册。
        if bool(got.get("killed")) or not alive(pid):
            try:
                Path(str(v["path"])).unlink()
            except OSError:
                pass      # 登记文件删不掉不影响"进程已死"这个事实：live_pids 会滤掉死 pid
        else:
            kept.append(pid)
    failed = [r for r in results if not bool(r.get("killed"))]
    return {"requested": [int(v["pid"]) for v in victims], "results": results,
            "killed": sum(1 for r in results if r["killed"]),
            "kept": kept, "failed": failed,
            "excluded": int(exclude_pid) if exclude_pid is not None else None}


# ---------------------------------------------------------------- 内部


def running_loops(root: str | Path) -> dict[str, Any]:
    """现在有没有在跑的循环（`draft/39` §2 D07 那一行要求 `--status` 显式回答它）。

    判据两路取并集，缺一路都会把"没人消费的开关"读成"没事"：

    1. 会话面：某段会话里某角色最后一条 `agent_run_start` 之后没有该角色对应的
       `agent_run_end` ⇒ 那一趟还在跑（按角色报出来）。会话是叙事面，
       强杀不留 `agent_run_end`，所以它单独用会漏；
    2. 进程面：`live_pids` 里登记着且真的活着的进程 ⇒ 也报出来。
       进程面单独用会漏"登记没写/被清理"的情况。

    ## E-13 改掉的两处假阳性（`draft/56 §2 主线 A`）

    - 按角色配平，而不是整个会话取最后一条 `agent_run_start`：一个会话里可以
      先后跑过多个角色（主控派活、被召唤者各跑一趟）。旧口径只看"最后一条 start"，
      于是 `M 起 → C 起 → M 收` 这种会话被判成"没人在跑"（最后一条 start 是 C，
      而 M 的 end 在它之后）—— 真正在跑的 C 被静默吞掉。反过来，
      `C 起 → C 收 → D 起 → D 收` 也会因为"最后一条 start 之后有任意 end"被判成没在跑。
    - 排除被拒的续跑：`--resume` 的四条拒绝路径各写一条 `agent_run_start`
      （带 `resume_refused`），它一步都没跑（`_note_resume_refusal` 的判据就是
      "没有后续的 `agent_step`"）。把它算成"在跑"会让 `--status` 天天说谎，
      而"循环还活着吗"这个读数正是用户叫停时唯一能据以判断的东西。

    返回 `{"running": [{"role","sid","since"}], "live": [...], "answer": "有"/"没有"}`。
    """
    running: list[dict[str, Any]] = []
    stale: list[str] = []
    from . import sessions as _SESS

    for info in _SESS.list_sessions(root):
        sid = str(info.get("sid") or "")
        events, problems = _SESS.read_session(root, sid)
        if problems:
            # 读不出来的会话 ⇒ 这一路判不了，如实说（"没查成"不许读成"没在跑"）
            stale.append(sid)
            continue
        # 按角色各取一条链：某个角色的最后一条 start 之后有没有该角色的 end。
        last_start: dict[str, dict[str, Any]] = {}
        closed: set[str] = set()
        for e in events:
            role = str(e.get("role") or "")
            kind = e.get("kind")
            if kind == "agent_run_start":
                if e.get("resume_refused"):
                    # 被拒的续跑不是起点（它一步都没跑）：既不开启、也不关闭任何一趟
                    continue
                last_start[role] = e
                closed.discard(role)
            elif kind == "agent_run_end":
                closed.add(role)
        for role, start in last_start.items():
            if role in closed:
                continue
            running.append({"role": role, "sid": sid, "since": str(start.get("ts") or "")})
    live = live_pids(root)
    return {"running": running, "live": live, "unreadable_sessions": stale,
            "answer": "有" if (running or live) else "没有"}


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def selftest() -> int:
    """最小自检：开关的三种状态 + 登记/清理（不碰任何真进程的生死）。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="stopctl_selftest_"))
    checks: list[tuple[str, bool]] = []
    checks.append(("没叫停 ⇒ None", read_stop(root) is None))
    got = request_stop(root, reason="user", by="M")
    checks.append(("叫停 ⇒ reason 对得上", got["reason"] == "user" and read_stop(root) is not None))
    again = request_stop(root, reason="budget")
    checks.append(("幂等：不改第一次的理由", again["reason"] == "user"))
    checks.append(("撤掉之后又是 None", clear_stop(root) and read_stop(root) is None))
    request_stop(root, force=True)
    checks.append(("强制那一份读得出来", bool(read_stop(root)["force"])))
    clear_stop(root)
    me = register_pid(root, "M", "selftest")
    checks.append(("登记了且自己活着", [p["pid"] for p in live_pids(root)] == [os.getpid()]))
    checks.append(("注销之后不在了", unregister_pid(root, "M", "selftest") and not live_pids(root)))
    del me
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    sys.exit(selftest())

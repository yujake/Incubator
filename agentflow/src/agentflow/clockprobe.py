# -*- coding: utf-8 -*-
"""“等谁”的探针与判定：把外部读口折成三态的那一层。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第五刀。
`_TARGET_PROBE` 是进程级可变量：`set_target_probe` 重新赋值它，`_probe_read` 读它。
按本仓的纪律「可变量没有跨模块共享，只有归谁所有」，两个写点/读点必须同处一个模块
—— 否则 `from .clock import _TARGET_PROBE` 拿到的是 import 那一刻的快照，
判据装上去的读口会在下一刀里静默失效。

## 装了什么

- `_TARGET_PROBE`：进程内唯一的那一格读口（没接上时是 `None`，三态里的
  `unjudgeable`，绝不折成 `open` / `closed`）；
- `set_target_probe`：唯一写点（装配期由 `tools/clock_tools.register` 接上）；
- `_probe_read`：问一次读口，把返回规整成六格（`checked` / `found` / `closed` /
  `resolved` / `why` / `task_text`）；
- `_judge_target`：把那六格折成 `(closed | open | unjudgeable, resolved, why)`。

## 为什么 `target_state` 不在这里

`target_state` 要 `book()` 才能判 "program:" 那一档，而 `book` / `TimerBook` / `Timer`
在 `clocktimer.py`，且 `Timer.due_reason` 反过来要问 `target_state` —— 四者是一个
运行期成环的整体（见 `clocktimer.py` 模块头）。把 `target_state` 留在这里会造出
`clocktimer -> clockprobe -> clocktimer` 的环，所以它跟着环核走，本模块只留探针。

## 等价性

四块逐字搬移（逐名 AST dump 全等），`clock.py` 原样再导出；所有
`from .clock import set_target_probe` / `_probe_read` 的调用点一个字都没改。
"""

from __future__ import annotations

from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    _resolve_root,
)

#: "等谁"的读口。工具层在装配期把"台账/名册里这个东西收口了没有"接上。
#:
#: 为什么不在这里直接读 Store / 名册：本模块的纪律是"能被判据单独喂假时钟、单独检查
#: 读数"，不该为了一个查询把 Store 拖进来（与 `set_due_handler` 同一条切法）。
_TARGET_PROBE: Callable[[str, str, str], Mapping[str, Any]] | None = None


def set_target_probe(probe: Callable[[str, str, str], Mapping[str, Any]] | None):
    """接上"等谁"的读口，返回上一个。

    读口的签名是 `probe(workspace, kind, ref) -> dict`，必须回这五格（三态不许折平）：

    - `checked`：这次查成没查成（没有台账/读不成 => False）；
    - `found`：台账/名册里有没有这个东西；
    - `closed`：它收口了没有（`found` 为假时无意义）；
    - `resolved`：解析成的具体对象（`task:t000012` / `agent:D1`），起表时落进台账；
    - `why`：没查成 / 没找到 / 还在跑的理由（读数要能读出"为什么还没到"）。
    """
    global _TARGET_PROBE
    previous = _TARGET_PROBE
    _TARGET_PROBE = probe
    return previous


def _probe_read(workspace: str | Path, kind: str, ref: str) -> dict[str, Any]:
    """问一次"等谁"的读口，把结果规整成五格（三态都在里面）。"""
    probe = _TARGET_PROBE
    if probe is None:
        return {"checked": False, "found": False, "closed": False,
                "resolved": f"{kind}:{ref}",
                "why": "没有接上'等谁'的读口（set_target_probe 还没接）=> 判不了它收口了没有"}
    try:
        got = dict(probe(_resolve_root(workspace), str(kind), str(ref)) or {})
    except Exception as exc:  # noqa: BLE001 - 读口炸了是"没查成"，不是"没到"
        return {"checked": False, "found": False, "closed": False,
                "resolved": f"{kind}:{ref}",
                "why": f"读口抛了 {type(exc).__name__}: {exc}"}
    got.setdefault("resolved", f"{kind}:{ref}")
    got.setdefault("why", "")
    got.setdefault("checked", False)
    got.setdefault("found", False)
    got.setdefault("closed", False)
    #: 被等对象那一行的 task 原文（业主 2026-10-27：等子代理的目的自动用它填）。
    #: 读口拿不到就是空串 —— 空串只表示"这一格没有可用的原文"，不表示"它没有 task"。
    got.setdefault("task_text", "")
    return got


def _judge_target(got: Mapping[str, Any], kind: str, ref: str) -> tuple[str, str, str]:
    """把读口的五格折成 `(三态之一, 解析成的对象, 理由)`。折法见 `target_state`。"""
    resolved = str(got.get("resolved") or f"{kind}:{ref}")
    why = str(got.get("why") or "")
    if not got.get("checked"):
        return ("unjudgeable", resolved, why or "读口说这次没查成")
    if not got.get("found"):
        return ("closed", resolved,
                f"被等对象已不在台账/名册里（{why or '查过了、没有这一行'}）=> 按收口处置")
    if got.get("closed"):
        return ("closed", resolved, why or "它收口了")
    return ("open", resolved, why or "它还在跑")

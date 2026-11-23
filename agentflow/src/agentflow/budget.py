# -*- coding: utf-8 -*-
"""可追加的总预算：一个工作区一份、运行期可改、每次闸门现读。

## 业主口径

不硬性限制运行步数，但限制预算；用户可追加，运行消耗的钱从总预算里实时扣除，扣完
时自动发送优雅停止请求（这时预算可能继续扣成负的一点点，但无大碍）。

## 为什么是"盘上寄存器"而不是一个内存里的参数

`Policy` 是 `frozen=True` 的值对象、`TokenMeter(budget_usd=…)` 与
`LlmSeam(usd_budget=…)` 的上限只在构造期注入、`SeamSpend.usd` 只增 —— 于是"跑到
一半追加预算"这件事在结构上没有入口，唯一的办法是重跑一次。而这个项目的运行是
小时级、多智能体的：用户在网页上看见还剩 $0.3、想加 $2 让它跑完，是常态而不是例外。

所以这一层做成盘上寄存器（`<工作区>/budget.json`），它只回答一个问题：
「这一趟的总预算是多少」。三个刻意的地方：

1. 每次判据现读盘（不缓存）：`TokenMeter` / `LlmSeam` / 步循环在每一次花钱之前
   读它 —— 用户在网页上点"追加"之后，下一个模型调用就受新上限约束（不需要重启、不需要重跑）。
   已花的钱不在这里算：唯一权威账是 `usage_ledger`（`tokenmeter.spent()`），
   这里只放"总额度"与"追加历史"，绝不放花销 —— 两份账必然分叉。
2. `total_usd` 只增不减、追加留历史：`added` 是 append-only 的
   `[{usd, by, at, note}]`。"谁在什么时候加了多少钱"与"钱花在哪儿"是两条轴，
   都要能事后回答（业主那句"运行消耗的钱从总预算里实时扣除"要的是前者与后者的差）。
3. 读不懂就是读不懂（三态）：文件坏了/数字非法 ⇒ `problem` 非空，且
   `limit_usd()` 回退到调用方给的那个上限（保守方向：少花，不是多花），
   并把问题原样带进读数 —— 不许把"配置坏了"折成"没有预算"（那会变成不限量）。

## 它不管什么（划清边界）

- 不管花销记账（`tokenmeter` / `usage_ledger` 是唯一权威账）；
- 不管闸门怎么判（`tokenmeter.guard` / `llmseam` 的调用前检查 / 步循环 / 多轮闸门各自持有
  判据；本模块只提供"现读的上限"这一个数）；
- 不管停机（扣完之后的优雅停止走 `stopctl`，与本模块是同族但各司其职）。
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "PAPERWORK_FIRST_RULE",
    "PAPERWORK_RESERVE_USD",
    "REGISTER_NAME",
    "add_usd",
    "limit_usd",
    "paperwork_first_reading",
    "read_register",
    "reading",
    "register_path",
    "write_initial",
]

#: 寄存器的落点（工作区根相对）。
REGISTER_NAME = "budget.json"

#: 收工必需物的预算储备线（美元）：余量掉到它以下时，M 必须先把收工必需物落盘，
#: 再回去继续攻证明。
#:
#: 为什么是一个绝对数而不是比例：真机 `projects/lp-ball-5`（2026-11-17）的现场是
#: 硬上限 $5 —— 预算不是"还剩 20%"，而是"下一个模型调用就可能扣到零"。比例线在
#: 小预算趟里永远触发得太晚（$0.4 的 20% 是 $0.08，一次重证就没了）；而这一档要买的
#: 是"写两份文件"这点工夫，它有一个与趟大小无关的下限。$1 是保守取值：两份文件
#: （`out/package/ACCEPTANCE-TARGETS.json` + `out/report/REPORT.md`）不需要模型写满一页，
#: 但"从容写完、还能自检一遍"要留出不止一次调用的余量。
PAPERWORK_RESERVE_USD = 1.0

#: 「预算见底之前先交收工必需物」这条硬口径的逐字正文。
#:
#: 为什么单独成一个常量（而不是在 `specs/m.py` 的政策与 `agent_skills.py` 的手册里
#: 各写一遍）：这是同一句话的两处落点，两处各写一遍必然漂 —— 而它一旦漂了，模型按
#: 其中一处行动、判据按另一处判，两边都"有理"。所以正文只有这一份，两处都引用它；
#: 判据 `tests/test_m_lands_the_paperwork_before_the_budget_runs_out.py` 逐字钉住
#: 两次渲染里都出现了它，并用"删掉这一句 ⇒ 同一判据必红"做反真空。
PAPERWORK_FIRST_RULE = (
    "预算余量低于阈值时，先把收工必需物落盘（`out/package/ACCEPTANCE-TARGETS.json` 与 "
    "`out/report/REPORT.md`），再回去继续攻证明；宁可少证一条，不许交不出验收表"
)


def register_path(root: str | Path) -> Path:
    """这一份预算寄存器在哪（不保证存在）。"""
    return Path(root) / REGISTER_NAME


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _coerce_usd(raw: Any) -> float | None:
    """把一格额度读成非负浮点；读不出/非法 ⇒ `None`（调用方据此报 problem）。"""
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(val) or math.isinf(val) or val < 0:
        return None
    return val


def read_register(root: str | Path) -> dict[str, Any]:
    """读寄存器（三态）：`{checked, exists, total_usd, added, path, problem}`。

    - 文件不在 ⇒ `exists=False`、`checked=True`、`problem=""`（"没设过预算"是正常形态）；
    - 文件在但读不懂（坏 JSON / 不是对象 / `total_usd` 非法）⇒ `problem` 非空、
      `total_usd=None` —— 调用方必须看得见这一档（见模块 docstring）。
    """
    path = register_path(root)
    out: dict[str, Any] = {"checked": True, "exists": False, "total_usd": None,
                           "added": [], "path": str(path), "problem": ""}
    if not path.is_file():
        return out
    out["exists"] = True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        out["problem"] = f"预算寄存器读不出来（{type(exc).__name__}: {exc}）"
        return out
    if not isinstance(data, Mapping):
        out["problem"] = f"预算寄存器必须是一个 JSON 对象（收到 {type(data).__name__}）"
        return out
    total = _coerce_usd(data.get("total_usd"))
    if total is None:
        out["problem"] = (f"预算寄存器里的 total_usd 不是非负数字（收到 "
                          f"{data.get('total_usd')!r}）")
        return out
    added = data.get("added")
    out["total_usd"] = total
    out["added"] = [dict(x) for x in added if isinstance(x, Mapping)] \
        if isinstance(added, list) else []
    return out


def limit_usd(root: str | Path, *, fallback: float | None = None) -> float | None:
    """现读这一趟的总预算：寄存器里有就用它，否则用 `fallback`（调用方给的上限）。

    这是全流程唯一的取值口（`tokenmeter` / `llmseam` / 步循环 / 多轮闸门都读它）。
    读不懂时回退到 `fallback` 并把问题留在 `read_register()` 的读数里 —— 少花是安全的
    那一侧，而"折成不限量"是危险的那一侧。
    """
    reg = read_register(root)
    if reg["total_usd"] is not None:
        return float(reg["total_usd"])
    return fallback


def write_initial(root: str | Path, total_usd: float, *, by: str = "user",
                  note: str = "") -> dict[str, Any]:
    """设一个新的总额度（给"第一次设预算"与"UI 里改总额"用）。返回回执。

    与 `add_usd` 的两处不同：

    1. 追加历史不丢：这一笔按 `kind="set"` 记进 `added`，旧的追加记录原样留着 ——
       "谁在什么时候把总额改成多少"与"谁在什么时候追加了多少"是同一份账上的两种事件，
       把后者抹掉会让「已花 7.5 而历史里只有一笔 set」变成一笔无解的账；
    2. 坏寄存器上仍然许写（这是它与 `add_usd` 的差别：后者算不出基数只能拒），
       但"丢了什么"要写进回执（`history_lost`）—— 显式重设是把一份读不懂的文件
       换成一份读得懂的，代价是那份读不懂的原样没了；这件事必须留痕，
       于是它不是"静默覆盖"。
    """
    # `add_usd` 有类型闸、`write_initial` 没有。`_coerce_usd` 读不出时返回 `None` ——
    # 直接用它会让"总额度"静默写成 null，所以这里明确拒绝。
    _usd = _coerce_usd(total_usd)
    if _usd is None:
        raise ValueError(f"总额度必须是**非负数字**，收到 {total_usd!r}；拒写（不写 null）")
    reg = read_register(root)
    got = _write(root, total_usd=total_usd,
                 entry={"kind": "set", "usd": _usd, "by": str(by), "at": _now(),
                        "note": str(note or "")},
                 added_before=reg["added"])
    if got.get("ok") and reg["exists"] and reg["problem"]:
        got["history_lost"] = reg["problem"]
    return got


def add_usd(root: str | Path, usd: float, *, by: str = "user",
            note: str = "") -> dict[str, Any]:
    """追加一笔额度（业主那句"用户可追加预算"的落点）。返回回执。

    追加是单调的：`total_usd` 只增不减（要减就用 `write_initial` 显式重设）。
    非法金额（负数 / NaN / 读不成数字）当场拒 —— 一次静默的"加了 0"会让用户
    以为加上了，而运行照样在下一个闸门停下。
    """
    amount = _coerce_usd(usd)
    if amount is None or amount <= 0:
        return {"ok": False, "reason": f"追加金额必须是正数（收到 {usd!r}）", "path": ""}
    reg = read_register(root)
    if reg["exists"] and reg["problem"]:
        return {"ok": False, "path": str(register_path(root)),
                "reason": f"寄存器读不出来，拒绝在它上面追加（{reg['problem']}）"}
    base = float(reg["total_usd"] or 0.0)
    return _write(root, total_usd=base + amount,
                  entry={"kind": "add", "usd": amount, "by": str(by), "at": _now(),
                         "note": str(note or "")},
                  added_before=reg["added"])


def _write(root: str | Path, *, total_usd: float, entry: Mapping[str, Any],
           added_before: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """原子写寄存器（同目录临时文件 + `os.replace`；半途崩 ⇒ 盘上那份逐字节不变）。"""
    path = register_path(root)
    payload = {
        "total_usd": round(float(total_usd), 6),
        "updated_at": _now(),
        "added": list(added_before or []) + [dict(entry)],
    }
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
                       encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            # 临时文件删不掉可以忽略：它是个点开头的半成品，目标文件一个字节没动，
            # 而这次调用的结局已经如实记成"没写成"（下面的返回里带着原因）。
            pass
        return {"ok": False, "path": str(path), "reason": f"写寄存器失败：{exc}"}
    return {"ok": True, "path": str(path), "total_usd": payload["total_usd"],
            "entry": dict(entry), "added_count": len(payload["added"])}


def reading(root: str | Path, *, spent_usd: float | None,
            fallback: float | None = None) -> dict[str, Any]:
    """给人看/给网页看的一格读数：总额度、已花、剩余、追加历史、三态。

    `remaining_usd` 可以为负（业主：「扣完时……这时预算可能会继续扣成负的一点点，
    但无大碍」）：那一点点来自"最后一个请求发出时还没超、回来时超了"。
    负值不是错误，`exceeded=True` 才是那件事的读数。
    """
    reg = read_register(root)
    total = float(reg["total_usd"]) if reg["total_usd"] is not None else fallback
    spent = None if spent_usd is None else float(spent_usd)
    remaining = None if (total is None or spent is None) else round(total - spent, 6)
    return {
        "tri": "unreadable" if reg["problem"] else ("computed" if reg["exists"]
                                                    else "not_applicable"),
        "reason": reg["problem"] or ("寄存器在盘上" if reg["exists"]
                                     else "这一趟没有设过预算（不限量，或由调用方给上限）"),
        "path": reg["path"],
        "exists": reg["exists"],
        "source": "register" if reg["total_usd"] is not None else (
            "fallback" if fallback is not None else "unlimited"),
        "total_usd": total,
        "spent_usd": spent,
        "remaining_usd": remaining,
        "exceeded": bool(remaining is not None and remaining < 0),
        "added": reg["added"],
        "problem": reg["problem"],
    }


def paperwork_first_reading(root: str | Path, *, spent_usd: float | None,
                            fallback: float | None = None) -> dict[str, Any]:
    """「验收表该不该先落盘」这一格读数：余量、储备线、以及一句能直接贴进拒信的人话。

    它是一格读数，不是硬闸：收工门的判定（`acceptance` 那一格的 pass/fail）一个字
    都不因它变 —— 这一格里"还剩多少"没有权力改门，它只回答"这一趟为什么连收工必需物
    都没交出来"。为什么必须做成读数而不是闸：预算是用户随时可追加的寄存器
    （`add_usd`），拿它去挡交付物会让"钱不够"长成"活没干"；而这一档要的恰恰相反 ——
    钱不够时更要把交付物交出来。

    三态照 `reading()` 那一份：`remaining_usd` 为 `None` 是"算不出来"（没设过预算、
    或账本读不成），不是"还剩很多"；`below_reserve` 为 `None` 只可能是同一档。
    `note` 把"还剩多少预算"与"收工必需物"写在同一句里，收工拒信直接用它。
    """
    reg = reading(root, spent_usd=spent_usd, fallback=fallback)
    remaining = reg["remaining_usd"]
    below = None if remaining is None else bool(float(remaining) < PAPERWORK_RESERVE_USD)
    head = "预算读数（不是硬闸，只用来分辨「没写」与「写得不对」）：这一趟"
    if remaining is None:
        note = (head
                + (f"已花 ${float(spent_usd):.6f}" if spent_usd is not None
                   else "已花多少也读不出来")
                + "，而盘上没有预算寄存器、调用方也没给上限 ⇒ 剩余算不出来"
                "（「算不出来」不等于「还剩很多」）。这一档更该先把验收表与报告落盘："
                "交付物是这一趟唯一不会随预算消失的东西。")
        return dict(reg, reserve_usd=PAPERWORK_RESERVE_USD, below_reserve=below,
                    note=note, paperwork_first_rule=PAPERWORK_FIRST_RULE)
    total = reg["total_usd"]
    note = (head
            + f"已花 ${float(spent_usd or 0.0):.6f} / 上限 "
            + (f"${float(total):.6f}" if total is not None else "（未设）")
            + f" / 还剩 ${float(remaining):.6f} ⇒ ")
    if float(remaining) < 0:
        note += ("余量已经透支（预算被扣穿）：这一趟再也买不回一次补写的调用 —— "
                 "收工必需物本该在预算见底之前就落盘（先落收工必需物，再回去攻证明）。")
    elif below:
        note += (f"余量已低于收工储备线 ${PAPERWORK_RESERVE_USD:.2f}：验收表与报告"
                 "本该在预算见底之前就落盘（先落收工必需物，再回去攻证明）。")
    else:
        note += (f"余量还在收工储备线 ${PAPERWORK_RESERVE_USD:.2f} 之上 —— "
                 "这一格缺的是「没写」，不是「写不起」。")
    return dict(reg, reserve_usd=PAPERWORK_RESERVE_USD, below_reserve=below,
                note=note, paperwork_first_rule=PAPERWORK_FIRST_RULE)

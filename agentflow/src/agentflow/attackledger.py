# -*- coding: utf-8 -*-
"""F 的攻坚台账（`work/F/attack-<plan_id>.md`）在 `attack_plans` 里的回指读数。

## 为什么单独一个模块

2026-11-22 `A-0c-1`（CONTRACT-ATTACKPATH，`draft/201`）给 `attack_plans` 加了
`report_path` 列，于是有了一族"按文件问台账"的读数。它起初写在
:mod:`agentflow.refvocab` 里，但那个文件从 717 行涨到 941 行、越过了
`tools/repo_survey.py` 的 800 行软基线（三格 72 → 73）。本仓的既有处置是拆模块、
不抬基线（`refvocab` 自己的 docstring 记着它上一次被拆成 `refspecs` 的同一理由）。

## 边界

- 本模块只做攻坚台账这一族：认族（路径 / 计划号）与"台账认不认它"的判定；
- :func:`attack_ledger_verdict` 是纯函数（零 I/O）—— 两个读侧共用它：
  :func:`attack_ledger_reading`（按 `data/attack_plans.json` 读）与
  `manuscriptretire.attack_ledger_of`（按 `store.rows("attack_plans")` 读）；
- `refvocab` 把本模块的三个公开名回引（re-export），于是"`refvocab` 的索引认这一族"
  这个读法照旧成立，调用点不必改；
- 表读取（`refvocab._table_rows` 那一套）在函数内延迟 import：本模块顶层只依赖
  :mod:`agentflow.refspecs`（纯数据、零 I/O），于是 `refvocab` 可以顶层 import 本模块
  而不成环。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .refspecs import (
    CODE_BAD_ADDRESS, CODE_OK, CODE_TARGET_MISSING, CODE_UNCHECKED,
    STATE_BAD, STATE_MISSING, STATE_OK, STATE_UNCHECKED, _pad6, _text,
)

# ---------------------------------------------------------------- 攻坚台账（A-0c-1）

#: 攻坚台账（F 的 `attack-<plan_id>.md`）认哪些目录：新落点在前，退役旧布局在后。
#:
#: 为什么这里不 import `agent_f.core.REPORT_DIR`：本模块是零 `agent_*` 依赖的纯模块
#: （模块 docstring 的边界），而 `REPORT_DIR` 住在 `agent_f/core.py`。于是"当前落点"
#: 在这里登记一份，历史落点（2026-11-22 之前的 `reports/`）一并认 —— 两处不许漂开
#: 由判据钉住：`tests/test_attack_report_path_is_a_ledger_column.py` 断言本元组的
#: 首项逐字等于 `AgentF.REPORT_DIR`。漂开的表现正是本仓最贵的那一类：写侧落一处、
#: 读侧认另一处，两边都自洽，盘上的稿于是"谁也读不到"。
ATTACK_LEDGER_DIRS: tuple[str, ...] = ("work/F", "reports")

#: 攻坚台账的文件名形态：`attack-<plan_id>.md`（计划号 4-6 位；`_pad6` 归一成 6 位）。
_ATTACK_NAME_RE = re.compile(r"^attack-(?P<id>\d{1,6})\.md$")


def attack_plan_id_of(rel: Any) -> str:
    """这一条路径是不是攻坚台账 ⇒ 那条计划的号（6 位）；不是这一族 ⇒ 空串。

    ## 只认带目录的那一种形态（这是判据，不是疏漏）

    `work/F/attack-000005.md` / `reports/attack-000000.md` 是这一族的两代落点；
    裸名 `attack-000005.md` 不认 —— "攻坚台账"的身份里包含它住哪个目录（同一份东西
    出现在别处就不是台账，这与 `manuscriptfamily` 的"目录是身份的一部分"同一条口径）。

    ## 为什么这里只做"认族 + 取号"，不读盘、不查台账

    本模块的另一半（:func:`attack_ledger_reading`）才读盘。拆开的用处：写面/审计
    只需"这条路径算不算这一族"（零 I/O 可判），而"它有没有台账行"要读
    `data/attack_plans.json` —— 两件事的失败面完全不同，折进一个函数就会把
    "不是这一族"与"读不到表"混成一档。
    """
    raw = _text(rel).replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw:
        return ""
    directory, _, name = raw.rpartition("/")
    if directory not in ATTACK_LEDGER_DIRS:
        return ""
    match = _ATTACK_NAME_RE.fullmatch(name)
    return _pad6(match.group("id")) if match is not None else ""


def _attack_index(root: Path, cache: dict[Any, Any]) -> dict[str, Any]:
    """攻坚台账索引：行上的 `report_path`（权威）∪ 盘上的 `attack-*.md`（真身）。

    返回 `{checked, by_plan, by_path, on_disk, bad_rows, why}`：

    - `by_plan`：`{计划号: 行上记的相对路径}`（只收非空的 `report_path`）；
    - `by_path`：`{归一化路径: 计划号}`（由 `by_plan` 反向建，供"由文件查行"）；
    - `on_disk`：`{计划号: 相对路径}`（扫 :data:`ATTACK_LEDGER_DIRS` 得到的真身）；
    - `checked=False` ⇒ `data/attack_plans.json` 读不出来（"没查成"≠"没有台账行"）。

    ## 为什么"行"与"盘"分开给，而不是直接算一个"对不对"

    两者对不上的方向有两种，处置完全不同：盘上有、行上没有 ⇒ 那正是本路要治的
    缺口（"文件在盘上、台账里没有"）；行上有、盘上没有 ⇒ 行上那个路径是假地址
    （写侧此前在写失败时也会给路径，见 `agent_f/core.py::_apply_round` 的同一格）。
    折成一个布尔之后，这两种都只剩"不一致"，而人要改的东西完全不同。
    """
    from . import refvocab as _RV

    key = ("attack",)
    if key in cache:
        return cache[key]
    got = _RV._table_rows(root, "attack_plans", cache)
    by_plan: dict[str, str] = {}
    for row in got["rows"]:
        plan_id = _pad6(_text(row.get("plan_id")))
        rel = _text(row.get("report_path")).replace("\\", "/")
        if plan_id and rel:
            by_plan[plan_id] = rel
    by_path = {rel: pid for pid, rel in by_plan.items()}
    on_disk: dict[str, str] = {}
    scanned: list[str] = []
    for rel_dir in ATTACK_LEDGER_DIRS:
        base = root / rel_dir
        try:
            if not base.is_dir():
                continue
        except OSError:
            continue
        scanned.append(rel_dir)
        try:
            paths = sorted(base.glob("attack-*.md"))
        except OSError as exc:
            out = {"checked": False, "by_plan": {}, "by_path": {}, "on_disk": {},
                   "bad_rows": 0,
                   "why": f"`{rel_dir}/` 读不出来（{type(exc).__name__}: {exc}）"}
            cache[key] = out
            return out
        for path in paths:
            match = _ATTACK_NAME_RE.fullmatch(path.name)
            if match is not None:
                on_disk[_pad6(match.group("id"))] = f"{rel_dir}/{path.name}"
    out = {"checked": bool(got["checked"]), "by_plan": by_plan, "by_path": by_path,
           "on_disk": on_disk, "bad_rows": int(got["bad_rows"]),
           "why": str(got["why"]), "scanned": scanned}
    cache[key] = out
    return out


def attack_ledger_verdict(*, rel: Any = "", plan_id: Any = "", row_path: Any = "",
                          on_disk: Any = "") -> dict[str, Any]:
    """纯判定（零 I/O）：这一份攻坚台账 / 这条计划，在「行上记的」与「盘上有的」之间是哪一档。

    ## 为什么单独成一个纯函数

    「怎么判」只有这一份实现，但读的地方有两个，它们的输入面不同：
    :func:`attack_ledger_reading` 按文件读（`data/attack_plans.json` + 扫目录），
    `manuscriptretire.attack_ledger_of` 按 `store.rows("attack_plans")` 读（那里已有
    三态化的台账读口）。把判据折进任意一侧，另一侧就会长出第二份 —— 与本模块
    「一张表」的纪律（以及 `manuscriptfamily` 的同一教训）相反。

    ## 入参（`rel` / `plan_id` 二选一；两个都给时以 `rel` 为准）

    - `rel`：路径（`work/F/attack-000005.md`；历史落点 `reports/attack-000000.md` 也认）；
    - `plan_id`：计划号（`5` / `000005` / `attack:000005` 都收）；
    - `row_path`：台账行上的 `report_path`（读侧读到的那个值；空串 = 行上没有记）；
    - `on_disk`：盘上那一份的相对路径（空串 = 盘上没有 / 没查）。

    ## 返回

    `{state, code, rel, plan_id, row_path, on_disk, found, why}`。`checked` 不在这里
    —— 它是"台账读成没读成"的读数，由调用方（那一侧真读了台账）给。本函数只回答
    "在已知的这几格下，这一份算不算有回指"。

    ## 四种"没有"，`why` 逐字分开

    1. 行上记着、且就是给出的那一份 ⇒ `ok`；
    2. 行上记着另一份 ⇒ 点名行上记的是哪一份（不是"不存在"）；
    3. 行上没记、而盘上有那份文件 ⇒ 「只有文件没有台账行」（本路要治的那一档）；
    4. 行上没记、盘上也没有 ⇒「行上没有记稿路径（`report_path` 为空/缺格）」。
       这一档不按计划号反推 `attack-<plan_id>.md` 是否存在 —— 反推等于给台账造
       第二个真身（真机上两个方向都有不匹配：多出来的文件、以及一轮没落稿的计划）。
    """
    out: dict[str, Any] = {"state": STATE_UNCHECKED, "code": CODE_UNCHECKED,
                           "rel": "", "plan_id": "", "row_path": "", "on_disk": "",
                           "found": None, "why": ""}
    text = _text(rel).replace("\\", "/")
    pid = ""
    if text:
        pid = attack_plan_id_of(text)
        if not pid:
            out.update(state=STATE_BAD, code=CODE_BAD_ADDRESS,
                       why=(f"{text!r} 不是攻坚台账的路径：要写成 `work/F/attack-<plan_id>.md`"
                            "（历史落点 `reports/attack-<plan_id>.md` 也认）"))
            return out
        out["rel"] = text
    else:
        raw_pid = _text(plan_id)
        if raw_pid.startswith("attack:"):
            raw_pid = raw_pid[len("attack:"):]
        if not re.fullmatch(r"\d{1,6}", raw_pid):
            out.update(state=STATE_BAD, code=CODE_BAD_ADDRESS,
                       why=(f"{plan_id!r} 不是攻坚计划号：给 `attack:<plan_id>`"
                            "或直接给 4-6 位计划号"))
            return out
        pid = _pad6(raw_pid)
    row = _text(row_path).replace("\\", "/")
    disk = _text(on_disk).replace("\\", "/")
    out.update(plan_id=pid, row_path=row, on_disk=disk)
    if row and (not text or row == text):
        out.update(state=STATE_OK, code=CODE_OK, found=True, why="")
        return out
    if row:
        out.update(state=STATE_MISSING, code=CODE_TARGET_MISSING, found=False,
                   why=(f"计划 {pid} 的台账行上记的是 `{row}`，而给出的路径是 `{text}` "
                        "⇒ 不是同一份（行上的回指没指到这一份）"))
        return out
    if disk:
        out.update(state=STATE_MISSING, code=CODE_TARGET_MISSING, found=False,
                   why=(f"`{disk}` 在盘上，但 `attack_plans` 里没有任何一行的 "
                        "`report_path` 指向它 ⇒ 只有文件没有台账行"))
        return out
    if text:
        out.update(state=STATE_MISSING, code=CODE_TARGET_MISSING, found=False,
                   why=(f"计划 {pid} 的行上 `report_path` 为空（老行不猜：不按计划号反推"
                        f" `attack-{pid}.md` 是否存在），盘上也没有 `{text}` ⇒ 没有对应稿"))
        return out
    out.update(state=STATE_MISSING, code=CODE_TARGET_MISSING, found=False,
               why=(f"计划 {pid} 的行上 `report_path` 为空/缺格（老行不猜：不按计划号反推"
                    f" `attack-{pid}.md` 是否存在）⇒ 台账没记它对应的稿"
                    "（没给路径 ⇒ 盘上那一份没查，不是「不存在」）"))
    return out


def attack_ledger_reading(rel: Any = "", *, plan_id: Any = "", root: Any = "",
                          cache: dict[Any, Any] | None = None) -> dict[str, Any]:
    """一份攻坚台账在台账里的回指读数（按文件读那一侧；判据在 :func:`attack_ledger_verdict`）。

    ## 三态（与 `ref_reading` 同一套纪律）

    | `state` | `checked` | 含义 |
    |---|---|---|
    | `ok` | True | 行上记着它、且路径与给出的那份是同一份 |
    | `missing` | True | 查过了：没有台账行 / 行上没记稿 / 行上记的是另一份 |
    | `unchecked` | False | 没查成（没有工作区根 / `attack_plans` 读不出来） |
    | `bad` | False | 形状不成立（给的路径不是这一族，也不是一个计划号） |

    `missing` 里那几种"没有"由 `why` 逐字分开（见 :func:`attack_ledger_verdict`），
    调用方按 `why` 认那一档是可以的 —— 但按码分支仍应看 `state`（`bad` 与
    `missing` 都是"不能用"，`unchecked` 不是）。
    """
    from . import refvocab as _RV

    parsed = attack_ledger_verdict(rel=rel, plan_id=plan_id)
    if parsed["state"] == STATE_BAD:
        return {**parsed, "checked": False}
    workspace = _RV._root_path(root)
    if workspace is None:
        return {**parsed, "checked": False, "state": STATE_UNCHECKED,
                "code": CODE_UNCHECKED,
                "why": "没有给工作区根 ⇒ 这一条没查成（不是「没有台账行」）"}
    got = _attack_index(workspace, _RV._cache_of(cache))
    if not got["checked"]:
        return {**parsed, "checked": False, "state": STATE_UNCHECKED,
                "code": CODE_UNCHECKED,
                "why": f"`data/attack_plans.json` 读不出来（{got['why']}）⇒ 没查成"}
    pid = str(parsed["plan_id"])
    verdict = attack_ledger_verdict(rel=rel, plan_id=plan_id,
                                    row_path=got["by_plan"].get(pid, ""),
                                    on_disk=got["on_disk"].get(pid, ""))
    return {**verdict, "checked": True}

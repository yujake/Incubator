# -*- coding: utf-8 -*-
"""四个只读读数（`draft/145` 之后这一层的形状，业主 2026-10-24 裁定的 B/F 两格）。

## 这一层为什么存在

"这个数是多少"在这套框架里出现过两种坏形态：

1. 同一个数在两个地方各算一遍（CLI 一份、网页一份）⇒ 两处读数分家，而没有任何一条判据
   会因此变红。真机教训：`status-report` 与网页的"在飞任务"曾经差一档。
2. "没读到"被折成 0 ⇒ 用户读到"这一趟 0 次错误"，而实际上是工作区根本不存在
   （三态纪律的反面，见 `AGENTS.md` 与 `noai_gate` 的退出码表）。

所以这一层只做一件事：把"读盘 ⇒ 一个带三态的 dict"收成一个口径。所有读数共用同一个
外层五键：

```text
{"checked": bool,      # 查过没有（False ⇒ 下面的 0 不是"没有"，是"没查成"）
 "state": str,         # "checked" / "unknown"（与 checked 一一对应，给只认字符串的消费者）
 "reason": str,        # state=unknown 时逐字说清哪一步没读成（checked 时为空串）
 "data": {...},        # 这一类读数自己的那张表（键集见本模块的 *_DATA_KEYS）
 "problems": [...]}    # 读到了、但人应该看见的异常（每条 {"code", "detail"}）
```

为什么 `state` 与 `checked` 同时给：三态纪律要的是"两个不同的东西不许用同一个值表示"，
而调用方有的只认布尔、有的只认字符串。两格由同一处同时写（`_envelope`），所以不会漂。

## 四条纪律（判据 `tests/test_readouts_are_the_single_shape.py` 钉的就是这四条）

1. 纯读：不写库、不写盘、不建目录、不加锁、零模型调用。
2. 不 import 呈现层：这里 import `webui` 或 `cli` 就会让"CLI 与网页读同一份"变成
   "CLI 与网页互相 import"——循环依赖只是症状，真正的问题是口径又有两个主人。
3. 没扫到 ≠ 没东西：读不到 ⇒ `checked=False` 且 `state="unknown"`，绝不给一张全 0 的表。
   反真空：把底下的 `scan` 打桩成空，四条读数必须一起变红（不能静默给 0）。
4. 空工作区是正控：初始化过、没有内容 ⇒ 全 0 且 `checked=True`。0 与 unknown 分得开，
   这一条与第 3 条是同一个口径的两面。

## 四条读数各自回答什么

| 读数 | 回答 | 数据源 | 出去的命令 |
|---|---|---|---|
| `errors_readout` | 每种角色犯了几次"错误动作"，各属哪一类 | 事件流的 `tasks` 行 + `sessions/*.jsonl` | `agentflow stats errors` |
| `flow_readout` | 每种角色做了哪些动作、被拦下多少、转投多少 | 同一份扫描（`agent_step` 的 `shape` / `result` + `agent_message`） | `agentflow stats flow` |
| `cost_readout` | 钱与 token 按角色、按阶段（`scope`）怎么分布 | `data/usage_ledger.json` | `agentflow stats cost` |
| `gates_readout` | 收工门八格各是什么状态（三态一张表） | `closing.check_closing`（现算，不读缓存） | `agentflow stats gates` |

`errors_readout` 的计数口径不在这里重写：它直接调 `errorstats.error_action_stats`（角色归属、
主码规则、三态都在那里有逐条注释）。本模块只负责"把它装进统一外层"，外加把同一份扫描
（`scan`）交给 `flow_readout` —— 两条读数看的是同一批记录，不存在两次读盘两个结果。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from . import errorstats as ES
from . import schema as S

#: 统一外层五个键（顺序即呈现顺序）。判据断言四条读数逐字给齐这五个。
READOUT_KEYS: tuple[str, ...] = ("checked", "state", "reason", "data", "problems")

#: `errors_readout` 的 `data` 键集（写进判据，多一个少一个都算口径漂了）。
ERRORS_DATA_KEYS: tuple[str, ...] = ("by_role", "role_total", "total", "categories", "sources")

#: `flow_readout` 的 `data` 键集。
FLOW_DATA_KEYS: tuple[str, ...] = ("roles", "totals")

#: `cost_readout` 的 `data` 键集（`by_role` 与 `by_scope` 是同一批行的两个切面）。
COST_DATA_KEYS: tuple[str, ...] = ("by_role", "by_scope", "total")

#: `gates_readout` 的 `data` 键集。
GATES_DATA_KEYS: tuple[str, ...] = ("cells", "counts", "machine_pass", "can_close", "verdict")

#: 读数名 → 它的 `data` 键集。判据从这一张表取期望值（不在测试里手抄第二份）。
READOUT_DATA_KEYS: dict[str, tuple[str, ...]] = {
    "errors": ERRORS_DATA_KEYS,
    "flow": FLOW_DATA_KEYS,
    "cost": COST_DATA_KEYS,
    "gates": GATES_DATA_KEYS,
}

#: `stats all` 那一档的 `data` 键集（就是四条读数的名字，顺序即呈现顺序）。
ALL_DATA_KEYS: tuple[str, ...] = ("errors", "flow", "cost", "gates")

#: 门那一格的三态取值（与 `closing.ClosingReport.status` 同一套词）。
CELL_STATES: tuple[str, ...] = ("pass", "fail", "unknown")


# ---------------------------------------------------------------- 外层


def _envelope(*, checked: bool, reason: str, data: dict[str, Any],
              problems: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """把一份读数装进统一外层（五键同时写，`state` 与 `checked` 不会漂）。

    `problems` 只收"读到了、但人该看见"的异常：它不改变 `checked`（读不成才改），
    否则"有一条没归类"会把整张表打成 unknown——那正好是第 3 条纪律的反面。
    """
    items = [dict(p) for p in problems]
    return {"checked": bool(checked),
            "state": "checked" if checked else "unknown",
            "reason": "" if checked else str(reason or "没查成"),
            "data": data,
            "problems": items}


def _problem(code: str, detail: str) -> dict[str, str]:
    return {"code": str(code), "detail": str(detail)}


def merge_readouts(parts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """把几条读数合成一条（`agentflow stats all` 用）。

    三态取合取：只要有一条没查成，合计这一条就是 `unknown`（部分成立不等于成立）。
    `data` 按读数名分栏（键集 `ALL_DATA_KEYS`）；`problems` 每条前面加上读数名，
    否则读的人看不出那条异常属于哪张表。

    为什么合取而不是"多数通过"：这一层唯一的消费者是"我该不该相信这几张表"，
    而"其中三张可信"不是一个能用一张表表达的状态。
    """
    named = {str(k): dict(v) for k, v in parts.items()}
    reasons = [f"{k}：{v.get('reason') or '没查成'}" for k, v in named.items()
               if not v.get("checked")]
    problems = [_problem(f"{k}:{p.get('code')}", str(p.get("detail") or ""))
                for k, v in named.items() for p in (v.get("problems") or ())]
    return _envelope(checked=not reasons, reason="；".join(reasons),
                     data={k: dict(v.get("data") or {}) for k, v in named.items()},
                     problems=problems)


# ---------------------------------------------------------------- 扫描（唯一入口）


def scan(target: Any, *, tables: Iterable[str] = ()) -> dict[str, Any]:
    """读一次盘：事件流 + 会话记录（＋点名的表）。四条读数共用这一份。

    `target` 既可以是工作区根路径，也可以是 `Store`（口径与 `errorstats` 一致：
    有 `read_events` 与 `root` 的对象就当 `Store` 用）。

    读盘的实现不在这里，而真身按来源分两处（2026-10-27，R-BE1 的 ②-1 更正）：
    事件流是 `errorstats._read_events`，会话记录是 `sessions.read_all_sessions`
    （`errorstats._read_sessions` 已改成对它的转发）。改前这句把两者都写成
    `errorstats` 的"唯一真身"，而 `sessions.read_session` 才是按 sid 的那条主线 ——
    两套实现对"读不明白"各有一套判定，同一份坏目录会给出两个数。
    本函数只把两处读数拼起来，不复制读取逻辑（复制出来的第二份迟早会与第一份对三态
    的判断不一样，而那正是这个模块存在的理由：口径只能有一个主人）。

    返回值里 `checked` 是"两个来源都读到了"（与 `error_action_stats` 的合取口径一致）；
    `store` 一格给 `gates_readout` 复用，不参与呈现。
    """
    root, store = ES._resolve_target(target)
    events, ev = ES._read_events(root, store)
    records, ss = ES._read_sessions(root)
    sources: dict[str, Any] = {"events": dict(ev), "sessions": dict(ss)}
    reasons = [str(s.get("reason") or "") for s in (ev, ss) if not s.get("checked")]
    checked = bool(ev.get("checked")) and bool(ss.get("checked"))
    out: dict[str, Any] = {"root": str(root), "store": store,
                           "events": events, "sessions": records,
                           "sources": sources, "checked": checked,
                           "reasons": [r for r in reasons if r]}
    if tables:
        out["tables"] = {name: _read_table(root, store, name) for name in tables}
    return out


def _read_table(root: Path, store: Any, table: str) -> dict[str, Any]:
    """读一张表（只读）。读不到 ⇒ `checked=False` 且逐字说清为什么。

    三态在这一层就分开：表文件不存在、表在但读不明白、读到了是 0 行，是三种不同的读数。
    "文件不存在"在初始化过的工作区里不是正常形态（`Store.init` 会写下每张空表），
    所以它记"没查成"，而不是"0 行"。
    """
    reading: dict[str, Any] = {"checked": False, "table": table, "rows": [], "count": 0,
                               "reason": ""}
    if store is None:
        if not isinstance(root, Path) or not root.is_dir():
            reading["reason"] = f"工作区不存在：{root}"
            return reading
        if not (root / "data").is_dir():
            reading["reason"] = f"没有 data/ 目录（这个目录不是工作区）：{root}"
            return reading
        path = root / "data" / f"{table}.json"
        if not path.exists():
            reading["reason"] = f"{table} 的表文件不存在：{path}（没初过？）"
            return reading
    try:
        if store is not None:
            rows = [dict(r) for r in store.rows(table)]
        else:
            from .store import Store

            rows = [dict(r) for r in Store(root).rows(table)]
    except Exception as e:  # noqa: BLE001 读不成 ⇒ 没查成（不许折成 0 行）
        reading["reason"] = f"{table} 读不到（{type(e).__name__}: {e}）"
        return reading
    reading.update(checked=True, rows=rows, count=len(rows), reason="")
    return reading


def _scan_problem(scan_result: Mapping[str, Any], *, need: tuple[str, ...] = ()) -> str:
    """这份扫描能不能当读数用：能就返回空串，不能就返回"为什么"。

    反真空的落点：底下的扫描被打桩成空（没有 `sources`）时，这里必须判"没查成"——
    "没扫到"不许被读成"扫过了、都是 0"。`need` 点名这条读数最少要看哪几个来源。
    """
    if not isinstance(scan_result, Mapping) or not scan_result.get("sources"):
        return "扫描没有报告任何来源（没扫到不等于没有东西；这份读数不成立）"
    sources = scan_result.get("sources") or {}
    missing = [name for name in need if name not in sources]
    if missing:
        return f"扫描缺了这些来源：{missing}（这份读数不成立）"
    skipped = [name for name in need if not (sources.get(name) or {}).get("checked")]
    if skipped:
        reasons: list[str] = []
        for name in skipped:
            one = str((sources.get(name) or {}).get("reason") or "")
            if one and one not in reasons:
                reasons.append(one)
        return "；".join(reasons) or f"这些来源没读到：{skipped}"
    return ""


# ---------------------------------------------------------------- 一、错误动作


def errors_readout(target: Any, *, scanned: Mapping[str, Any] | None = None,
                   ) -> dict[str, Any]:
    """按角色 × 类目的错误动作计数（口径全在 `errorstats`）。

    `data` 的五个键与 `errorstats.ErrorStats.as_dict()` 同名同义：`by_role` / `role_total` /
    `total` / `categories`（只留非 0 的类目合计，按类目表顺序）/ `sources`（逐源读数）。
    为什么把 `sources` 放进 `data`：这一层最常见的误读是"0 次错误"，而排查那件事第一步就是
    看"到底读了几条事件、几行读不明白"——它必须和计数在同一个对象里，才不会有人另算一份。

    `scanned`（2026-10-27，R-BE1 的 ⑥-5）：调用方已经读过一份扫描（`scan()`）时传进来，
    于是这一条不再自己读一遍盘。改前 `stats all` 一次跑四条，`events.jsonl` 与
    `sessions/*.jsonl` 因此各被读 4 遍。计数仍然走 `errorstats.error_action_stats_from`
    那一处（只有一份分类口径），本函数不复制它。
    """
    #: `errorstats` 那一支"从已读记录算"的接缝。用 `getattr` 而不是直接名字：
    #: 那个文件此刻正被另一条 lane 重写，函数可能一时不在 —— 不在就退回"自己读一遍"，
    #: 两条路给出同一份 `ErrorStats`（差别只有谁去读盘），所以退回不改任何读数。
    from_records = getattr(ES, "error_action_stats_from", None)
    if scanned is not None and from_records is not None:
        sources = scanned.get("sources") or {}
        stats = from_records(scanned.get("events"), sources.get("events"),
                             scanned.get("sessions"), sources.get("sessions"))
    else:
        # 单跑这一条时照旧：`error_action_stats` 自己就会读那两处（不重复读盘）。
        stats = ES.error_action_stats(target)
    data: dict[str, Any] = {"by_role": {r: dict(c) for r, c in stats.by_role.items()},
                            "role_total": dict(stats.role_total),
                            "total": int(stats.total),
                            "categories": dict(stats.categories()),
                            "sources": {k: dict(v) for k, v in stats.sources.items()}}
    problems: list[dict[str, str]] = []
    unclassified = int((stats.sources.get("events") or {}).get("unclassified") or 0)
    if unclassified:
        problems.append(_problem(
            "unclassified_refusal",
            f"{unclassified} 条被拒行的理由码不在 CODE_TABLE 里（未计入任何类目；"
            "要收进来就把它登记进 errorstats.CODE_TABLE）"))
    why = _scan_problem({"sources": stats.sources}, need=("events", "sessions"))
    if why:
        return _envelope(checked=False, reason=why or stats.reason, data=data,
                         problems=problems)
    return _envelope(checked=True, reason="", data=data, problems=problems)


# ---------------------------------------------------------------- 二、动作流


def _step_role(record: Mapping[str, Any]) -> str:
    return ES._role_name(record.get("role"))


def _step_shape(record: Mapping[str, Any]) -> str:
    """这一步的形状（`agent_loop.SHAPES` 的取值；没记 ⇒ 空串，不猜）。"""
    return str(record.get("shape") or "")


def _step_blocked(record: Mapping[str, Any]) -> bool:
    """这一步是不是"被拦下"：结果里有拒信原话/错误/问题码就算。

    口径与 `errorstats._step_text` 一致（同一个"拒信原话"的读法），但这里不需要归类，
    只需要布尔：`errorstats` 那边已经把"哪一类"数过了，这一条读数回答的是"多少步被拦"。
    """
    result = record.get("result")
    if isinstance(result, Mapping):
        for key in ("error", "problem", "refusal_reason"):
            if result.get(key):
                return True
        return False
    return bool(record.get("problem"))


#: 转投的记号（`errorstats` 的 `relay_after_refusal` 同一件事：被禁边拒掉之后发起的代唤）。
RELAY_SUBJECT = "代唤"


def flow_readout(target: Any, *, scanned: Mapping[str, Any] | None = None,
                 ) -> dict[str, Any]:
    """按角色的动作分布：做了多少步、各是什么形状、被拦下多少、转投多少。

    `data.roles[role]` 的四格：

    - `steps`：`agent_step` 的条数（这一角色在这台机器上真的走过多少步）；
    - `shapes`：形状 → 步数（`tool` / `summon` / `summon_many` / `message` / `handoff` /
      `note` / `ask_user` / `final` / `invalid`；`invalid` 是"模型给的形状认不出"）；
    - `blocked`：结果里带拒信原话/错误/问题码的步数（被判据或在写库那一刻拦下的都算）；
    - `relayed`：这一角色发出的 `agent_message` 里 subject 含"代唤"的条数（转投）。

    `data.totals` 是四个数的全角色合计。为什么不做"成功率"这类派生比率：口径一改就会
    悄悄改掉历史可比性（`EVAL_REQUIRED_FIELDS` 那一族的教训），比率留给读的人自己算。

    `scanned`：与 `errors_readout` 同一格（`stats all` 共读一份扫描，2026-10-27 ⑥-5）。
    """
    scanned = scan(target) if scanned is None else scanned
    why = _scan_problem(scanned, need=("events", "sessions"))
    roles: dict[str, dict[str, Any]] = {}
    problems: list[dict[str, str]] = []
    if not why:
        for record in scanned.get("sessions") or ():
            kind = str(record.get("kind") or "")
            role = _step_role(record)
            if kind == "agent_step":
                slot = roles.setdefault(role, {"steps": 0, "shapes": {}, "blocked": 0,
                                               "relayed": 0})
                slot["steps"] = int(slot["steps"]) + 1
                shape = _step_shape(record) or "（未记形状）"
                shapes = slot["shapes"]
                shapes[shape] = int(shapes.get(shape, 0)) + 1
                if _step_blocked(record):
                    slot["blocked"] = int(slot["blocked"]) + 1
            elif kind == "agent_message":
                subject = str(record.get("subject") or "")
                if RELAY_SUBJECT in subject:
                    sender = ES._role_name(record.get("from"))
                    slot = roles.setdefault(sender, {"steps": 0, "shapes": {}, "blocked": 0,
                                                     "relayed": 0})
                    slot["relayed"] = int(slot["relayed"]) + 1
        for name, src in (scanned.get("sources") or {}).items():
            broken = src.get("unreadable_files") or []
            if broken:
                problems.append(_problem(
                    "unreadable_session",
                    f"{name} 里有 {len(broken)} 个文件读不明白：{broken[:6]}"))
        if not roles:
            problems.append(_problem(
                "no_steps", "会话记录里没有任何 agent_step（这一趟还没有人走过一步）"))
    data: dict[str, Any] = {
        "roles": {r: {"steps": int(v["steps"]), "shapes": dict(sorted(v["shapes"].items())),
                      "blocked": int(v["blocked"]), "relayed": int(v["relayed"])}
                  for r, v in sorted(roles.items())},
        "totals": {"roles": len(roles),
                   "steps": sum(int(v["steps"]) for v in roles.values()),
                   "blocked": sum(int(v["blocked"]) for v in roles.values()),
                   "relayed": sum(int(v["relayed"]) for v in roles.values())},
    }
    if why:
        return _envelope(checked=False, reason=why, data=data, problems=problems)
    return _envelope(checked=True, reason="", data=data, problems=problems)


# ---------------------------------------------------------------- 三、钱


def _money(value: float) -> float:
    """美元留六位：同一批行在两次读数里必须打出一模一样的字（判据靠它）。"""
    return round(float(value or 0.0), 6)


def cost_readout(target: Any, *, scanned: Mapping[str, Any] | None = None,
                 ) -> dict[str, Any]:
    """`usage_ledger` 按角色、按阶段的花费与 token。

    `data.by_role[role]` 与 `data.by_scope[scope]` 是同一批行的两个切面，各含
    `usd` / `tokens_in` / `tokens_out` / `tokens_total` / `attempts` / `rows`；
    `data.total` 是同一形状的合计。

    为什么两个切面都要：`role` 回答"谁花的"，`scope`（`schema.USAGE_SCOPES`：summon /
    experiment / search / extract / review / reason）回答"花在哪件事上"。只给一个切面时，
    另一件事就得有人另算一份——而那正是本模块要收掉的形态。

    `scanned`：`stats all` 共读一份扫描（2026-10-27 ⑥-5）。那份扫描没带
    `usage_ledger` 时这里自己读这一张表（单跑 `stats cost` 走的就是这条路）。
    """
    scanned = scan(target, tables=("usage_ledger",)) if scanned is None else scanned
    why = _scan_problem(scanned, need=("events", "sessions"))
    table = ((scanned.get("tables") or {}).get("usage_ledger"))
    if table is None:
        table = _read_table(Path(str(scanned.get("root") or ".")),
                            scanned.get("store"), "usage_ledger")
    table = table or {}
    if not why and not table.get("checked"):
        why = str(table.get("reason") or "usage_ledger 读不到")

    def _empty() -> dict[str, Any]:
        return {"usd": 0.0, "tokens_in": 0, "tokens_out": 0, "tokens_total": 0,
                "attempts": 0, "rows": 0}

    by_role: dict[str, dict[str, Any]] = {}
    by_scope: dict[str, dict[str, Any]] = {}
    problems: list[dict[str, str]] = []
    unknown_scope = 0
    for row in (table.get("rows") or ()) if not why else ():
        role = ES._role_name(row.get("role"))
        scope = str(row.get("scope") or "")
        if scope not in S.USAGE_SCOPES:
            unknown_scope += 1
            scope = scope or "（未记阶段）"
        tokens_in = int(row.get("tokens_in") or 0)
        tokens_out = int(row.get("tokens_out") or 0)
        total = int(row.get("tokens_total") or 0) or (tokens_in + tokens_out)
        for slot_map, key in ((by_role, role), (by_scope, scope)):
            slot = slot_map.setdefault(key, _empty())
            slot["usd"] = _money(slot["usd"] + float(row.get("usd") or 0.0))
            slot["tokens_in"] = int(slot["tokens_in"]) + tokens_in
            slot["tokens_out"] = int(slot["tokens_out"]) + tokens_out
            slot["tokens_total"] = int(slot["tokens_total"]) + total
            slot["attempts"] = int(slot["attempts"]) + int(row.get("attempts") or 0)
            slot["rows"] = int(slot["rows"]) + 1
    if unknown_scope:
        problems.append(_problem(
            "unknown_scope",
            f"{unknown_scope} 行的 scope 不在 schema.USAGE_SCOPES 里（按原值单列，未并入任何阶段）"))
    total = _empty()
    for slot in by_role.values():
        for key in ("usd", "tokens_in", "tokens_out", "tokens_total", "attempts", "rows"):
            total[key] = _money(total[key] + slot[key]) if key == "usd" \
                else int(total[key]) + int(slot[key])
    data: dict[str, Any] = {"by_role": {r: dict(v) for r, v in sorted(by_role.items())},
                            "by_scope": {s: dict(v) for s, v in sorted(by_scope.items())},
                            "total": total}
    if why:
        return _envelope(checked=False, reason=why, data=data, problems=problems)
    return _envelope(checked=True, reason="", data=data, problems=problems)


# ---------------------------------------------------------------- 四、收工门


def gates_readout(target: Any, *, project_dir: str = "", report_path: str = "",
                  sid: str | None = None,
                  scanned: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """收工门八格的三态一张表（现算，不读任何人缓存过的结论）。

    `data.cells` 每格 `{"name", "status", "detail"}`：`status` 取 `pass` / `fail` / `unknown`
    （与 `closing.ClosingReport.status` 同一套词）；`detail` 是该格被拦时的原话（没有就是空串）。
    `data.counts` 是三态各几格；`data.machine_pass` 是"八格全 pass 且没有 blocker"这个旧口径
    （它只是读数：收工由 M 判，见 `closing.ClosingReport.can_close` 的注释）；
    `data.verdict` 是 M 那份判据（没有 ⇒ null，绝不编一个"通过了"）。

    为什么现算而不是读 `out/review/` 里上一次的结论：这张表回答的是"现在能不能交"，
    缓存过的结论回答的是"上一次能不能交"——两件事用同一个输出就是那次"内外读数分家"的重演。
    现算的代价是几次磁盘读，零模型调用。

    `project_dir` / `report_path` 不给 ⇒ 依赖它们的那几格如实记 `unknown`（不是 pass）。

    `scanned`：`stats all` 共读一份扫描（2026-10-27，R-BE1 的 ⑥-5）。门的"现算"不受影响 ——
    八格仍然在这次调用里现跑，这里复用的只是事件流/会话记录那份扫描（门本身不读它们，
    只用它的 `store`）。
    """
    scanned = scan(target) if scanned is None else scanned
    why = _scan_problem(scanned, need=("events", "sessions"))
    empty = {"cells": [], "counts": {s: 0 for s in CELL_STATES},
             "machine_pass": False, "can_close": False, "verdict": None}
    if why:
        return _envelope(checked=False, reason=why, data=empty)
    store = scanned.get("store")
    if store is None:
        try:
            from .store import Store

            store = Store(Path(str(scanned.get("root") or ".")))
        except Exception as e:  # noqa: BLE001 打不开工作区 ⇒ 没查成
            return _envelope(checked=False,
                             reason=f"打开工作区失败（{type(e).__name__}: {e}）", data=empty)
    from . import closing as CL

    try:
        report = CL.check_closing(store, project_dir=str(project_dir or ""),
                                  report_path=str(report_path or ""), sid=sid)
    except Exception as e:  # noqa: BLE001 门自己抛了 ⇒ 这一趟"没查成"，不是"没问题"
        return _envelope(checked=False,
                         reason=f"收工门没跑成（{type(e).__name__}: {e}）", data=empty)
    detail_of: dict[str, list[str]] = {}
    problems: list[dict[str, str]] = []
    for finding in report.findings:
        detail_of.setdefault(str(getattr(finding, "check", "")), []).append(
            str(getattr(finding, "detail", "") or ""))
        if str(getattr(finding, "level", "")) == "blocker":
            problems.append(_problem(str(getattr(finding, "code", "") or "blocker"),
                                     f"【{getattr(finding, 'check', '')}】"
                                     f"{getattr(finding, 'detail', '')}"))
    cells: list[dict[str, Any]] = []
    counts = {s: 0 for s in CELL_STATES}
    for name in CL.DEFAULT_CHECKS:
        status = str(report.status.get(name) or "unknown")
        if status not in CELL_STATES:
            status = "unknown"
        counts[status] = int(counts[status]) + 1
        cells.append({"name": name, "status": status,
                      "detail": "；".join(d for d in detail_of.get(name, []) if d)})
    data: dict[str, Any] = {"cells": cells, "counts": counts,
                            "machine_pass": bool(report.machine_pass),
                            "can_close": bool(report.can_close),
                            "verdict": dict(report.m_verdict) if report.m_verdict else None}
    return _envelope(checked=True, reason="", data=data, problems=problems)


#: 读数名 → 实现。`agentflow stats <名>` 与将来的网页都从这一张表取。
READOUTS = {"errors": errors_readout, "flow": flow_readout,
            "cost": cost_readout, "gates": gates_readout}


# ---------------------------------------------------------------- 人读的呈现


def _shown_width(text: str) -> int:
    """显示宽度（CJK 占两格）。表格对齐只靠它——靠 `len` 会把中文表头错开。"""
    shown = 0
    for ch in text:
        shown += 2 if ord(ch) > 0x2E7F else 1
    return shown


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _shown_width(text))


#: 人读表里那一列原话最多显示多少字（全文在 `--json` 的 `data.cells[].detail` 里）。
DETAIL_COL_CHARS = 46


def _clip(text: str, limit: int = DETAIL_COL_CHARS) -> str:
    """缩到 `limit` 字（超了打一个省略号）。只改呈现，不改 `data` 里的原文。"""
    one = " ".join(str(text or "").split())
    return one if len(one) <= limit else one[:limit] + "…"


def _table(head: list[str], rows: list[list[str]]) -> list[str]:
    """等宽小表（按显示宽度对齐；每列至少四格）。"""
    widths: list[int] = []
    for i in range(len(head)):
        widest = _shown_width(head[i])
        for row in rows:
            widest = max(widest, _shown_width(row[i]))
        widths.append(max(widest, 4))
    lines = ["  ".join(_pad(head[i], widths[i]) for i in range(len(head))).rstrip(),
             "  ".join("-" * widths[i] for i in range(len(head)))]
    lines += ["  ".join(_pad(row[i], widths[i]) for i in range(len(head))).rstrip()
              for row in rows]
    return lines


def _head(kind: str, readout: Mapping[str, Any]) -> list[str]:
    """每张表开头的四行（三态 + 读数 + 没查成时那句"0 不是没有"）。"""
    lines = [f"读数 {kind}（只读，零模型调用）",
             f"三态    checked={readout.get('checked')}  state={readout.get('state')}"]
    if readout.get("reason"):
        lines.append(f"原因    {readout.get('reason')}")
    if not readout.get("checked"):
        lines.append("没有读到该读的东西 ⇒ 下面这些 0 不是『没有』，是『没查成』。")
    return lines


def _problems_block(readout: Mapping[str, Any]) -> list[str]:
    items = list(readout.get("problems") or [])
    if not items:
        return []
    lines = ["", f"要看见的 {len(items)} 条："]
    lines += [f"  [{p.get('code')}] {p.get('detail')}" for p in items]
    return lines


def render_readout(kind: str, readout: Mapping[str, Any]) -> list[str]:
    """把一条读数渲染成人读的几行（CLI 与将来的网页共用这一份）。"""
    lines = _head(kind, readout)
    data = readout.get("data") or {}
    if kind == "errors":
        cats = list((data.get("categories") or {}).items())
        if not cats:
            lines.append("")
            lines.append("按角色 × 类目：全 0（一条判据都没命中）" if readout.get("checked")
                         else "按角色 × 类目：无可报读数")
        else:
            head = ["角色"] + [c for c, _n in cats] + ["合计"]
            rows = [[role] + [str((data["by_role"].get(role) or {}).get(c, 0)) for c, _n in cats]
                    + [str((data.get("role_total") or {}).get(role, 0))]
                    for role in sorted(data.get("role_total") or {})]
            rows.append(["合计"] + [str(n) for _c, n in cats] + [str(data.get("total", 0))])
            lines += ["", *_table(head, rows)]
            lines += ["", "类目释义："]
            meanings = dict(ES.ERROR_CATEGORIES)
            lines += [f"  {c}: {meanings.get(c, '')}" for c, _n in cats]
    elif kind == "flow":
        roles = data.get("roles") or {}
        if not roles:
            lines += ["", "按角色的动作：无人走过一步" if readout.get("checked")
                      else "按角色的动作：无可报读数"]
        else:
            head = ["角色", "步数", "被拦", "转投", "形状分布"]
            rows = [[role, str(v.get("steps", 0)), str(v.get("blocked", 0)),
                     str(v.get("relayed", 0)),
                     " ".join(f"{k}={n}" for k, n in (v.get("shapes") or {}).items())]
                    for role, v in roles.items()]
            t = data.get("totals") or {}
            rows.append(["合计", str(t.get("steps", 0)), str(t.get("blocked", 0)),
                         str(t.get("relayed", 0)), ""])
            lines += ["", *_table(head, rows)]
    elif kind == "cost":
        for label, key in (("按角色", "by_role"), ("按阶段（scope）", "by_scope")):
            slots = data.get(key) or {}
            lines += ["", f"{label}："]
            if not slots:
                lines.append("  （0 行：一分钱都没记过）" if readout.get("checked")
                             else "  （没查成，无读数）")
                continue
            head = ["名字", "美元", "token 进", "token 出", "token 合计", "尝试", "行数"]
            rows = [[name, f"{v.get('usd', 0):.6f}", str(v.get("tokens_in", 0)),
                     str(v.get("tokens_out", 0)), str(v.get("tokens_total", 0)),
                     str(v.get("attempts", 0)), str(v.get("rows", 0))]
                    for name, v in slots.items()]
            lines += _table(head, rows)
        total = data.get("total") or {}
        lines += ["", "合计：" + (f"{total.get('usd', 0):.6f} 美元 / "
                                 f"{total.get('tokens_total', 0)} token / "
                                 f"{total.get('rows', 0)} 行"
                                 if readout.get("checked") else "（没查成）")]
    elif kind == "gates":
        cells = data.get("cells") or []
        if not cells:
            lines += ["", "收工门八格：没有读数" if readout.get("checked") else "收工门八格：没查成"]
        else:
            head = ["格", "三态", "原话（缩 46 字，全文见 --json）"]
            rows = [[c.get("name", ""), c.get("status", ""), _clip(str(c.get("detail") or ""))]
                    for c in cells]
            lines += ["", *_table(head, rows)]
            counts = data.get("counts") or {}
            lines += ["", "计数：" + "  ".join(f"{s}={counts.get(s, 0)}" for s in CELL_STATES),
                      f"机器口径 machine_pass={bool(data.get('machine_pass'))}；"
                      f"M 判据 can_close={bool(data.get('can_close'))}"]
            verdict = data.get("verdict")
            if verdict:
                lines.append(f"M 的判据：met={verdict.get('met')} "
                             f"目标={verdict.get('goal') or '（没写）'} "
                             f"依据={verdict.get('basis') or '（没写）'}")
            else:
                lines.append("M 的判据：没有人判过（这一格是 unknown，不是『通过』）")
    else:  # pragma: no cover - 读数名只由 READOUTS 产生
        lines.append(f"（没有这个读数：{kind}）")
    lines += _problems_block(readout)
    return lines

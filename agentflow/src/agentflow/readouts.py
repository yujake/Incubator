# -*- coding: utf-8 -*-
"""四个只读读数（这一层的形状，业主裁定的 B/F 两格）。

## 这一层为什么存在

"这个数是多少"在这套框架里出现过两种坏形态：同一个数在两处各算一遍（CLI 一份、网页一份，
两处读数分家而没有任何判据会红 —— `status-report` 与网页的"在飞任务"曾差一档）；
以及"没读到"被折成 0（用户读到"这一趟 0 次错误"，而工作区根本不存在）。

所以这一层只做一件事：把"读盘 ⇒ 一个带三态的 dict"收成一个口径。所有读数共用同一个
外层五键：

```text
{"checked": bool,      # 查过没有（False ⇒ 下面的 0 不是"没有"，是"没查成"）
 "state": str,         # "checked" / "unknown"（与 checked 一一对应，给只认字符串的消费者）
 "reason": str,        # state=unknown 时逐字说清哪一步没读成（checked 时为空串）
 "data": {...},        # 这一类读数自己的那张表（键集见本模块的 *_DATA_KEYS）
 "problems": [...]}    # 读到了、但人应该看见的异常（每条 {"code", "detail"}）
```

为什么 `state` 与 `checked` 同时给：调用方有的只认布尔、有的只认字符串；两格由 `_envelope` 同时写，所以不会漂。

## 四条纪律（判据 `tests/test_readouts_are_the_single_shape.py` 钉的就是这四条）

1. 纯读：不写库、不写盘、不建目录、不加锁、零模型调用。
2. 不 import 呈现层：import `webui` / `cli` 就等于口径又有了两个主人（循环依赖只是症状）。
3. 没扫到 ≠ 没东西：读不到 ⇒ `checked=False` 且 `state="unknown"`，绝不给一张全 0 的表；
   反真空：把底下的 `scan` 打桩成空，四条读数必须一起变红。
4. 空工作区是正控：初始化过、没有内容 ⇒ 全 0 且 `checked=True`。0 与 unknown 分得开。

## 四条读数各自回答什么

| 读数 | 回答 | 数据源 | 出去的命令 |
|---|---|---|---|
| `errors_readout` | 每种角色犯了几次"错误动作"，各属哪一类 | 事件流的 `tasks` 行 + `sessions/*.jsonl` | `agentflow stats errors` |
| `flow_readout` | 每种角色做了哪些动作、被拦下多少、转投多少 | 同一份扫描（`agent_step` 的 `shape` / `result` + `agent_message`） | `agentflow stats flow` |
| `cost_readout` | 钱与 token 按角色、按阶段（`scope`）怎么分布 | `data/usage_ledger.json` | `agentflow stats cost` |
| `gates_readout` | 收工门八格各是什么状态（四态一张表：pass / fail / unknown / na） | `closing.check_closing`（现算，不读缓存） | `agentflow stats gates` |

`errors_readout` 的计数口径不在这里重写：它直接调 `errorstats.error_action_stats`（角色归属、
主码规则、三态都在那里有逐条注释）。本模块只把它装进统一外层，并把同一份扫描交给 `flow_readout`。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from . import errorstats as ES
from . import schema as S

#: 统一外层五个键（顺序即呈现顺序）。判据断言四条读数逐字给齐这五个。
READOUT_KEYS: tuple[str, ...] = ("checked", "state", "reason", "data", "problems")

#: `errors_readout` 的 `data` 键集（写进判据，多一个少一个都算口径漂了）。
#:
#: 扩面：前五个键是原有的（`total` 仍是角色侧总数，语义一个字没改）；
#: 后面几组是新的三类读数 + 逐类三态 + 每条 source 的样本。三组数刻意不相加：
#: `total`（谁做错了）/ `system_total`（系统哪里坏了）/ `state_readings_total`
#: （现在积着什么）是三种单位（`errorstats` 模块 docstring 第二节）。
ERRORS_DATA_KEYS: tuple[str, ...] = (
    "by_role", "role_total", "total", "categories", "sources",
    "system", "system_total", "state_readings", "state_readings_total",
    "classes", "class_state", "samples", "run_boundary",
)

#: `flow_readout` 的 `data` 键集。
FLOW_DATA_KEYS: tuple[str, ...] = ("roles", "totals")

#: `cost_readout` 的 `data` 键集（`by_role` 与 `by_scope` 是同一批行的两个切面）。
COST_DATA_KEYS: tuple[str, ...] = ("by_role", "by_scope", "total")

#: `gates_readout` 的 `data` 键集。
#:
#: `refusal`：`None` = 门真的跑了；非空 = 受控拒绝（会话号不在
#: 盘上 / 不是一个号），那一份 data 里的 `cells` 是空的而不是八格 `unknown` ——
#: "门根本没跑"与"跑了、八格都没查成"必须长得不一样。
GATES_DATA_KEYS: tuple[str, ...] = ("cells", "counts", "machine_pass", "m_says_done",
                                    "can_close", "closable", "verdict",
                                    "closing_verdict", "refusal")

#: 读数名 → 它的 `data` 键集。判据从这一张表取期望值（不在测试里手抄第二份）。
READOUT_DATA_KEYS: dict[str, tuple[str, ...]] = {
    "errors": ERRORS_DATA_KEYS,
    "flow": FLOW_DATA_KEYS,
    "cost": COST_DATA_KEYS,
    "gates": GATES_DATA_KEYS,
}

#: `stats all` 那一档的 `data` 键集（就是四条读数的名字，顺序即呈现顺序）。
ALL_DATA_KEYS: tuple[str, ...] = ("errors", "flow", "cost", "gates")

#: 门那一格的四态取值（与 `closing.ClosingReport.status` 同一套词）。
#:
#: 为什么有四档（补 `na`）：这里曾经只有 `pass` / `fail` / `unknown`，
#: 而 `closing` 早就会写第四档 `na`（`load_bearing` 在「形式化已关闭」的项目上
#: 记 `na`，closing.py 的 `rep.status["load_bearing"] = "na"`）。于是 `gates_readout`
#: 在 :531 把它折成 `unknown` —— 同一现场两个读口给出两种 counts。
#: 旧工作区里 `load_bearing` 那一格大量是 `na` ⇒ 不是某个工作区的怪数据，
#: 是这个词表少了一档（每一份收工门读数都被折了同一格）。
#:
#: 四档各自的语义（`unknown` 与 `na` 是两件不同的事，不许互相折）：
#:
#: - `pass`：查过了，这一格成立；
#: - `fail`：查过了，这一格不成立（拦住）；
#: - `unknown`：没查成 —— 跑了但读不成；或缺了它依赖的入参（如没给项目根 /
#:   报告路径）；或台账读不出来。它说的永远是"我们不知道"，不是"不成立"；
#: - `na`：不适用 —— 这一档对这个项目天然不成立（例如「形式化已关闭」的项目
#:   没有承重结论要 T3 背书）。它是读数，不是"没查成"：把 `na` 读成 `unknown`
#:   等于把「这一档不存在」说成「我们没查」。
#:
#: 折平哪一种都有代价：`na → unknown` 让"不适用"混进"没查成"（格子的原话写着
#: "不适用"，状态栏却写 unknown）；`na → pass` 更糟（把"不用查"
#: 说成"查过了没问题"）。词表是这一层唯一的口径主人，所以补在词表上、而不是在
#: `gates_readout` 里给某一格特判。
CELL_STATES: tuple[str, ...] = ("pass", "fail", "unknown", "na")


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

    读盘的实现不在这里，而真身按来源分两处：
    事件流是 `errorstats._read_events`，会话记录是 `sessions.read_all_sessions`
    （`errorstats._read_sessions` 已改成对它的转发）。把两者都写成
    `errorstats` 的"唯一真身"会漏掉 `sessions.read_session` 那条按 sid 的主线 ——
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

    `data` 的键与 `errorstats.ErrorStats.as_dict()` 同名同义：`by_role` / `role_total` /
    `total`（角色侧总数，语义与扩面前逐字相同）/ `categories`（只留非 0 的类目合计，
    按类目表顺序）/ `sources`（逐源读数）。为什么把 `sources` 放进 `data`：这一层最常见的
    误读是"0 次错误"，而排查那件事第一步就是看"到底读了几条事件、几行读不明白"——
    它必须和计数在同一个对象里，才不会有人另算一份。

    扩面（业主「覆盖面有些小了」）加的三组，刻意不相加：

    - `system` / `system_total`：系统侧（hook 没判成 / 外部面掉了 / 收工门拦下）；
    - `state_readings` / `state_readings_total`：状态读数（板项没被 ack，快照会回落）；
    - `classes` / `class_state` / `samples`：逐类的 `{count, bucket, state, reason, by_role}`
      与每一类前 N 条的 `{source, ref, ts, detail}` —— 页面"按类"与"展开到每条的 source"
      两段吃这一份，网页不另算一份口径。

    `scanned`：调用方已经读过一份扫描（`scan()`）时传进来，
    于是这一条不再自己读一遍盘。扩面新读的四个目录不进 `scan()`（只有这条读数要用），
    在这里单列读一次 —— 整条读数仍然只读一遍盘。
    """
    #: `errorstats` 那一支"从已读记录算"的接缝。用 `getattr` 而不是直接名字：
    #: 那个文件此刻正被另一条 lane 重写，函数可能一时不在 —— 不在就退回"自己读一遍"，
    #: 两条路给出同一份 `ErrorStats`（差别只有谁去读盘），所以退回不改任何读数。
    from_records = getattr(ES, "error_action_stats_from", None)
    if scanned is not None and from_records is not None:
        sources = scanned.get("sources") or {}
        # 扩面新源（`verifications/` / `out/roster/` / `out/secretary/` / 收工门现算）：
        # 与"事件流 / 会话记录"不同，它们只有这一条读数要用，所以不进 `scan()`（进了
        # `flow` / `cost` / `gates` 会白读）；这里单列读一次，于是整条读数仍然只读一遍盘。
        aux = ES._read_aux(Path(str(scanned.get("root") or target)))
        stats = from_records(scanned.get("events"), sources.get("events"),
                             scanned.get("sessions"), sources.get("sessions"), aux=aux)
    else:
        # 单跑这一条时照旧：`error_action_stats` 自己就会读那两处（不重复读盘）。
        stats = ES.error_action_stats(target)
    # `by_class()` 每次现算全部类目 × 角色；这条读数要用它两处（classes / unknown）。
    classes = stats.by_class()
    data: dict[str, Any] = {"by_role": {r: dict(c) for r, c in stats.by_role.items()},
                            "role_total": dict(stats.role_total),
                            "total": int(stats.total),
                            "categories": dict(stats.categories()),
                            "sources": {k: dict(v) for k, v in stats.sources.items()},
                            "system": dict(stats.system_categories()),
                            "system_total": int(stats.system_total),
                            "state_readings": {r: dict(c) for r, c
                                               in stats.state_readings.items()},
                            "state_readings_total": int(stats.state_readings_total),
                            "classes": [dict(one) for one in classes],
                            "class_state": {k: dict(v) for k, v in stats.class_state.items()},
                            "samples": {k: [dict(s) for s in v]
                                        for k, v in stats.samples.items()},
                            "run_boundary": str(stats.run_boundary)}
    problems: list[dict[str, str]] = []
    unclassified = int((stats.sources.get("events") or {}).get("unclassified") or 0)
    if unclassified:
        problems.append(_problem(
            "unclassified_refusal",
            f"{unclassified} 条被拒行的理由码不在 CODE_TABLE 里（未计入任何类目；"
            "要收进来就把它登记进 errorstats.CODE_TABLE）"))
    loose = {k: int(v or 0) for k, v in (stats.sources.get("unclassified") or {}).items()
             if int(v or 0)}
    if loose:
        problems.append(_problem(
            "unclassified_signal",
            f"结构判据认不出族的那几条没有猜类目：{loose}（各自的那一类里没加数；"
            "要收进来就给 errorstats 的族表补一条原话）"))
    unknown = [one["category"] for one in classes
               if str(one.get("state") or "") == "unknown"]
    if unknown:
        # 三态纪律：没查到的那几类必须点名，否则页面上的 0 会被读成"这一类没事"。
        problems.append(_problem(
            "classes_unknown",
            f"{len(unknown)} 个类目没查成（不是 0）：{'、'.join(unknown[:6])}"
            f"{'…' if len(unknown) > 6 else ''}"))
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

    `scanned`：与 `errors_readout` 同一格（`stats all` 共读一份扫描）。
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

    `scanned`：`stats all` 共读一份扫描（那份扫描没带
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


def gate_cells(report: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """收工门八格的逐格读数与四档计数 —— 这台计算机器只有一份实现。

    ## 为什么要有这个函数（口径题，不是重构）

    八格读数有两个出口：命令行 `agentflow stats gates` 走 :func:`gates_readout`，
    网页 `/api/package` 与 `/api/acceptance` 走 `webui/readers.py::_closing_block`。
    改前两处各写一遍同一个循环（遍历 `closing.DEFAULT_CHECKS`、把词表外的状态折成
    `unknown`、逐档累加）⇒"同一份 `rep.status` 数出两个 counts"没有结构保证（一处改了
    归一化规则，另一处照旧，两边都"对"）。现在两边都只调这一个函数：
    输入 `closing.ClosingReport`、输出 `(cells, counts)`，不读盘、不看第几端。

    ## 形状

    - `cells[i] = {"name", "status", "detail"}`，顺序就是 `closing.DEFAULT_CHECKS`；
      `detail` 是该格被拦时那几条 finding 的原话（用顿号连起来，没有就是空串）；
    - `counts` 的键就是 :data:`CELL_STATES` 四档，值各几格，八格加起来等于格数。

    网页那端还给每格补 `source`（原文落点）：那是网页的呈现面，在这一份读数之外补，不许反过来改格形状。
    """
    from . import closing as CL

    detail_of: dict[str, list[str]] = {}
    for finding in (getattr(report, "findings", []) or []):
        detail_of.setdefault(str(getattr(finding, "check", "")), []).append(
            str(getattr(finding, "detail", "") or ""))
    cells: list[dict[str, Any]] = []
    counts = {s: 0 for s in CELL_STATES}
    for name in CL.DEFAULT_CHECKS:
        status = str((getattr(report, "status", {}) or {}).get(name) or "unknown")
        if status not in CELL_STATES:
            status = "unknown"
        counts[status] = int(counts[status]) + 1
        cells.append({"name": name, "status": status,
                      "detail": "；".join(d for d in detail_of.get(name, []) if d)})
    return cells, counts


def gates_readout(target: Any, *, project_dir: str = "", report_path: str = "",
                  sid: str | None = "",
                  scanned: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """收工门八格的四态一张表（现算，不读任何人缓存过的结论）。

    `data.cells` 每格 `{"name", "status", "detail"}`：`status` 取 :data:`CELL_STATES`
    的四档（`pass` / `fail` / `unknown` / `na`，与 `closing.ClosingReport.status` 同一套词）；
    `detail` 是该格被拦时的原话（没有就是空串）。`na` 与 `unknown` 分得开是这一格的
    硬口径：前者是"这一档对这个项目天然不成立"，后者是"没查成"—— 折在一起时，同一份
    现场在 `agentflow closing` 与 `agentflow stats gates` 两个出口会给出两套 counts。
    `data.counts` 是这四档各几格（逐格等于 `closing` 侧 `rep.status` 的分布）；
    `data.machine_pass` 是"八格全 pass 且没有 blocker"这个旧口径
    （它只是读数：收工由 M 判，见 `closing.ClosingReport.can_close` 的注释）；
    `data.verdict` 是 M 那份判据（没有 ⇒ null，绝不编一个"通过了"）。

    为什么现算而不是读上一次落盘的结论：那回答"上一次能不能交"，与"现在"是两件事（同一个输出就是"内外读数分家"的重演）；代价只是几次磁盘读，零模型调用。

    `project_dir` / `report_path` 不给 ⇒ 依赖它们的那几格如实记 `unknown`（不是 pass）。

    `sid` 三态（缺省不是 `None`）：不给 ⇒ `closing.NO_SESSION`（没有运行号）⇒ `user_pending`
    记 `unknown` 并在 `problems` 里点名 —— 真机上缺省会话（`sessions/<今天>.jsonl`）106/107
    不存在，按它读会把"问了还没答"读成 pass；显式给 `None` 才是运维口径，某一趟就显式给号。

    `sid` 给了一个盘上不存在的号 ⇒ 受控拒绝：`checked=False`、
    `reason` 就是 CLI 那一句原话、`data.refusal` 带 `{"code","sid","detail","exit_code": 2}`，
    `data.cells` 为空（门根本没跑，不是"八格全是 unknown"的空读数）。这一档与
    `agentflow closing` 共用 `closing.closing_session_identity`，所以两个出口同文同码。
    机器口径的两个喂参也在这里现算（`closing.machine_feeders`）—— API 出口不喂 ⇒
    同一份工作区在 API 算出 `can_close=None`、在 CLI 算出 True/False（"一个说不知道、
    一个说可以交"）。

    `scanned`：`stats all` 共读一份扫描（复用的只是事件流/会话记录那份，门只用它的 `store`），八格仍然现跑。
    """
    scanned = scan(target) if scanned is None else scanned
    why = _scan_problem(scanned, need=("events", "sessions"))
    empty = {"cells": [], "counts": {s: 0 for s in CELL_STATES},
             "machine_pass": False, "m_says_done": False, "can_close": None,
             "closable": False, "verdict": None, "closing_verdict": None,
             "refusal": None}
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

    # 没给运行号（`closing.NO_SESSION` 或其空白变体）⇒ 这一格问不出来，下面还要点名；
    # `None` 不算"没给"：它是判据层的运维口径（读缺省会话），见 docstring 的 `sid` 三态。
    no_sid = sid is not None and not str(sid).strip()

    # 机器口径的两个喂参：CLI 与工具体都喂这一份；这一条读数
    # 不喂 ⇒ 同一份工作区在 API 出口算出 `can_close=None`、在 CLI 出口算出
    # True/False（"一个说不知道、一个说可以交"）。现在三个出口走同一个
    # `closing.machine_feeders`（口径只有一处）。
    feed = CL.machine_feeders(store)
    try:
        report = CL.check_closing(store, project_dir=str(project_dir or ""),
                                  report_path=str(report_path or ""), sid=sid,
                                  retire=feed.get("retire"), programs=feed.get("programs"))
    except Exception as e:  # noqa: BLE001 门自己抛了 ⇒ 这一趟"没查成"，不是"没问题"
        return _envelope(checked=False,
                         reason=f"收工门没跑成（{type(e).__name__}: {e}）", data=empty)
    # ---- 受控拒绝：号不在盘上 ⇒ 门根本没跑。
    #
    # 这一档不许折成"八格全是 unknown 的一张表"（那是空读数）：`checked=False` +
    # 原话进 `reason`，`data.refusal` 带 code/sid/exit_code —— CLI 那边是同一句话、
    # 同一个码（2），两个出口拒绝同一件事。
    if report.refusal:
        refused = dict(report.refusal)
        data = dict(empty, refusal=refused)
        return _envelope(checked=False, reason=str(refused.get("detail") or ""),
                         data=data,
                         problems=[_problem(str(refused.get("code") or "refusal"),
                                            str(refused.get("detail") or ""))])
    problems: list[dict[str, str]] = []
    for finding in report.findings:
        if str(getattr(finding, "level", "")) == "blocker":
            problems.append(_problem(str(getattr(finding, "code", "") or "blocker"),
                                     f"【{getattr(finding, 'check', '')}】"
                                     f"{getattr(finding, 'detail', '')}"))
    if no_sid:
        problems.append(_problem("no_session", (
            "没给运行号（sid）⇒ 待答问题那一格只能是 unknown（不是 pass）：没给号就没有对象，"
            "不能按缺省会话猜。要看工作区整体在等什么用 `agentflow inbox`（它扫全部会话）；"
            "要看某一趟用 `agentflow closing --sid <号>`（或 API `gates_readout(sid=…)`）。")))
    # 逐格与计数只从这一处取（与网页那头同一个函数，见 `gate_cells` 的注释）。
    cells, counts = gate_cells(report)
    # 一份权威结论（ROOTGATE-②）：`closing_verdict` 是唯一判据；`verdict` 这个键
    # 早已是 M 的 `m_verdict`，所以权威结论另起一格，两个名字不混。
    authoritative = getattr(report, "verdict", None)
    data: dict[str, Any] = {
        "cells": cells, "counts": counts,
        "machine_pass": bool(report.machine_pass),
        # `m_says_done` 是 M 的判断；`can_close` 是机器口径
        # （`bool | None`，`None` = 没接线 —— 不许折成 False，那会被读成"机器说不通过"）。
        "m_says_done": bool(report.m_says_done),
        "can_close": report.can_close,
        "closable": bool(report.closable),
        "verdict": dict(report.m_verdict) if report.m_verdict else None,
        "closing_verdict": (dict(authoritative)
                            if isinstance(authoritative, Mapping) else None),
        "refusal": None,
    }
    return _envelope(checked=True, reason="", data=data, problems=problems)


#: 读数名 → 实现。`agentflow stats <名>` 与将来的网页都从这一张表取。
READOUTS = {"errors": errors_readout, "flow": flow_readout,
            "cost": cost_readout, "gates": gates_readout}


# ---------------------------------------------------------------- 人读的呈现


#: 等宽小表不在这里实现：`errorstats._table_lines` 是唯一真身（本模块与
#: `agentflow stats` 的文本输出共用同一份对齐规则）。2026-11-19 SPLITREAD：
#: 此前 `_shown_width` / `_pad` / `_table` 是那一份的逐行副本，只在 docstring 上不同。
#: 调用点一律写 `ES._table_lines(...)` —— 走模块属性而不是 `from ... import`，
#: 这样把 `errorstats` 那一份打成空表时，这里的表也跟着消失（判据的机器读数）。


#: 人读表里那一列原话最多显示多少字（全文在 `--json` 的 `data.cells[].detail` 里）。
DETAIL_COL_CHARS = 46


def _clip(text: str, limit: int = DETAIL_COL_CHARS) -> str:
    """缩到 `limit` 字（超了打一个省略号）。只改呈现，不改 `data` 里的原文。"""
    one = " ".join(str(text or "").split())
    return one if len(one) <= limit else one[:limit] + "…"


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
            lines += ["", *ES._table_lines(head, rows)]
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
            lines += ["", *ES._table_lines(head, rows)]
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
            lines += ES._table_lines(head, rows)
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
            # 列名逐字是「四态」：这一格的值域就是 `CELL_STATES` 的四档。写成「三态」
            # 会让读的人以为 `na` 是别的什么东西（它曾被折进 `unknown`）。
            head = ["格", "四态", "原话（缩 46 字，全文见 --json）"]
            rows = [[c.get("name", ""), c.get("status", ""), _clip(str(c.get("detail") or ""))]
                    for c in cells]
            lines += ["", *ES._table_lines(head, rows)]
            counts = data.get("counts") or {}
            lines += ["", "计数：" + "  ".join(f"{s}={counts.get(s, 0)}" for s in CELL_STATES),
                      f"机器口径 machine_pass={bool(data.get('machine_pass'))}；"
                      f"M 判据 m_says_done={bool(data.get('m_says_done'))}，"
          f"机器口径 can_close={data.get('can_close')!r}"]
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

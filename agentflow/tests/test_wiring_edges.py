"""接线判据：今晚这批新功能必须挂在真机调用图上，且这件事要有一条会红的判据。

## 这一份守的是什么

业主 2026-10-27 的话是这一类缺陷的唯一权威：「有极大概率你的那些子代理们把功能实现好
以后未接线，请务必检查接线」。它描述的是一个具体的失败形态：

    函数写好了、单测也绿了，可是没有任何真机路径会调它。

这种形态在任何一条既有判据里都看不见 —— 单测自己塞调用方，所以它永远是绿的。已经
量到过的实例：`clock.park_state`（只作为读数被读，从不参与控制流，见
`docs/WIRING-AUDIT-2026-10-27.md`）。2026-10-27 晚的另两只是
`secretary.proof_route_of` / `proof_routes_of`（读侧唯一口径，全仓 0 个非测试调用点）
—— 它们已在本轮接上读侧，台账因此清空。

本文件把「谁在活着的那条路上调它」做成源码级判据：一张表（`WIRED`）+ 一个走一遍
AST 就能算出来的可达集 + 一个反向核对（发现的空集必须等于 `KNOWN_ORPHANS`）。

## 边的三种形态（少算一种就会误报 ORPHAN）

真机里"被调用"不只是 `f(...)` 这一种写法。本仓实测有三种，三种都要算边：

1. 调用：`f(...)` / `obj.f(...)`；
2. 裸引用：`sessions.set_append_hook(_observe_session_event)`、`clock.set_due_handler(_deliver_due)`
   —— 挂点型接线，函数体以后再被调用。只算调用会把 `observe_work` 判成孤儿
   （它唯一的入口就是这个挂点）；
3. 工厂默认值：`sleep = sleep or self._default_sleep` —— 引用之后经 `self._sleep(...)` 调用。
   只算调用会把 `fetch._default_sleep` 判成孤儿。

## 入口集（真机可达的起点）

- `cli.py` 里 `cmd_*` 那些子命令处理器（`set_defaults(func=cmd_xxx)` 是 argparse 的挂点，
  静态看不见）；
- `host.py` 的全部函数（装配线本身）；
- 带 `tool` 装饰器的函数（模型按名字从注册表里取，静态也看不见）。

三者都是"真机入口"，但它们都不是"静态可解析的调用边" ⇒ 必须显式种进可达集，否则整片
工具体会被判成不可达。

## 误差方向（这一条必须写清，否则判据会骗人）

- 本判据只做名字解析，不做类型解析 ⇒ 同名函数会互相"借"可达性。它的误差方向是
  "把不可达读成可达"（宁可漏报），不会因为同名而把可达读成不可达；
- 反过来，经 `getattr(名字)` / 字符串表 / 反射得到的边看不见 ⇒ 会误报 ORPHAN。所以
  每条 `KNOWN_ORPHANS` 都带一句理由，且台账必须与实测集合相等：有人真把它接上，
  这一条会红（接线事件要人看见），有人新造一条孤儿，这一条也会红。
"""
from __future__ import annotations

import ast
import functools
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"


# ============================================================ 图

def _parse(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


class _Collect(ast.NodeVisitor):
    """一遍 AST 收三样：定义点、调用边、裸引用边（都带所在函数）。"""

    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.stack: list[str] = []
        self.defs: list[dict] = []
        self.edges: list[tuple[str, str, int, str]] = []   # (caller, callee, line, kind)

    def _qual(self) -> str:
        return ".".join(self.stack) or "<module>"

    def _enter(self, name: str) -> None:
        self.stack.append(name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.defs.append({"rel": self.rel, "line": node.lineno, "name": node.name,
                          "qual": ".".join(self.stack + [node.name]),
                          "decos": [ast.unparse(d) for d in node.decorator_list]})
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name:
            self.edges.append((self._qual(), name, node.lineno, "call"))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # 裸引用（`f` 作为值被传出去）。`Load` 才算：`Store` 是赋值目标，不是边。
        if isinstance(node.ctx, ast.Load):
            self.edges.append((self._qual(), node.id, node.lineno, "ref"))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # `obj.attr` 里 attr 作为值被取出（`self._default_sleep` / `SS.set_append_hook`）。
        if isinstance(node.ctx, ast.Load):
            self.edges.append((self._qual(), node.attr, node.lineno, "ref"))
        self.generic_visit(node)


def _graph_of(pairs: list[tuple[str, ast.Module]]) -> dict:
    """把若干（相对路径, AST）收成与 `graph()` 同形的接线图。

    为什么抽出这一层：反真空那一条要拿"语义相反的两棵树"去喂 `entries()` /
    `reachable()` / `is_live()` 本身。喂 AST 而不是喂现成的图，是为了让被量的
    那几步（收边、种入口、闭包）真的跑一遍，而不是用例自己手搭一份图再自证。
    """
    defs: dict[str, list[dict]] = {}
    out_edges: dict[str, set[str]] = {}
    in_edges: dict[str, list[tuple[str, int, str]]] = {}
    for rel, tree in pairs:
        got = _Collect(rel)
        got.visit(tree)
        for d in got.defs:
            defs.setdefault(d["name"], []).append(d)
        for caller, callee, line, kind in got.edges:
            out_edges.setdefault(caller, set()).add(callee)
            in_edges.setdefault(callee, []).append((caller, line, kind))
    return {"defs": defs, "out": out_edges, "in": in_edges}


@functools.lru_cache(maxsize=1)
def graph() -> dict:
    """整棵 `src/agentflow` 的接线图（只读盘，不 import 任何模块）。"""
    return _graph_of([(path.relative_to(SRC).as_posix(), _parse(path))
                      for path in sorted(SRC.rglob("*.py"))])


def entries(g: dict) -> set[str]:
    """真机入口集（见模块 docstring 那三条）。"""
    seeds: set[str] = set()
    for name, rows in g["defs"].items():
        for d in rows:
            if d["rel"] == "cli.py" and name.startswith("cmd_"):
                seeds.add(d["qual"])
            elif d["rel"] == "host.py":
                seeds.add(d["qual"])
            elif any("tool" in deco for deco in d["decos"]):
                seeds.add(d["qual"])
    return seeds


def reachable(g: dict) -> set[str]:
    """从入口集顺着边闭包（同名定义一起点亮）。"""
    by_qual: dict[str, list[str]] = {}
    for name, rows in g["defs"].items():
        for d in rows:
            by_qual.setdefault(d["qual"], []).append(name)
    seen: set[str] = set()
    todo = list(entries(g))
    while todo:
        qual = todo.pop()
        if qual in seen:
            continue
        seen.add(qual)
        for callee in g["out"].get(qual, ()):
            for d in g["defs"].get(callee, ()):
                if d["qual"] not in seen:
                    todo.append(d["qual"])
    return seen


def callers(g: dict, name: str) -> list[tuple[str, int, str]]:
    """非测试调用/引用点（本图只收 src，所以全是非测试）。"""
    return list(g["in"].get(name, ()))


def is_live(g: dict, name: str) -> bool:
    """这个名字有没有至少一个"本身可达"的调用/引用点。"""
    live = reachable(g)
    return any(qual in live for qual, _line, _kind in callers(g, name))


# ============================================================ 表

#: 今晚这一批（15 项）里每一项在代码上的那个落点。值是一句"谁在活着的那条路上调它"，
#: 空串 = 这一项今天是孤儿（必须同时出现在 `KNOWN_ORPHANS` 里，否则反真空那一条会红）。
#:
#: 2026-10-27 第二批（业主四条裁定的六件）追加在末尾，判据同一条：有真机调用点、
#: 调用者本身可达、且有一条运行探针读数（读数在
#: `docs/WIRING-AUDIT-2026-10-27.md` 第六节；探针脚本零模型钱）。
#:
#: 注意这张表只收"靠调用/引用边接起来"的那些。模型按名字调的工具走的是另一条面
#: （注册表），它们的判据在下面 `WIRED_BY_REGISTRY` —— 把工具混进这张表会让判据误报，
#: 因为工具函数在源码里本来就没有调用点（那是注册表的活，不是调用图的活）。
WIRED: dict[str, str] = {
    # 2 挂机：登记 / 读数 / 事件观测 / 唤醒消费
    "_register_parked": "clock.start_timer + clock.start_alarm",
    "waiters": "clock_now + clock_timer_list（只作读数）",
    "observe_work": "clock_tools._observe_session_event（会话写路径的旁路钩子）",
    "observe_message": "clock_tools._observe_session_event",
    "pending_wakes": "agent_loop._wake_pending + clock_now",
    "consume_wakes": "agent_loop.consume_clock_wakes（_take_wakes 调它）",
    # 3 秘书链转发
    "relay_out": "conductor_tools.conductor_guide（conductor.guide）",
    "relay_in": "Secretary.relay_out + Secretary.relay_in（逐跳递归）",
    "deliver_local": "Secretary.relay_in（链尾那一跳）",
    "relay_path": "Secretary.relay_out / relay_in（三处落台账）",
    # 4 链式寻址
    "parse_chain_address": "Conductor.resolve_chain",
    "resolve_chain": "conductor_tools.conductor_guide",
    "chain_of": "Conductor.resolve_chain + Conductor.tree",
    "chain_text": "Conductor.resolve_chain + Conductor.tree 的 chain 格",
    # 6 依赖面：F 写稿 / 秘书洗稿 / 打回
    "wash_dependency_face": "_Core._wash_manuscript",
    "_wash_manuscript": "_Core._apply_round 的 proof 分支（在 _proof_outlet 之前）",
    # 7 D 携带
    "_deliver_carried_to_b": "_WriteReport.write_report",
    "read_carried_manuscript": "_RegisterStatement.register_statement（两处探测）",
    "carried_manuscripts": "depsection.read_carried_manuscript",
    # 8 B 读稿落依赖
    "read_manuscript": "_RegisterStatement.register_statement 的兜底读盘",
    "record_manuscript_dependency_face": "_RegisterStatement._receive_carried_manuscript",
    # 9 V 引用核实
    "citation_material": "agent_v.core._citation_material",
    "reconcile_citation_checks": "AgentV._citation_checks",
    "apply_citation_gate": "AgentV.verify_proof",
    "signs_bit3": "verifications.record_verification 等七处",
    # 10 保留产物闸
    "_reserved_artifact": "fs_tools._reserved_refusal（fs_write / fs_edit 两道闸共用）",
    # 12 非平凡度
    "proof_effort_readings": "Secretary.judge_statement",
    "nontriviality_from_effort": "Secretary.judge_statement",
    "material_truncation": "Secretary.judge_statement",
    # 13 命题同一性
    "adjudicate_proposition": "Secretary.record_statement",
    "append_proposition_verdict": "Secretary.adjudicate_proposition",
    "proposition_verdict_of": "Secretary.adjudicate_proposition（缓存读回）",
    # 13（续）证明的路子说明：写侧 `record_statement` 落 `_proof_routes`，
    # 读侧 2026-10-27 起接在 `table_tools._with_proof_routes`（`table.get` /
    # `table.list` 的 statements 行带 `route` 与 `proof_routes` 两格）。
    # 改前这两只是孤儿：写进去之后全仓 0 个非测试调用点读回来。
    "proof_routes_of": "table_tools._with_proof_routes（两条读侧工具共用它）",
    "proof_route_of": "table_tools._with_proof_routes（同一处的 `route` 格）",
    # 15 时钟账
    "await_io": "fetch / providers / store / conductor / userio 共十三处",
    "note_wait": "clock.await_io + conductor.SummonHandle.wait + scheduler.WaveHandle",
    "coverage": "clock_now（clock.now 的 waits_outside_clock 那一格）",
    "raw_wait_census": "clock.coverage",
    # ---------------------------------------------------------------- 第二批（业主 2026-10-27 四条裁定）
    # ① 等程序：起外部程序的唯一入口是 `program_span`，进作用域就 `start_program`
    #    登记一条 kind="program" 的计时器，出作用域 `finish_program` 收口。
    "program_span": "cancellation.run_cancellable:519 等六处（起程序并等它的唯一入口）",
    "start_program": "clock.ProgramSpan.open:1854（进作用域那一刻）",
    "finish_program": "clock.ProgramSpan.finish:1883（出作用域那一刻）",
    # ② 目的自动填：装配期把"等谁"的读口挂上，读口从名册/台账里抄那一行 task 原文。
    "set_target_probe": "tools/clock_tools.py:1211 register（装配期挂口）",
    "_target_probe": "tools/clock_tools.py:1211 register（挂给 clock.set_target_probe）",
    "_roster_task_text": "tools/clock_tools.py:339 _target_probe（名册那一行 task 原文）",
    # ③ 等待任意计时器返回：读侧接在循环的判据上（`wait_any_reading`）；写侧
    #    `request_wait_any` 原先只有框架内部入口、模型面没有那一格（这就是第二批里
    #    唯一的 UNREACHABLE）。第二段① 把它做成 `clock.wait_any` 之后两条都通了 ——
    #    `clock.wait_any` 本身在 `WIRED_BY_REGISTRY`（工具面），它的 handler 调
    #    `request_wait_any`，于是这里写的是那条新的活边。
    "wait_any_reading": "agent_loop._wait_any_reading:4898 + agent_loop._hand_off:5090",
    "request_wait_any": "tools/clock_tools.py:1163 clock_wait_any（clock.wait_any 的 handler）",
    # ④ 计时器不阻塞动作：判据只有一处（`_park_gate`），"手上有活"由 `_pending_work` 现算。
    "_park_gate": "AgentLoop.run:6125（_deliver_mailbox 之后、ask_step 之前）",
    "_pending_work": "agent_loop._park_gate:4981",
    "_wait_any_reading": "agent_loop._park_gate:4980",
    # ⑤ 交差：无事可做 + 无计时器 ⇒ `_hand_off`；父侧在消费唤醒时记静默。
    "_hand_off": "AgentLoop.run:6131（_park_gate 判成交差那一支）",
    "_note_child_handoff": "agent_loop._take_wakes:4328（每条唤醒都过一遍）",
    "record_handoff": "agent_loop._hand_off:5095",
    "mark_handoff_seen": "agent_loop._note_child_handoff:4360",
    "read_handoffs": "Conductor._handoffs_summary:2665（父侧读数）",
    # ⑥ 不变量：派活成功那一刻起表（写侧），读侧判据只被测试接线 ⇒ 见 KNOWN_ORPHANS。
    "arm_child_waiter": "Conductor._summon_preflight:5160（[5c]，_register_roster 之后）",
    "_summon_preflight": "Conductor.summon_begin:4824",
}

#: 模型按名字调的那一批：它们的接线面是 `tools._MODULES`（模块装配表），不是调用边。
#: 值是"这个函数所在的工具模块"，判据同时核两件事：函数真的有 tool 装饰器、模块在表里。
WIRED_BY_REGISTRY: dict[str, str] = {
    "clock_now": "clock_tools",
    "clock_timer_start": "clock_tools",
    "clock_alarm_start": "clock_tools",
    "clock_timer_list": "clock_tools",
    "clock_timer_cancel": "clock_tools",
    "clock_periodic_start": "clock_tools",
    "clock_periodic_stop": "clock_tools",
    "clock_timer_purpose": "clock_tools",
    "clock_wait_any": "clock_tools",
    "conductor_watch": "conductor_tools",
    "conductor_ledger": "conductor_tools",
    "conductor_guide": "conductor_tools",
    "trace_children": "trace_tools",
}

#: 今天实测没有真机调用点的那些。每一条都要写清"为什么它还在、以及差哪一根线"；
#: 这张表与实测集合必须相等（新增孤儿会红，接上之后不改表也会红）。
#:
#: 2026-10-27 晚清空：最后两条（`proof_route_of` / `proof_routes_of`）已经接上读侧
#: （`table_tools._with_proof_routes`），于是它们移进 `WIRED`。空表本身也是有内容的
#: 读数：它说"今天这一批没有孤儿"，而反真空那一条（实测集合必须等于台账）仍然在守。
#:
#: 2026-10-27 第二批填过七条（`programs` / `program_census` / `request_wait_any` /
#: `read_wait_any` / `cancel_wait_any` / `handoffs_reading` / `child_wait_invariant`），
#: 随后逐条补线清空：
#: - `request_wait_any` → `clock.wait_any`（工具面，`WIRED_BY_REGISTRY`）；
#: - `programs` → `clock.now` 的 `programs` 那一格；
#: - `program_census` → `clock.coverage()` 的 `programs_outside_clock`（`clock.now` 念它）；
#: - `read_wait_any` → `clock.wait_any` 的 `intents` 那一格；
#: - `cancel_wait_any` → `agent_loop._park_gate` 回模型那一拍（`run.park.wait_cancelled`）；
#: - `handoffs_reading` → `conductor.watch` / `conductor.ledger` 的 `silent_children`；
#: - `child_wait_invariant` → `conductor.watch` / `conductor.status_report` 的同一名格子。
#: 每一格的"读数里真有它 + 打桩成空就红"由 `tests/test_wiring_readouts.py` 钉住。
KNOWN_ORPHANS: dict[str, str] = {}

#: 这三个是"只作为读数被读、从不参与控制流"的属性。它们不算孤儿（属性读取算边），
#: 但它们是 `docs/WIRING-AUDIT-2026-10-27.md` 里 a/b 两条的判据本体 —— 单独点名，
#: 免得下一次有人把它们从读数面删掉却没有人发现。
READOUT_ONLY: tuple[str, ...] = ("park_state", "is_park")


# ============================================================ 判据

def test_every_monitored_feature_has_a_live_edge() -> None:
    """① 表里每一项都必须有一个"本身可达"的调用点或引用点。"""
    g = graph()
    dead = []
    for name, why in WIRED.items():
        rows = g["defs"].get(name) or []
        assert rows, f"`WIRED` 里的 {name!r} 在 src 里找不到定义点 —— 表过期了"
        got = callers(g, name)
        if not got:
            dead.append(f"{name}（表里写的是：{why}）：0 个非测试调用点")
            continue
        if not is_live(g, name):
            where = "、".join(f"{q}:{line}" for q, line, _k in got[:4])
            dead.append(f"{name}（表里写的是：{why}）：有调用点但调用者不可达 {where}")
    assert not dead, (
        "这些功能没有活在真机调用图上（实现好了、没人调）：\n" + "\n".join(dead))


def test_the_orphan_ledger_equals_what_the_graph_finds() -> None:
    """② 反向：实测孤儿集合必须等于台账（两向都红）。"""
    g = graph()
    found = {name for name in list(WIRED) + list(KNOWN_ORPHANS) if not is_live(g, name)}
    listed = set(KNOWN_ORPHANS)
    assert found == listed, (
        "孤儿台账与实测不符。\n"
        f"  实测是孤儿、台账里没写：{sorted(found - listed)}（有人在不知不觉中让它失去了调用点；"
        "要么接上，要么写进 `KNOWN_ORPHANS` 并说清差哪一根线）\n"
        f"  台账写了孤儿、实测已经有活调用点：{sorted(listed - found)}"
        "（这是接线事件，请把它从 `KNOWN_ORPHANS` 移到 `WIRED` 并写清谁调它）")


def _called_only_from_a_test() -> dict:
    """形态甲：唯一的调用点在一份测试文件里 ⇒ 没有真机入口 ⇒ 这个名字是死的。"""
    return _graph_of([
        ("probe_only_test_calls.py", ast.parse(
            "def orphan_fn():\n    return 1\n")),
        ("tests/test_probe.py", ast.parse(
            "def test_thing():\n    return orphan_fn()\n")),
    ])


def _called_from_a_real_entry() -> dict:
    """形态乙：调用点是 `cli.py` 的 `cmd_*`（真机入口集那一档）⇒ 这个名字是活的。"""
    return _graph_of([
        ("probe_real_entry_calls.py", ast.parse(
            "def real_fn():\n    return 1\n")),
        ("cli.py", ast.parse(
            "def cmd_probe(args):\n    return real_fn()\n")),
    ])


def _the_pair(predicate) -> tuple[bool, bool]:
    """判据本体：同一对语义相反的图、同一套谓词，必须读出"一死一活"。

    正控与反真空共用它：反真空把 `predicate` 换成恒 True（或恒 False），
    这一对读数就塌成一个值，"一死一活"当场不成立 —— 这正是"该判据必红"。
    """
    return (bool(predicate(_called_only_from_a_test(), "orphan_fn")),
            bool(predicate(_called_from_a_real_entry(), "real_fn")))


def test_the_liveness_predicate_is_not_vacuous() -> None:
    """③ 反真空：`is_live` / `reachable` 必须把两种语义相反的 AST 读成不同的结论。

    改前这一条是假反真空（审计 2026-10-27 第三处）：它断的是用例内嵌的 `callees()`
    对两棵合成树都给出 `{"call"}` —— 恒真，`is_live` / `reachable` 一次都没被调用。

    现在两棵树走完整条真判据：`_Collect` 收边、`entries()` 种真机入口、`reachable()`
    顺边闭包、`is_live()` 只看"调用者本身可不可达"：

    - 形态甲：`orphan_fn` 的唯一调用点在一份测试文件里 ⇒ `entries()` 不种它 ⇒ 不可达；
    - 形态乙：`real_fn` 的调用点是 `cli.py` 的 `cmd_probe`（真机入口集那一档）⇒ 可达。

    反真空（本条自己承重）：把谓词打桩成恒 True ⇒ 同一对读数塌成 `(True, True)`，
    第一条断言当场红；恒 False 同理。两条都断，所以"永远说活"和"永远说死"都逃不掉。
    """
    assert _the_pair(is_live) == (False, True), (
        "谓词读不出这两种形态的差别（都说活、或都说死）⇒ 它没在量接线",
        _the_pair(is_live))
    for stub_value in (True, False):
        stub = lambda _g, _name, _value=stub_value: _value   # noqa: E731 - 打桩谓词
        assert _the_pair(stub) != (False, True), (
            f"把谓词打桩成恒 {stub_value} 之后这一对读数仍然一死一活 ⇒ "
            "判据的牙不是从 is_live 那里来的")

    # 入口集与闭包各自也要承重（否则形态乙可能因为别的原因绿）：
    # `cmd_*` 在 `cli.py` 里才是入口，测试文件里的调用点一律不是。
    live_graph = _called_from_a_real_entry()
    assert "cmd_probe" in entries(live_graph), entries(live_graph)
    assert "cmd_probe" in reachable(live_graph), sorted(reachable(live_graph))
    assert "real_fn" in reachable(live_graph), sorted(reachable(live_graph))
    dead_graph = _called_only_from_a_test()
    assert "test_thing" not in entries(dead_graph), ("测试文件里的调用点被当成真机入口"
                                                    " ⇒ 形态甲那一半恒死不了")
    assert reachable(dead_graph) == set(), sorted(reachable(dead_graph))


def test_the_clock_module_is_on_the_assembly_list() -> None:
    """④ 工具那一条面：`@tool` 函数必须挂着 tool 装饰器，且它所在模块在 `tools._MODULES` 里。

    为什么不把工具塞进 `WIRED` 那张表：工具在源码里没有调用点（模型按名字取），硬要求
    调用边会把十一件工具全判成孤儿 —— 那是判据错，不是代码错。它们的接线面是装配表。
    `_MODULES` 从源码里的那个元组字面量按 AST 现读（不 import）：它被改成算出来的表达式
    时这一条会以"读不懂装配表"红掉，而不是悄悄通过。
    """
    g = graph()
    modules = _assembly_modules()
    bad: list[str] = []
    for name, module in WIRED_BY_REGISTRY.items():
        rows = g["defs"].get(name) or []
        if not rows:
            bad.append(f"{name}：src 里找不到定义点（表过期了）")
            continue
        if not any("tool" in deco for d in rows for deco in d["decos"]):
            bad.append(f"{name}：不是 `@tool` 函数，注册表拿不到它")
        if module not in modules:
            bad.append(f"{name}：它所在的 {module} 不在 tools._MODULES 里 ⇒ 谁都拿不到")
    assert not bad, "这些工具不在真机工具面上：\n" + "\n".join(bad)


def _assembly_modules() -> set[str]:
    """`tools/__init__.py` 里 `_MODULES` 那个元组字面量（静态读，不 import）。"""
    tree = _parse(SRC / "tools" / "__init__.py")
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target != "_MODULES":
            continue
        value = node.value
        if not isinstance(value, (ast.Tuple, ast.List)):
            raise AssertionError(
                "tools._MODULES 不是元组字面量，这一条判据读不懂它 —— "
                "装配表是接线判据的落点，改成算出来的表达式之前请先改这里")
        return {e.value for e in value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    raise AssertionError("tools/__init__.py 里找不到 _MODULES")

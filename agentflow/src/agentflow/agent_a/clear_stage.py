"""A 的收尾自驱（`clear_stage`）：A 这一拍收尾时自己把该清的表清掉。

## 两个接线点（同一份判据，不是两份实现）

1. `run_once` 的每个出口（`_finish`，ACLEAR）：模型调了 `own.run_once` 时由它收尾；
2. `agent_loop.run()` 的退场段（`drive_at_run_exit`，ACLEAR2）：模型一次
   `run_once` 都不调、只用 `lit.*` 把判收做完时由它收尾 —— 真机 `lp-ball-15`
   的 A 221 步里 `own.run_once` 是 0 次，这一条覆盖边界由 ACLEAR2 补上。

两个入口调的是同一对函数（`_clear_stage_self_drive` / `_unprocessed_reason_self_drive`），
所以"清哪几个委托 / 写不写理由"的判据只有一份；区别只在什么时候算这一拍收尾。

## 为什么要有它（2026-11-21，真机 lp-ball-15 的现场）

真机 `projects/lp-ball-15` 的收工门 6 pass / 2 fail，其中一格是
`literature_pending` 的 `delegation_not_cleared`：委托 `r-000008` 的 6 行候选
里只有判收的那 1 行被清了表，另外 5 行判拒的一直没有 `cleared_at`、也没有归档。
现场逐条：

- A 在 15:46:24 对 `r-000008` 的 5 个槽逐条 `lit.stage_reject`（判拒是终态，
  行上不再 pending），15:46:29 又对同一个委托调 `lit.admit_all`，但 `slots`
  只点名了判收的那 1 个槽；
- `lit.admit_all` 的清表作用域是"这一次提交覆盖的槽"（`clear_delegation` 的
  `only_slots`），于是判拒的 5 行一行都没有 `cleared_at`；
- `run_once` 的出口只读/认领待裁行（`pending_all_delegations`），判完但没清表的
  委托对它完全隐身 —— 要让清表发生，只能靠模型自己再想起来补一次
  `lit.admit_all`，而它已经收了 `done=true` 的工。

同族先例是 B 的二阶段（`agent_b/stage_two.py`）：`run_once` 每个出口在 `_finish`
里自驱，不靠 M 派、也不靠模型自觉。这里照同一个形状做 A 的收尾。

## 这一格做两件事，都是"自驱"不是"再立一道门"

1. 清表（`_clear_stage_self_drive`）：逐委托看，凡"已判完（没有 pending）但还没
   清表"的，自己调 `litstage.admit_all`（这就是模型那个动作的同一份实现：批量
   注册 + 回填 + 双阶段报告 + 归档 + 清表）。被跳过的委托逐条写 `why`：
   还有 pending 的写明"还剩几条没判，不清表"（正控，见判据 c）。
2. 未消化理由（`_unprocessed_reason_self_drive`）：`literature.processed` 只由
   B 的 `run_once` 领取路径翻；B 用 `table.create` 手工登记完的那几篇，概念/关系
   行都在盘上，`processed` 却仍是假。这一格给那种"确实消化过"的行自动写
   `unprocessed_reason`（逐条带 statements / relations 的条数），收工门
   `acceptance` 那一格的读取端会认它（口径不变：仍然只是 `unknown`，不是 `pass`）。
   没有消化痕迹的行一个字都不写 —— 那是"没消化"，不是"可以带着收工"。

它不替模型判收（判收是文本判断）、不替 B 抽读，也不动 `processed`：
`processed` 是 B 的证据位，A 去翻它等于替 B 作证。

## 三态

`checked=False` 是"没查成"（没有 store / 表读不出来），不是"表已清"；
`enabled=False` 是反真空打桩；`in_task` 只做读数 —— 清表不靠召唤号（`admit_all`
是幂等的、归档与 `lit.close` 事件都带 actor），所以这里不按 B 的 `in_task` 跳过，
但"不在任务上下文"这件事必须能在回执里读到，不许静默。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _clear_stage_self_drive_enabled() -> bool:
    """清表自驱开不开（反真空的打桩点；默认开）。

    与 `agent_b/stage_two._stage_two_self_drive_enabled` 同形：这一格只回答
    "这一拍自驱不自己提交"，不回答"清哪几个委托"。反真空把它打成 False ⇒
    `run_once` 不再自己清表（`pending` / `refused` 读数照常点名）——
    证明"自己清了表"不是一句恒真读数。
    """
    return True


def _unprocessed_reason_self_drive_enabled() -> bool:
    """未消化理由自驱开不开（反真空的打桩点；默认开）。

    关掉它之后 `literature` 行上不会多出 `unprocessed_reason`，收工门
    `acceptance` 那一格对"没有理由的未消化队列"照样红 —— 证明那一格的红
    不是被这一格偷偷洗掉的。
    """
    return True


def _in_task() -> tuple[bool, str]:
    """这一拍有没有召唤号：`(在不在任务里, 读不到时的原因)`。

    读不到召唤号不等于"不在任务里"（三态）：`why` 非空时调用方要把原因写进回执。
    """
    try:
        from ..conductor import current_task_id

        return bool(str(current_task_id() or "")), ""
    except Exception as exc:  # noqa: BLE001 - 读不到召唤号 = 这一格没查成（不是"不在任务里"）
        return False, f"{type(exc).__name__}: {exc}"


def _finish(agent: Any, res: Any) -> Any:
    """`run_once` 的每个出口都从这里交结果：先算两个收尾自驱，再返回。

    为什么所有出口都要走它（而不是只在"主流程跑完"那一支）：真机 lp-ball-15
    的 `r-000008` 判完之后 A 的下一拍只走"队列空"那个出口（检索请求全 done）——
    只在主流程那一支自驱，恰恰放过了现场这一形。
    """
    res.clear_stage = _clear_stage_self_drive(agent)
    res.unprocessed_reasons = _unprocessed_reason_self_drive(agent)
    return res


def drive_at_run_exit(agent: Any, run: Any = None) -> dict:
    """A 这一拍退场时的收尾自驱（`agent_loop` 里的唯一接线点，ACLEAR2）。

    ## 为什么还要第二处接线（ACLEAR 的覆盖边界）

    ACLEAR 把自驱挂在 `agent_a/run_once.py` 的三个出口上，而真机 `lp-ball-15` 的 A
    221 步里 `own.run_once` 被调了 0 次（B 是 23 次）：模型直接用 `lit.*` 工具
    把判收做完了，于是那一份自驱一次都没被触发 —— 判完没清表的三个委托就这么留到了
    收工门。`agent_loop.run()` 的退场段是这一拍一定会经过的那一处：步循环里的
    `break`（收工 / 判停两档 / 预算 / 叫停 / 等用户 / 上行 / 模型不可达与坏 JSON
    上限 …）全都落到那里，`for ... else` 那一支也一样；异常那一档连 `agent_run_end`
    都没有，不是这一格能补的。接线点见 `agent_loop.py` 退场段那句注释。

    ## 这一格不另写判据

    两件事都直接调上面写好的那两个函数（`_clear_stage_self_drive` /
    `_unprocessed_reason_self_drive`）—— 清哪几个委托、写不写理由的判据只有一份。
    这里只做两件接线该做的事：把读数挂到 `LoopRun` 上（`runs/A-*.json` 的可复核面）、
    把"真的要动手的那几档"落一句人话进 `run.notes`（跟着 `agent_run_end` 一起落盘）。

    ## 为什么"没事可做"时不写 note

    `run` 上的两个结构化字段已经完整回答了"查过没有 / 清了几条 / 还剩几条"；
    每一拍都往 notes 里加一句"都已清表"只会把真正的那句话淹掉（真机 notes 已经
    九千条）。但三种情形必须留痕、不许静默：没查成（`checked=False`）、
    真的动了盘（`cleared` / `written` 非空）、以及想交却没交成（`refused` 非空）。
    """
    clear_stage = _clear_stage_self_drive(agent)
    reasons = _unprocessed_reason_self_drive(agent)
    if run is not None:
        # `run` 只做读数落点：没有它（裸调本函数）也要能跑完这一格。
        setattr(run, "clear_stage", clear_stage)
        setattr(run, "unprocessed_reasons", reasons)
        note = _run_exit_note(clear_stage, reasons)
        if note:
            notes = getattr(run, "notes", None)
            if isinstance(notes, list):
                notes.append(note)
    return {"clear_stage": clear_stage, "unprocessed_reasons": reasons}


def _run_exit_note(clear_stage: dict, reasons: dict) -> str:
    """退场自驱的那一句读数：只报"没查成 / 动了盘 / 想交没交成"三档（其余进字段）。"""
    parts: list[str] = []
    if not clear_stage.get("checked"):
        parts.append("清表自驱没查成：" + str(clear_stage.get("why") or "（没有原因）"))
    elif clear_stage.get("cleared") or clear_stage.get("refused"):
        parts.append("清表自驱：" + str(clear_stage.get("note") or ""))
    if not reasons.get("checked"):
        parts.append("未消化理由自驱没查成：" + str(reasons.get("why") or "（没有原因）"))
    elif reasons.get("written"):
        parts.append("未消化理由自驱：" + str(reasons.get("note") or ""))
    if not parts:
        return ""
    return "A 这一拍退场时的收尾自驱（自驱不是模型补的）：" + "；".join(p for p in parts if p)


def _by_delegation(rows: list[dict]) -> dict[str, list[dict]]:
    """按委托号分组的候选行（组内保持盘上的顺序；空委托号也算一组）。"""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(str(row.get("request_id") or ""), []).append(dict(row))
    return groups


def _registrar(agent: Any):
    """把"一条候选登记成 literature 行"接到工具层那份唯一实现上。

    为什么不在这里另写一份登记逻辑：判收/提交的登记路径（`search.register` 的
    handler）要处理判重、取号、收编候选期抽读件、补写定位栏 —— 这些口径的
    唯一实现是 `tools.search_tools._registrar_from_candidate`，复制一份必然漂，
    而漂的表现是"自驱提交造出来的 literature 行与模型提交造出来的不同形"。
    与 `agent_a/shelf_search.py::_tool_ctx` 同一条理由：复用工具层的 `_Ctx`，
    免得"相对路径往哪解析"这种地方悄悄分叉。
    """
    from ..tools.search_tools import _Ctx, _registrar_from_candidate

    root = Path(getattr(agent.store, "root", ".")).resolve()
    ctx = _Ctx(workspace=root, store=agent.store,
               bound_actor=str(getattr(agent, "actor", "") or ""))

    def _one(row: Any) -> dict:
        return _registrar_from_candidate(ctx, row)

    return _one


def _clear_stage_self_drive(agent: Any) -> dict:
    """逐委托自驱清表：已判完、没清表的委托，这一拍自己 `lit.admit_all` 掉。

    返回 `{checked, enabled, in_task, in_task_why, delegations, settled, cleared,
    pending, refused, why, note}`：

    - `cleared`：这一拍真的提交掉的委托，逐条 `{request_id, cleared, registered,
      slots, archive_rel_path, report_path}` —— 回执按它点名"清了几条 / 哪个委托 /
      归档在哪"；
    - `pending`：还有没判的委托（`{request_id, pending, slots, why}`）—— 这一档
      只点名、不动盘：提交闸要的是"批内全判"，替它清表就是关闸；
    - `refused`：这一拍想交但被受控拒的委托（逐条带 `kind` 与原文），包括
      并发下别人已经清掉的 `already_settled`；
    - `settled`：本来就已经清过表的委托号（幂等的读数，不重复提交）。
    """
    out: dict = {"checked": False, "enabled": False, "in_task": False,
                 "in_task_why": "", "delegations": 0, "settled": [],
                 "cleared": [], "pending": [], "refused": [], "why": "", "note": ""}
    store = getattr(agent, "store", None)
    if store is None:
        out["why"] = "没有 store ⇒ 读不到待入库候选表（没查成，不是「表已清」）"
        return out
    try:
        rows = [dict(r) for r in store.rows("lit_candidates")]
    except Exception as exc:  # noqa: BLE001 - 读不到 ≠ 已清表
        out["why"] = (f"待入库候选表读不出来（{type(exc).__name__}: {exc}）"
                      "⇒ 没查成，不是「已清表」")
        return out
    out["checked"] = True
    out["enabled"] = bool(_clear_stage_self_drive_enabled())
    out["in_task"], out["in_task_why"] = _in_task()
    groups = _by_delegation(rows)
    out["delegations"] = len(groups)
    if not out["enabled"]:
        out["why"] = "清表自驱被关掉（反真空打桩）⇒ 这一拍只点名、不自己提交"
        return out
    from .. import litstage as L

    todo: list[str] = []
    for rid in sorted(groups):
        rs = groups[rid]
        if not rs:
            continue
        if L.cleared_of(rs):
            out["settled"].append(rid)
            continue
        waiting = [r for r in rs if L.judged_state(r) == "pending"]
        if waiting:
            out["pending"].append({
                "request_id": rid, "pending": len(waiting),
                "slots": sorted(str(r.get("slot") or "") for r in waiting),
                "why": (f"委托 {rid} 还有 {len(waiting)} 条没判 ⇒ 这一拍不清表"
                        "（提交闸要的是批内全判；替它清表等于把闸关掉）"),
            })
            continue
        todo.append(rid)
    if not todo:
        out["why"] = _no_todo_why(out)
        out["note"] = out["why"]
        return out
    try:
        registrar = _registrar(agent)
    except Exception as exc:  # noqa: BLE001 - 登记路径接不上要如实写，不许静默跳过
        out["why"] = (f"登记路径接不上（{type(exc).__name__}: {exc}）⇒ 这一拍不提交；"
                      "要清的是：" + "、".join(todo))
        out["note"] = out["why"]
        return out
    actor = str(getattr(agent, "actor", "") or "agent-A")
    for rid in todo:
        # 这一次调用会新清几条：`clear_delegation` 的 `cleared` 数的是"这次提交覆盖的
        # 全部槽"（含早已清过的行），而回执要的是"这一拍补上了几条 cleared_at"。
        newly = sum(1 for r in groups[rid]
                    if not str(r.get("cleared_at") or "").strip())
        try:
            got = L.admit_all(store, registrar=registrar, request_id=rid, actor=actor)
        except L.LitStageError as exc:
            kind = str(getattr(exc, "kind", "") or "")
            out["refused"].append({"request_id": rid, "kind": kind, "why": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 - 提交失败要如实写，不许把这一轮判成成功
            out["refused"].append({"request_id": rid, "kind": type(exc).__name__,
                                   "why": f"{type(exc).__name__}: {exc}"})
            continue
        if not got.get("ok"):
            # `admit_all` 的受控拒是"返回一份 ok=False 的读数"而不是抛：
            # 这一档不许折成"清了"（那会把拒绝写成成功，比不清更坏）。
            out["refused"].append({
                "request_id": rid,
                "kind": str(got.get("kind") or "refused"),
                "why": str(got.get("reason") or "提交被受控拒（没有理由原话）"),
            })
            continue
        rep = got.get("report") if isinstance(got.get("report"), dict) else {}
        out["cleared"].append({
            "request_id": rid,
            "cleared": int(newly),
            "registered": int(got.get("registered") or 0),
            "slots": list(got.get("submitted") or []),
            "archive_rel_path": str(got.get("archive_rel_path") or ""),
            "report_rel_path": str(rep.get("rel_path") or ""),
            "report_admitted": int(rep.get("admitted") or 0),
            "report_not_admitted": int(rep.get("not_admitted") or 0),
        })
    out["why"] = _clear_why(out)
    out["note"] = out["why"]
    return out


def _no_todo_why(out: dict) -> str:
    """没有可提交的委托时那句读数（区分"都清过了"与"还有没判的"）。"""
    head = f"全表 {int(out.get('delegations') or 0)} 个委托"
    if out.get("pending"):
        left = "、".join(f"{x['request_id']} 还剩 {x['pending']} 条没判"
                         for x in out["pending"])
        return f"{head}里没有已判完待清表的；另有没判完的：{left}"
    return f"{head}都已清表（每一行都有 cleared_at），这一拍没有要提交的"


def _clear_why(out: dict) -> str:
    """清表自驱的一句话结论：清了几条 / 哪个委托 / 归档在哪 / 谁没交成。"""
    parts: list[str] = []
    if out.get("cleared"):
        parts.append("这一拍自己提交了 " + str(len(out["cleared"])) + " 个还没清表的委托："
                     + "、".join(
                         f"{x['request_id']}（清 {x['cleared']} 条 / 注册 {x['registered']} 条）"
                         for x in out["cleared"]))
        archives = "、".join(f"{x['request_id']}→{x['archive_rel_path']}"
                            for x in out["cleared"] if x.get("archive_rel_path"))
        if archives:
            parts.append("归档：" + archives)
    if out.get("pending"):
        parts.append("另有没判完、这一拍不清表的："
                     + "、".join(f"{x['request_id']} 还剩 {x['pending']} 条"
                                for x in out["pending"]))
    if out.get("refused"):
        parts.append("没交成的：" + "、".join(
            f"{x['request_id']}（{x.get('kind') or '受控拒'}：{str(x.get('why') or '')[:160]}）"
            for x in out["refused"]))
    if out.get("settled"):
        parts.append(f"已经清过表的委托 {len(out['settled'])} 个")
    if not parts:
        return f"全表 {int(out.get('delegations') or 0)} 个委托里没有要清的"
    return "；".join(parts) + "。"


def _active_statements(rows: list[dict], lit_id: str) -> list[dict]:
    """这一篇文献名下、仍在册的 statements 行（`source_lit_id` 指向它）。"""
    return [r for r in rows
            if str(r.get("source_lit_id") or "") == lit_id
            and str(r.get("status") or "active") == "active"]


def _active_relations(rows: list[dict], lit_id: str) -> list[dict]:
    """这一篇文献名下、仍在册的 relations 行（`lit_id` 指向它）。"""
    return [r for r in rows
            if str(r.get("lit_id") or "") == lit_id
            and str(r.get("status") or "active") == "active"]


def _unprocessed_reason(lit_id: str, n_stmt: int, n_rel: int) -> str:
    """一条"确实消化过、但 processed 位没翻"的行上那句理由（逐条带证据条数）。"""
    return (
        f"B 已经把这一篇登记成 {n_stmt} 条 statements（概念/命题，"
        f"source_lit_id={lit_id}）与 {n_rel} 条 relations（lit_id={lit_id}），"
        "只是 `processed` 位仍为假：该位只由 B.run_once 的领取路径翻，"
        "B 用 table.create / own.register_statement 手工登记不会翻它。"
        "⇒ 这一条已经消化过（证据就是上面那两行条数），可以带着这一格收工。"
    )


def _unprocessed_reason_self_drive(agent: Any) -> dict:
    """给"确实消化过、processed 仍为假"的 literature 行自动写下理由。

    返回 `{checked, enabled, unprocessed, written, kept, undigested, why, note}`：

    - `written`：这一拍落下理由的行，逐条 `{lit_id, title, statements, relations,
      reason}`（"行上能看到"就是这一格）；
    - `kept`：行上已经有理由（幂等：不覆盖别的写者写的那一句）；
    - `undigested`：没有消化痕迹（statements 与 relations 都 0）或 B 正持着租约
      的行，逐条带 `why` —— 这一档一个字都不写：没有证据就写"可以带着收工"
      等于把未消化说成已消化。
    """
    out: dict = {"checked": False, "enabled": False, "unprocessed": 0,
                 "written": [], "kept": [], "undigested": [], "why": "", "note": ""}
    store = getattr(agent, "store", None)
    if store is None:
        out["why"] = "没有 store ⇒ 读不到文献表（没查成，不是「没有未消化」）"
        return out
    try:
        lit_rows = [dict(r) for r in store.rows("literature")]
    except Exception as exc:  # noqa: BLE001 - 读不到 ≠ 没有未消化
        out["why"] = (f"文献表读不出来（{type(exc).__name__}: {exc}）"
                      "⇒ 没查成，不是「没有未消化」")
        return out
    out["checked"] = True
    out["enabled"] = bool(_unprocessed_reason_self_drive_enabled())
    unprocessed = [r for r in lit_rows if not r.get("processed")]
    out["unprocessed"] = len(unprocessed)
    if not out["enabled"]:
        out["why"] = "未消化理由自驱被关掉（反真空打桩）⇒ 这一拍不写理由"
        return out
    if not unprocessed:
        out["why"] = "`literature.processed` 全为真 ⇒ 没有要写理由的行"
        out["note"] = out["why"]
        return out
    try:
        statement_rows = [dict(r) for r in store.rows("statements")]
        relation_rows = [dict(r) for r in store.rows("relations")]
    except Exception as exc:  # noqa: BLE001 - 读不到消化面 ⇒ 不猜
        out["why"] = (f"消化面（statements / relations）读不出来"
                      f"（{type(exc).__name__}: {exc}）⇒ 这一拍不写理由")
        return out
    from ..store import lease_expired

    actor = str(getattr(agent, "actor", "") or "agent-A")
    for row in unprocessed:
        lit_id = str(row.get("lit_id") or "")
        title = str(row.get("title") or "")
        existing = str(row.get("unprocessed_reason") or "").strip()
        if existing:
            out["kept"].append({"lit_id": lit_id, "title": title, "reason": existing})
            continue
        if not lease_expired(row.get("lease_until")) and row.get("claimed_by"):
            out["undigested"].append({
                "lit_id": lit_id, "title": title,
                "why": (f"B 的领取租约还没到期（holder={row.get('claimed_by')}）"
                        "⇒ 这一拍不写理由：它正在被消化，下一秒可能就翻真")})
            continue
        n_stmt = len(_active_statements(statement_rows, lit_id))
        n_rel = len(_active_relations(relation_rows, lit_id))
        if not n_stmt and not n_rel:
            out["undigested"].append({
                "lit_id": lit_id, "title": title,
                "why": ("statements 与 relations 都没有挂在这一篇上 ⇒ 没有消化痕迹，"
                        "不写字面理由（那会是把未消化说成已消化）")})
            continue
        reason = _unprocessed_reason(lit_id, n_stmt, n_rel)
        try:
            with store.tx("literature", actor=actor,
                          note="a.clear_stage.unprocessed_reason") as tx:
                cur = tx.find("literature", lit_id=lit_id)
                if cur is None:
                    out["undigested"].append({
                        "lit_id": lit_id, "title": title,
                        "why": "写理由时这一行已经不在表里（并发删除）⇒ 没写"})
                    continue
                cur["unprocessed_reason"] = reason
                tx.upsert("literature", cur, note="a.clear_stage.unprocessed_reason")
        except Exception as exc:  # noqa: BLE001 - 写失败要如实写，不许折成写过了
            out["undigested"].append({
                "lit_id": lit_id, "title": title,
                "why": f"写理由失败：{type(exc).__name__}: {exc}"})
            continue
        out["written"].append({"lit_id": lit_id, "title": title,
                               "statements": n_stmt, "relations": n_rel,
                               "reason": reason})
    out["why"] = _unprocessed_why(out)
    out["note"] = out["why"]
    return out


def _unprocessed_why(out: dict) -> str:
    """未消化理由自驱的一句话结论（写了哪几行 / 哪几行不能写、为什么）。"""
    parts: list[str] = []
    if out.get("written"):
        parts.append("这一拍给 " + str(len(out["written"])) + " 条已消化但 processed 仍为假的"
                     "文献行写了 `unprocessed_reason`："
                     + "、".join(f"lit:{x['lit_id']}（statements {x['statements']} / "
                                 f"relations {x['relations']}）" for x in out["written"]))
    if out.get("kept"):
        parts.append("已经有理由的 " + str(len(out["kept"])) + " 条保持原样："
                     + "、".join(f"lit:{x['lit_id']}" for x in out["kept"]))
    if out.get("undigested"):
        parts.append("没有写理由的：" + "、".join(
            f"lit:{x['lit_id']}（{x.get('why')}）" for x in out["undigested"]))
    if not parts:
        return f"`literature` 有 {int(out.get('unprocessed') or 0)} 条未消化，但没有可写的理由"
    return "；".join(parts) + "。"

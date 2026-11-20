# -*- coding: utf-8 -*-
"""等级反算（apply 才写盘）。

2026-11-20（VERSPLIT2）：`v_grades.py` 是从 `verifications.py` 搬出的 2 块 / 282 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import evidencebits as EB  # 等级的唯一派生口（`derive_grade` / 反算表）
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）
from . import statementledger as SL  # 命题台账的查口（按号 / 按关键词，只读、零模型）


def recompute_grades(root: str | Path, store: Any, *, apply: bool = False) -> dict[str, Any]:
    """按现行 V 的签重算每一行的等级（四栏读数；`apply` 才把历史列反算回去）。

    ## 2026-11-05 改口径：这一格从"补档位"变成"算等级"
    业主动裁：「等级是唯一的轴……`evidence_kind` 只作历史列保留，判定面一律读等级」。
    于是本命令的主读数从"该把 `evidence_kind` 写成哪一档"变成"按五元位现算，这一行
    现在哪一级"：等级是 :func:`evidencebits.derive_grade` 的现算值，不是本命令造的目标。

    ## 判据只有一处
    每一行都调 :func:`_grade_recomputed_from_signature`（它只算等级、不写档位）；
    本函数一个字都不重写"够不够 `pre_theorem`"的判据。四栏里"凭据不够"那一栏的
    `state` 是 :func:`proof_review_gap` 的原值（`signed` / `holding` / `stale` /
    `rejected` / `unsigned` / `unreadable`），不是本命令自造的枚举。

    ## 四栏（顺序不变，语义改成等级）
    - `will_upgrade`：现算等级与"历史档位反算出来的等级"不一致 —— 两个方向都收，
      `direction` 逐条写 `up`/`down`。存量里 106 条 `cross_check→heuristic` 会降、
      30 条 `cross_check→proof_review` 会升（分布见 `temp/grade_audit.py`）。
    - `already_consistent`：现算等级与历史列的反算名已经一致（重刷不会动它）；
    - `not_enough`：现算等级算不出来、而凭据闸有话说 —— `state` 逐字是
      `proof_review_gap().state`；
    - `unchecked`：`checked=False`（台账读不出来 / 坏行 / 这一行根本查不了）＋ `why`。
    概念行（`kind="concept"`）不进四栏：概念不参与等级链（`evidencebits.derive_grade` 对
    它 `not_applicable`），把它折进任何一栏都是错读数。它们逐条记在 `concepts` 里，
    并在 `--json` / CLI 摘要里报出条数。

    ## `apply`
    `apply=True` 时逐条落盘（一行一笔 `store.tx("statements")`）：事务内重新读这一行、
    再调一次 `_grade_recomputed_from_signature`（盘在两次读之间可能变过），只有仍然
    "等级与历史档位不一致"才 `tx.upsert`。写的是反算名
    （`evidencebits.kind_from_grade(等级)`）—— 档位若还出现，只能由等级反算
    （业主原话），不是"本命令选了一个目标档"。读不出来的行一个字不写；写入失败记
    `failed`、继续下一条。写完逐条再读一次盘，只有盘上现算等级与 `_grade_recomputed.to`
    都对上才记 `written`，否则记 `unmoved`（"已写 / 未动"是两条不同的读数）。

    幂等：等级与反算名已经一致的行在 `_grade_recomputed_from_signature` 之后不会再动
    ⇒ 第二次 `apply` 全部落 `already_top` 或 `not_enough`。

    返回键：`checked`（整张表读出来了吗）/ `apply` / `root` / `rows`（总行数）/
    `columns`（上面四栏）/ `concepts` / `written` / `unmoved` / `failed` / `why`。
    `not_enough` 每条还带 `ledger` / `ledger_present` / `rows`：`proof_review_gap` 在
    "台账文件不在盘上 / 空文件 / 没有证明正文"这几支会给出空的 `state`，这几格用 gap
    自己的读数说清"空"是哪一种 —— 不在这里补一个枚举。
    """
    root_p = Path(root) if str(root or "").strip() else Path(getattr(store, "root", "") or "")
    out: dict[str, Any] = {
        "checked": False, "apply": bool(apply), "root": str(root_p),
        "rows": 0, "columns": {name: [] for name in GRADE_BACKFILL_COLUMNS},
        "concepts": [], "written": [], "unmoved": [], "failed": [], "why": "",
    }
    if not str(root_p).strip():
        out["why"] = "没给工作区根 ⇒ 台账读不出来（四栏都没查成）"
        return out
    if not (root_p / "data" / str(S.TABLES["statements"]["file"])).is_file():
        out["why"] = (f"`{root_p / 'data' / str(S.TABLES['statements']['file'])}` 不在盘上"
                      " ⇒ 这不像一个工作区（四栏都没查成）")
        return out
    rows, problem, error = SL.rows_of(store)
    if problem:
        out["why"] = (f"`statements` 读不出来（{error.get('type') or '?'}: "
                      f"{error.get('message') or problem}）⇒ 四栏都没查成")
        return out
    out["checked"] = True
    out["rows"] = len(rows)
    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
    order = {g: i for i, g in enumerate(EB.GRADES)}

    def _rank(grade: str) -> int:
        return order.get(str(grade or ""), -1)

    for row in rows:
        sid = str(row.get("stmt_id") or row.get("statement_id") or "")
        cur = str(row.get("evidence_kind") or "").strip()
        if str(row.get("kind") or "") == "concept":
            # 概念不参与等级链：它既不该被升档，也不是"凭据不够"。单列出来是为了
            # 不让"四栏加起来比行数少"变成一条看不见的缺口。
            out["concepts"].append({
                "statement_id": sid, "evidence_kind": cur,
                "why": "概念行不参与等级链（`evidencebits.derive_grade` 对它是 "
                       "`not_applicable`）⇒ 不归本命令管",
            })
            continue
        got = verifications._grade_recomputed_from_signature(row, root=root_p)
        reading = dict(got.get("reading") or {})
        if reading.get("checked") is False:
            # 判据自己报"没查成"（异常那一支）。先按 `checked=False` 分出去。
            out["columns"]["unchecked"].append({
                "statement_id": sid, "evidence_kind": cur, "state": "",
                "why": str(reading.get("why") or "凭据没查成（读不出来）"),
            })
            continue
        # 现算等级直接读五元位（唯一入口 `derive_grade`）；`reading` 只提供
        # "凭什么"（basis）与幂等判据，不提供等级 —— 后者由 `bits_from_row` 现算，
        # 这样"没签 / 凭据不够"的行也能被如实判成"该降档"（纠虚报那 105+ 条）。
        doc_kind = str(row.get("kind") or "")
        try:
            live_grade = EB.derive_grade(EB.bits_from_row(dict(row)), kind=doc_kind)
        except Exception:  # noqa: BLE001 —— 算不出来按"没查成"记，不折成"一致"
            out["columns"]["unchecked"].append({
                "statement_id": sid, "evidence_kind": cur, "state": "",
                "why": "五元位算不出来 ⇒ 这一行没查成（不是「一致」）",
            })
            continue
        cur_grade = EB.KIND_TO_GRADE.get(cur, "")
        if live_grade != cur_grade:
            direction = "up" if _rank(live_grade) > _rank(cur_grade) else "down"
            out["columns"]["will_upgrade"].append({
                "statement_id": sid,
                # `from` / `to` 是等级；档位两列并列给出，读的人不必自己换算。
                "from": cur_grade or "（空）", "to": live_grade,
                "from_kind": cur or "（空）",
                "to_kind": EB.kind_from_grade(live_grade),
                "direction": direction,
                "basis": str(reading.get("basis") or ""),
                "why": str(reading.get("why") or (
                    "历史档位与现算等级不一致：判定面读等级，重刷会按反算名改这一列"
                    "（两个方向都改；降档是纠虚报）")),
            })
            pending.append((out["columns"]["will_upgrade"][-1], dict(got["row"])))
            continue
        out["columns"]["already_consistent"].append(
            {"statement_id": sid, "grade": live_grade, "evidence_kind": cur})
        continue
    if apply and pending:
        _apply_grade_backfill(root_p, store, pending, out)
    return out


def _apply_grade_backfill(root: Path, store: Any,
                          pending: list[tuple[dict[str, Any], dict[str, Any]]],
                          out: dict[str, Any]) -> None:
    """`recompute_grades(apply=True)` 的写盘半：一行一笔事务 + 写后逐条读盘。

    ## 写的是什么（2026-11-05）
    写的是反算名：`evidencebits.kind_from_grade(等级)`。`_grade_recomputed_from_signature`
    只算等级、不写档位；这一格是"档位若还出现，只能由等级反算"那条纪律的唯一写者。
    事务内重新读这一行、再跑一次 `_grade_recomputed_from_signature`：调用方手上那份
    `pending` 是几毫秒前算的，而盘可能已经变过（另一个进程刚补过签 / 刚改过正文）。
    判据仍然只有那一处；这里只决定"还写不写"。
    """
    attempted: list[tuple[dict[str, Any], str]] = []
    for entry, _planned in pending:
        sid = str(entry.get("statement_id") or "")
        try:
            with store.tx("statements", actor="repair",
                          note=f"repair.backfill_grades:{sid}") as tx:
                # 按号定位走查口（口径一）。改前这里还认 `statement_id` 这个历史别名：
                # `statements` 的主键只有 `stmt_id`（`schema` 里没有那一列，`row_from_dict`
                # 也会丢掉未知键）⇒ 那一档是死别名，收口时按主键口径统一。
                current_got = SL.by_id(tx, stmt_id=sid)
                if not current_got["checked"]:
                    err = current_got.get("error") or {}
                    raise RuntimeError(
                        f"`statements` 读不出来（{err.get('type') or '?'}: "
                        f"{err.get('message') or current_got.get('reason') or '?'}）")
                current = current_got["row"] or None
                if current is None:
                    out["unmoved"].append({
                        "statement_id": sid,
                        "why": "事务里找不到这一行（两次读之间盘变过）⇒ 没动",
                    })
                    continue
                fresh = verifications._grade_recomputed_from_signature(current, root=root)
                trace = dict(fresh.get("reading") or {})
                try:
                    live = EB.derive_grade(EB.bits_from_row(dict(current)),
                                           kind=str(current.get("kind") or ""))
                except Exception:  # noqa: BLE001 —— 算不出来 ⇒ 没查成，不动
                    out["unmoved"].append({
                        "statement_id": sid,
                        "why": "事务内重算五元位失败 ⇒ 没查成，不动",
                    })
                    continue
                target_kind = EB.kind_from_grade(live)
                cur_now = str(current.get("evidence_kind") or "").strip()
                if not target_kind or target_kind == cur_now:
                    out["unmoved"].append({
                        "statement_id": sid,
                        "why": str(trace.get("why")
                                   or "重算结果与历史列已经一致（盘在两次读之间变过）⇒ 没动"),
                    })
                    continue
                if not trace:
                    # 凭据那一支没给出回执（没签 / 凭据不够），而等级与历史列确实不一致
                    # ⇒ 写盘仍要留痕。痕里的 `from`/`to` 是等级，`basis` 留空（没有签可指）。
                    trace = {
                        "checked": True, "from": EB.KIND_TO_GRADE.get(cur_now, ""),
                        "to": live, "from_kind": cur_now, "to_kind": target_kind,
                        "why": ("重刷：历史档位与现算等级不一致 ⇒ 按 `kind_from_grade` "
                                "反算改写这一列（没有签可指，basis 为空）"),
                        "basis": "", "proof_no": None, "at": verifications._now_iso(),
                    }
                current["evidence_kind"] = target_kind
                current[GRADE_RECOMPUTED_KEY] = dict(trace)
                tx.upsert("statements", current,
                          note=f"repair.backfill_grades:{sid}")
            attempted.append((entry, live))
        except Exception as exc:  # noqa: BLE001 —— 一条写失败不许拖住其余行
            out["failed"].append({
                "statement_id": sid,
                "why": f"{type(exc).__name__}: {exc}",
            })
    if not attempted:
        return
    # ---- 写后逐条再读一次盘（业主 2026-11-04）：事务返回 ≠ 盘上是那个样子。
    try:
        from .store import Store as _Store   # 惰性：只为一个"全新的读"开一个新句柄

        # 取数走查口的唯一取数口（三态：读不成不是 0 行）。
        disk_got, disk_problem, disk_error = SL.rows_of(_Store(root))
    except Exception as exc:  # noqa: BLE001 —— 读不回来就逐条记"没查成"
        disk_got, disk_problem = None, f"{type(exc).__name__}: {exc}"
        disk_error = {"type": type(exc).__name__, "message": str(exc)}
    if disk_problem:
        for entry, _target in attempted:
            out["unmoved"].append({
                "statement_id": str(entry.get("statement_id") or ""),
                "why": ("写完之后再读盘失败（"
                        f"{disk_error.get('type') or '?'}: "
                        f"{disk_error.get('message') or disk_problem}）"
                        "⇒ 这一条是「没查成」，不是「没动」"),
            })
        return
    # 索引的构造只有一处（查口 `index_by_id`）。改前这里还认 `statement_id`
    # 这个历史别名：`statements` 的主键只有 `stmt_id`（schema 里没有那一列，
    # `row_from_dict` 也会丢掉未知键）⇒ 那一档是死别名，按主键口径统一。
    disk_rows = SL.index_by_id(disk_got)
    for entry, target in attempted:
        sid = str(entry.get("statement_id") or "")
        disk = disk_rows.get(sid) or {}
        trace = dict(disk.get(GRADE_RECOMPUTED_KEY) or {})
        try:
            live_grade = EB.derive_grade(EB.bits_from_row(disk),
                                         kind=str(disk.get("kind") or ""))
        except Exception:  # noqa: BLE001 —— 读不回来按"没落到"记
            live_grade = ""
        if (live_grade == target
                and str(disk.get("evidence_kind") or "").strip() == EB.kind_from_grade(target)
                and str(trace.get("to") or "") == target):
            out["written"].append({
                "statement_id": sid, "from": str(entry.get("from") or ""),
                "to": target, "to_kind": EB.kind_from_grade(target),
                "at": str(trace.get("at") or ""),
                "basis": str(trace.get("basis") or ""),
            })
        else:
            out["unmoved"].append({
                "statement_id": sid,
                "why": (f"写完之后再读盘：现算等级={live_grade!r}、"
                        f"evidence_kind={disk.get('evidence_kind')!r}、"
                        f"{GRADE_RECOMPUTED_KEY}.to="
                        f"{str(trace.get('to') or '（没有痕）')!r} ⇒ 这一条没落到目标等级"),
            })


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    GRADE_BACKFILL_COLUMNS,
    GRADE_RECOMPUTED_KEY,
)

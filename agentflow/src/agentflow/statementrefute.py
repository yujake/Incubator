# -*- coding: utf-8 -*-
"""命题的另外两个终态：`refuted`（标记为错误）与「优化栏 = 难以自证」。

## 为什么这个模块存在（业主 2026-11-13 裁定）

| 档 | 命题怎么标 | 证据 | 稿 |
|---|---|---|---|
| 数学错误 | `status="refuted"` | 三选一（见下） | 一并作废（`manuscriptretire`） |
| 难以自证 | status 不动，只写优化栏 `hard_to_prove` | 一句理由 | 不动（业主：其它栏保留引文侧的样子，V 签还是占位） |

## 「标记为错误」的机器实现是已有的（业主问的那一条的答案）

`evidencebits` 里早就有一整套作废载荷，只是从来没有生产调用者：

- `VOID_CONDITIONS` / `void_refusal()`（`evidencebits.py`，§3.18 四条：脚本正常退出、
  脚本自己给 `refutes`、反例非空且可复现、D 判反例成立）；
- `void()`（返回 `bits.voided_by` 载荷：反例实验 / 一条构造 / 一行「有毛病」判词）；
- `cascade_void()` / `apply_cascade()`（依赖级联作废）；
- 读侧 `derive_grade` 见到 `bits.voided_by` 就把等级清零（回「猜想」），
  `bits_from_row` 还认旧名 `refuted_by`。

本模块不另造第二套：它只做"把那一套接到命题行的写入口上"这一件事，证据判据逐个
转调上面那些函数（`void_refusal` / `void`），一条都不重写。

## 三态（与 `statementabandon.apply_abandonment` 同一条纪律）

- `checked=True`：写成了（`amended=True`），或本来就是这一档（`already=True`，幂等）；
- `checked=False` + `refused`：不在册 / 没有 store / 证据不齐 / 证据判不过 / 写失败
  ⇒ 一个字节都不写（受控拒绝，不是异常）；
- 校验一律过 `schema`（`Statement.validate`），这里不另立一份数据面判据。
"""
from __future__ import annotations

from typing import Any, Mapping

from . import errorstate as _ES
from . import evidencebits as _EB
from . import schema as _S
from . import statementabandon as _SA
from . import statementledger as _SL

#: 作废证据三档：实验反例 / 一条构造 / 一行判词（`verifications/<号>.jsonl#v-…`）。
#: 多给一档 ⇒ 受控拒：凭哪一条作废必须说得清（"两件证据说不清"就是给自己留后路）。
REFUTE_EVIDENCE = ("experiment_id", "construction", "defect_ref")


class _InvariantBroken(ValueError):
    """同事务读回时"两处读法不恒等"（`status=错误` 而等级 / 载荷对不上）。

    它不是写失败，是写完之后这一行不合恒定式：整笔回滚比"写成功但读数分家"好 ——
    后者会让一行"状态说错、等级说猜想"的数据留在盘上，而没有任何一处会响。
    """


def _by_id(store: Any, stmt_id: str, *, tx: Any = None) -> tuple[dict | None, str, bool]:
    """按号定位（口径一）：返回 `(行, 原因, 查没查成)`。

    走 `statementledger.by_id` 这一处读口，不在这里另写一份"哪一列是主键"。
    """
    if tx is not None:
        got = _SL.by_id(rows=tx.rows("statements"), stmt_id=stmt_id)
    else:
        got = _SL.by_id(store, stmt_id=stmt_id)
    if not got.get("checked"):
        err = got.get("error") or {}
        return None, (f"`statements` 读不出来（{err.get('type', '?')}: "
                      f"{err.get('message', '?')}）⇒ 没查成"), False
    return (dict(got["row"]) if got.get("found") else None), "", True


def _write_row(store: Any, *, before: Mapping[str, Any], merged: Mapping[str, Any],
               note: str, actor: str, payload: Mapping[str, Any] | None = None,
               ) -> tuple[dict | None, str, str]:
    """整行重建 → 过 `Statement.validate` → 在一个事务里落盘。

    返回 `(写成的行, 拒码, 原因)`；拒码为空 = 写成了。受控拒要求一个字节都不写，
    所以校验全部赶在 `tx.upsert` 之前。

    ## 判它错的那一笔在这里 settle（业主 2026-11-13：同一事务）
    `payload` 非空 = 这一笔是"把命题判成错误"。三件事在这一处一起落盘：

    ① `status` 写 :data:`errorstate.ERROR_WORD`（词表里活着的那个词，补丁落地后自动 `error`）；
    ② `bits.voided_by` 写这份载荷；
    ③ `bits` 整份走 `normalize_raw` ⇒ `bits.grade` 由 `derive_grade` 现算（两种作废都读
       「错误」），不会留着旧的缓存等级。

    写完在同一個事务里读回跑 `errorstate.statement_refuted`：不是 `error` ⇒ 抛
    `_InvariantBroken` ⇒ 事务不提交。这就是"两处读法必须恒等"在写侧的落点 ——
    它防的不是"校验不严"，是"写成功了、而状态与等级各说一套"。
    """
    merged = dict(merged)
    if payload is not None:
        merged["status"] = _ES.ERROR_WORD
        bits = dict(merged.get("bits") or {})
        bits["voided_by"] = dict(payload)
        merged["bits"] = _EB.normalize_raw(
            bits, origin=str(merged.get("origin") or "own_result"),
            kind=str(merged.get("kind") or ""))
    history = [dict(h) for h in (before.get("_statement_amend_history") or [])
               if isinstance(h, Mapping)]
    changed = {k: {"from": before.get(k), "to": v}
               for k, v in merged.items() if before.get(k) != v}
    if changed:
        history.append({"at": _S.now_iso(), "by": actor, "task_id": "",
                        "changes": changed})
    row_in = dict(merged)
    row_in["_statement_amend_history"] = history[-20:]
    try:
        obj = _S.row_from_dict("statements", dict(row_in))
        obj.validate()
        canonical = obj.to_dict()
    except (TypeError, ValueError) as exc:
        return None, "refute_invalid_row", (
            f"改完之后这一行不是合法的命题行（{type(exc).__name__}: {exc}）⇒ 整笔不写")
    extra = {k: v for k, v in row_in.items() if k not in canonical}
    data = {**extra, **canonical}
    sid = str(data.get("stmt_id") or "")
    try:
        with store.tx("statements", actor=actor, note=note) as tx:
            now, why, ok = _by_id(store, sid, tx=tx)
            if not ok:
                return None, "statements_unreadable", why
            if now is None:
                return None, "refute_unknown_statement", (
                    f"命题 {sid} 在写事务里不见了 ⇒ 整笔不写")
            tx.upsert("statements", data, note=note)
            if payload is not None:
                # 同事务读回：这一笔是"判它错"，就必须读得出「状态=错误 ∧ 等级=错误」。
                after, _why2, _ok2 = _by_id(store, sid, tx=tx)
                reading = _ES.statement_refuted(row=after)
                if reading["state"] != _ES.STATE_ERROR:
                    raise _InvariantBroken(
                        f"写完之后同事务读回来不是「错误」（"
                        f"{reading['conflict'] or reading['state']}：{reading['why']}）"
                        "⇒ 整笔回滚（状态与等级不许只落一半）")
    except _InvariantBroken as exc:
        return None, "refute_invariant_broken", str(exc)
    except ValueError as exc:
        return None, "refute_write_refused", str(exc)
    except Exception as exc:  # noqa: BLE001 —— 写不进去要受控报出来
        return None, "refute_write_failed", (
            f"写不进去（{type(exc).__name__}: {exc}）⇒ 一行都没改")
    return data, "", ""


def _experiment_row(store: Any, experiment_id: str) -> tuple[dict | None, str]:
    """`experiments` 里那一行；读不出来 / 没有 ⇒ `(None, why)`（两档分开说）。"""
    if not str(experiment_id or "").strip():
        return None, "没给 experiment_id"
    try:
        rows = [dict(r) for r in store.rows("experiments")]
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        return None, f"`experiments` 读不出来（{type(exc).__name__}: {exc}）⇒ 没查成"
    hit = next((r for r in rows
                if str(r.get("experiment_id") or "") == str(experiment_id)), None)
    if hit is None:
        return None, f"`experiments` 里没有 {experiment_id!r} 这一行 ⇒ 引用了一行不存在的实验"
    return hit, ""


def refute_statement(store: Any, *, statement_id: Any, reason: Any = "", at: Any = "",
                     experiment_id: Any = "", construction: Any = "",
                     defect_ref: Any = "", counterexample_valid: Any = None,
                     actor: str = "secretary-B") -> dict[str, Any]:
    """把一条命题标记为错误（`status=错误那一档` + `bits.voided_by` 载荷）。

    状态词取 :data:`errorstate.ERROR_WORD`（今天是 `refuted`，词表补丁落地后自动 `error`），
    与等级「错误」是同一个概念的两处读法：写完由 `_write_row` 在同一个事务里读回校验。

    证据三选一（多给 / 不给都受控拒）：
    - `experiment_id`：`experiments` 里真有一行，且过 §3.18 四条（`void_refusal`）；
    - `construction`：一条构造（"它为什么假"的正文）；
    - `defect_ref`：`verifications/<6位命题号>.jsonl#v-<6位验证号>`，那一行判词「有毛病」
      且审的是现行正文（判据本体 `statementabandon._defect_refusal`，这里只转调）。

    ## 终态纪律
    错误那一档与 `abandoned` 都是终态：再作废一次是改写历史 ⇒ 受控拒（不是幂等放行）。
    已经是错误那一档的同一笔重放 ⇒ `already=True`、一个字节不写；读不出来的一行
    （`conflict` 非空）也不许覆盖（`refute_state_unreadable`）。

    ## 级联只落读数
    依赖它的那些命题（`derived_from`）按 `cascade_void` 读一遍，读数放在 `cascade` 里
    不改行（业主 2026-11-13：先只落读数，第二笔再裁要不要同事务改多行）。
    那件事本身不能省：`verify` 会按 `STATEMENT_UNUSABLE_STATUSES` 让压在它上面的
    proof 行报 error，而"被牵连的是哪几条"必须在写这一笔时就看得见。

    返回键与 `Secretary.amend_statement_meta` 同形（`checked` / `amended` / `already` /
    `changes` / `refused` / `reason` / `row`），外加 `voided_by` / `cascade` / `at`。
    """
    out: dict[str, Any] = {"checked": False, "amended": False, "already": False,
                           "stmt_id": str(statement_id or ""), "changes": [],
                           "refused": "", "reason": "", "why": "", "row": {},
                           "voided_by": {}, "cascade": {}, "at": "", "form": {}}
    sid = str(statement_id or "").strip()
    text = str(reason or "").strip()
    if not sid:
        out.update(refused="refute_missing_id", why="没给命题号 ⇒ 不知道作废哪一条（不猜）")
        return out
    if store is None:
        out.update(refused="store_unavailable", why="这一层没有 store ⇒ 写不了")
        return out
    if not text:
        out.update(refused="refute_reason_missing",
                   why=("标记为错误必须给理由（`refute_basis`）：只标一个 status='refuted' "
                        "等于把'为什么错'记成一笔没人能接手的账"))
        return out
    given = {"experiment_id": str(experiment_id or "").strip(),
             "construction": str(construction or "").strip(),
             "defect_ref": str(defect_ref or "").strip()}
    picked = [k for k, v in given.items() if v]
    if not picked:
        out.update(refused="refute_evidence_required",
                   why=("标记为错误必须给一件可核的证据，三选一：`experiment_id`"
                        "（反例实验）/ `construction`（一条构造）/ `defect_ref`"
                        "（一行「有毛病」的判词）—— 只写一句「我觉得错了」不算"))
        return out
    if len(picked) > 1:
        out.update(refused="refute_evidence_ambiguous",
                   why=("这一笔同时给了 " + "、".join(picked) + " ⇒ 说不清凭哪一条作废；"
                        "一次只交一件，读写的人都对得上"))
        return out
    stamp = str(at or "").strip() or _S.now_iso()
    row, why, checked = _by_id(store, sid)
    if not checked:
        out.update(refused="statements_unreadable", why=why)
        return out
    if row is None:
        out.update(refused="refute_unknown_statement",
                   why=f"命题 {sid} 不在册 ⇒ 作废一条不存在的命题（不新建行）")
        return out
    status_now = str(row.get("status") or "")
    reading = _ES.statement_refuted(row=row)
    if reading["state"] == _ES.STATE_ERROR:
        out.update(checked=True, already=True, row=row, at=stamp,
                   reason=(f"这一条早就是错误那一档（{_ES.ERROR_WORD}，终态）⇒ 一个字节都没写"
                           "（再作废一次是改写历史）"))
        return out
    if status_now == "abandoned":
        out.update(refused="refute_on_abandoned",
                   why=(f"命题 {sid} 已经被明确放弃（abandoned）⇒ 不能在同一条上再标错误："
                        "两个终态是两件事，换了档就读不出'当初是放弃还是被证否'"))
        return out
    if reading["state"] == _ES.STATE_UNKNOWN:
        # 读不出来的行（状态词不在词表 / 载荷在而状态没跟上 / 签口袋坏）不许覆盖：
        # 覆盖等于拿一笔新历史去盖住"这一行本来就读不出来"。
        out.update(refused="refute_state_unreadable",
                   why=(f"这一行现在读不出状态（{reading['conflict'] or '未知'}："
                        f"{reading['why']}）⇒ 整笔不写：先把它读出来，再判它错"))
        return out
    # ---- 证据：三选一，全部转调既有判据 -------------------------------------
    payload: dict[str, Any] = {}
    detail: dict[str, Any] = {}
    if given["experiment_id"]:
        exp, ewhy = _experiment_row(store, given["experiment_id"])
        if exp is None:
            out.update(refused="refute_experiment_unreadable", why=ewhy,
                       form={"experiment_id": given["experiment_id"]})
            return out
        verdict = str(exp.get("result") or "")
        refused = _EB.void_refusal(exp, verdict=verdict,
                                   counterexample_valid=counterexample_valid)
        if refused:
            out.update(refused="refute_experiment_not_evidence", why=(
                f"实验 {given['experiment_id']} 过不了 §3.18 的四条：{refused}"),
                form={"experiment_id": given["experiment_id"],
                      "exit_code": exp.get("exit_code"), "result": verdict,
                      "has_counterexample": bool(exp.get("counterexample"))})
            return out
        payload = _EB.void(exp, verdict=verdict,
                           counterexample_valid=counterexample_valid, reason=text)
        detail = {"experiment_id": given["experiment_id"]}
    elif given["construction"]:
        payload = _EB.void({}, construction=given["construction"], reason=text)
        detail = {"construction": given["construction"][:400]}
    else:
        ref = given["defect_ref"]
        root = str(getattr(store, "root", "") or "")
        d, code, dwhy = _SA._defect_refusal(store, root, ref, text,
                                            statement_id=sid, statement=row)
        if code:
            out.update(refused=code, why=dwhy, form={detail, d})
            return out
        payload = _EB.void({}, defect_ref=ref, reason=text)
        detail = dict(d)
    if not payload:
        out.update(refused="refute_evidence_required",
                   why="证据那一格没拼出作废载荷 ⇒ 整笔不写（不猜）")
        return out
    #: 作废时刻随载荷落盘（`voided_by.at`）：读数要能回答"几时判它错的"。
    #: 只标状态不写时刻，与放弃那一档"理由与时间缺一不可"是同一条纪律。
    payload["at"] = stamp
    #: status / 载荷 / 等级三件事由 `_write_row` 一处 settle（同一事务）⇒ 调用方不再各自拼。
    data, code, rwhy = _write_row(store, before=row, merged=dict(row),
                                 note=f"statement:error:{stamp}", actor=actor,
                                 payload=dict(payload))
    if code:
        out.update(refused=code, why=rwhy, form={**detail, "voided_by": dict(payload)})
        return out
    out.update(checked=True, amended=True, row=data, at=stamp, voided_by=dict(payload),
               form=dict(detail),
               changes=[f"status: {status_now} → {_ES.ERROR_WORD}",
                        f"bits.voided_by: {str(payload.get('kind') or '')}",
                        f"bits.grade: → {_EB.GRADE_ERROR}"],
               reason=(f"命题 {sid} 已标记为错误（{_ES.ERROR_WORD}，{stamp}）：凭据是 "
                       f"{str(payload.get('kind') or '')}"))
    out["cascade"] = _cascade_reading(store, sid, reason=text)
    out["resubmits"] = _SA.close_resubmits(store, statement_id=sid,
                                          why=f"命题 {sid} 已被标记为错误")
    return out


def _cascade_reading(store: Any, statement_id: str, *, reason: str) -> dict[str, Any]:
    """读一遍"谁压在它上面"（`cascade_void`，只读不写）。"""
    try:
        rows = [dict(r) for r in store.rows("statements")]
        got = _EB.cascade_void(rows, root=statement_id, reason=reason)
    except Exception as exc:  # noqa: BLE001 —— 读不出来要如实说（不是"没有牵连"）
        return {"checked": False, "why": f"级联读数没跑成（{type(exc).__name__}: {exc}）"}
    return {"checked": True, "dependents": list(got.get("dependents") or []),
            "cycles": list(got.get("cycles") or []),
            "missing": list(got.get("missing") or []),
            "note": str(got.get("note") or ""),
            "applied": False}


def mark_hard_to_prove(store: Any, *, statement_id: Any, basis: Any = "",
                       proof_no: Any = 1, at: Any = "",
                       actor: str = "secretary-B") -> dict[str, Any]:
    """把一条命题的优化栏写成「难以自证」（不动 status、不动 V 签占位）。

    业主 2026-11-13：「就是优化栏写难以自证，其它栏保留引文侧录入的样子，如 V 签还是占位」。

    ## 边界（三条都是硬拒）
    - 概念 / 定义行（`NOT_APPLICABLE_KINDS`）不是命题 ⇒ 没有"优化栏"这回事；
    - 命题已经退休（`abandoned` / `refuted`）⇒ 优化栏不再有意义；
    - 同一份证明已经记过 `optimized=true` ⇒ "已优化"与"难以自证"不能并存
      （两个都是对同一件事的结论，同时成立就是自相矛盾）。

    ## 写入的东西只有一格
    `bits.evidence.hard_to_prove_by_proof[证明号] = {basis, at}`。`status` / `bits.reviewed` /
    `bits.evidence.reviewed_source` / `quote_reason` 一个字节都不动 —— 占位签仍读作占位签。

    幂等：同一份证明、同一句理由重放 ⇒ `already=True`、不写；换了理由 ⇒ 改写那一格。
    """
    out: dict[str, Any] = {"checked": False, "amended": False, "already": False,
                           "stmt_id": str(statement_id or ""), "changes": [],
                           "refused": "", "reason": "", "why": "", "row": {},
                           "hard_to_prove": {}, "at": "", "form": {}}
    sid = str(statement_id or "").strip()
    text = str(basis or "").strip()
    if not sid:
        out.update(refused="hard_to_prove_missing_id", why="没给命题号 ⇒ 不知道记哪一条（不猜）")
        return out
    if store is None:
        out.update(refused="store_unavailable", why="这一层没有 store ⇒ 写不了")
        return out
    if not text:
        out.update(refused="hard_to_prove_basis_missing",
                   why=("优化栏写「难以自证」必须给一句理由（`hard_to_prove`）："
                        "只标一档不说难在哪，父代理没法判断要不要把它当研究任务上报"))
        return out
    stamp = str(at or "").strip() or _S.now_iso()
    row, why, checked = _by_id(store, sid)
    if not checked:
        out.update(refused="statements_unreadable", why=why)
        return out
    if row is None:
        out.update(refused="hard_to_prove_unknown_statement",
                   why=f"命题 {sid} 不在册 ⇒ 记不了一条不存在的命题")
        return out
    status_now = str(row.get("status") or "")
    if _SA.is_abandon_exempt(row.get("kind")):
        out.update(refused="hard_to_prove_not_a_proposition",
                   why=(f"命题 {sid} 的 kind 是 {row.get('kind')!r}（概念 / 定义）⇒ "
                        "它不是命题，没有「优化」这件事"))
        return out
    reading = _ES.statement_refuted(row=row)
    if status_now == "abandoned" or reading["state"] == _ES.STATE_ERROR:
        out.update(refused="hard_to_prove_on_retired",
                   why=(f"命题 {sid} 已经退休（{status_now}）⇒ 优化栏不再有意义"
                        "（退休的命题不会再被洗）"))
        return out
    no = 1
    try:
        no = int(proof_no)
    except (TypeError, ValueError):
        no = 1
    if no < 1:
        no = 1
    existing = _EB.hard_to_prove_entry(row, no)
    if existing and str(existing.get("basis") or "") == text:
        out.update(checked=True, already=True, row=row, at=str(existing.get("at") or stamp),
                   hard_to_prove=dict(existing),
                   reason="同一份证明的优化栏已经记着这一句（幂等：一个字节都没写）")
        return out
    if _EB.optimized_by_proof(row).get(no):
        out.update(refused="hard_to_prove_after_optimized",
                   why=("这一份已经记着 optimized=true ⇒ 不能再记「难以自证」："
                        "两个结论同时成立就是自相矛盾（先由人裁哪一条才算）"))
        return out
    bits = _EB.with_hard_to_prove(row.get("bits") or {}, no, basis=text, at=stamp)
    merged = dict(row)
    merged["bits"] = bits
    data, code, rwhy = _write_row(store, before=row, merged=merged,
                                 note=f"statement:hard_to_prove:{stamp}", actor=actor)
    if code:
        out.update(refused=code, why=rwhy)
        return out
    out.update(checked=True, amended=True, row=data, at=stamp,
               hard_to_prove={"basis": text, "at": stamp})
    out["changes"] = [f"bits.evidence.hard_to_prove_by_proof[{no}]"]
    out["reason"] = (f"命题 {sid} 的优化栏已记「难以自证」（{stamp}）："
                     "status 与 V 签占位一个字节都没动；请把它报给父代理")
    return out

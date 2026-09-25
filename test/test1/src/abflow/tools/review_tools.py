"""H 的工具：**审校**。

## 这个模块存在的最重要理由

**审校者的判断也需要证据。**

这是本项目上一阶段最刺痛的一条教训：评审方提出的一条「缺陷」
（「medium 置信度泄漏进了正文」）是**错的**，是实现方拿证据顶回来才纠正的。
如果审校记录可以只写「这里有问题」而不给依据，审校就会变成
**另一种幻觉的来源** —— 而且因为审校者站在更高的位置，它更难被纠正。

因此：

1. `schema.ReviewFinding.evidence` **必填非空**（写入时硬约束）；
2. 本模块的每个检查都给出 `evidence` 字段，内容是**触发该发现的实际值**
   （例如 `citations=[]`、`evidence_kind='cross_check' 且 disclaimer 为空`），
   而不是一句「看起来不对」；
3. **H 只读**：它提发现，不改稿。改稿由 G 做。这不是分工洁癖 ——
   若审校者能直接改，它就同时是「发现者」与「修正者」，
   于是「发现问题」与「掩盖问题」在结构上无法区分。

## 「H 只读」在本模块里的落地形态（两条，缺一不可）

- **默认注册面只读**：`register()` 只注册 `review.scan_document`（`none`）
  与 `review.list_findings`（`read`）。会写盘的两个入口
  （`review.review_document` / `review.verify_fixes`，均为 `write_local`）
  必须显式 `include_writers=True` 才会被装配 —— 于是「H 的工具面」
  （默认装配结果）在结构上不含任何写工具。
- **它们是 H 的代理步骤，不是 H 的刀**：这两个写工具的落点被钉死在
  `review_findings`（新增/改状态）与 `documents.status` 上，
  **一个字都不改 `claims` / `knowledge tables`**。改稿这件事在 H 侧根本没有入口。

## 判据只有一份

`scan_document` 是唯一的机械判据，G 侧的 `doc_tools.scan_claim` 与它同词表
（`schema.FINDING_KINDS`）。本模块**不另写一套检查** —— 两套判据必然漂移，
而漂移的后果是「G 认为合规、H 认为违规」这种**没有任何报错**的静默分裂。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .. import schema as S
from .base import ToolRegistry, ToolSpec, fail, ok
from .doc_tools import OVERCLAIM_MARKERS, dependencies_for_doc, guard_result as _guard_result

#: H 审校；G 需要看到发现才能修订（**看不到发现的 G 无法闭环**）；
#: F/D 需要知道哪些结论还带着未闭合的发现。
_ROLES = ("H", "G", "F", "D")

#: 写盘入口的角色。刻意只挂 H：写发现是审校者的本职，而不是让作者替审校者记账。
_WRITER_ROLES = ("H",)

#: 默认值哨兵（沿用 `agent_d._UNSPECIFIED` 的用法）：
#: 不传 = 「自己去库里读依赖」；显式传 `None` = 「调用方没有依赖清单 ⇒ **没查**」。
#: 「没查」与「查了、依赖都闭合」必须能分开（FC-01 三态纪律）。
_UNSPECIFIED: Any = object()


# ---------------------------------------------------------------- 纯函数判据


def scan_document(
    doc: Mapping[str, Any],
    *,
    dependencies: Sequence[Mapping[str, Any]] | None = None,
) -> dict:
    """对一份稿件做**全量机械审校**。纯函数，不碰存储。

    检查项（每一项都可判定，且都给出 evidence）：

    - `unsupported_claim` —— 断言无引用；
    - `overclaim` —— `evidence_kind != "proof"` 却出现证明性措辞，或
      `cross_check` 缺 disclaimer；
    - `missing_negation_kind` —— 否定型断言未分类；
    - `dangling_dep` —— 该稿件登记的依赖里有 `dangling` / `external_unavailable` 的
      （**这是 FC-23 的落地**：引用了拿不到的定理，必须是一条可见的发现，而不是
      藏在引文角标里）；
    - `inconsistent_number` —— 同一份稿件里同一个 claim_key 出现互相矛盾的数字
      （当前版本只检查「同一 claim_id 重复出现且 text 不同」，这是可判定的那一层）。

    ⚠️ **本函数不判断数学对不对。** 它判的是「稿件有没有把自己说清楚」：
    有没有引用、证据等级有没有被夸大、依赖有没有闭合。把这两件事分清，
    是审校可被信任的前提 —— 一个声称「我检查了证明」的自动审校器是危险的。

    三态：`dependencies=None` ⇒ `dep_check.checked=False`（**没查**），
    与「查了、依赖都闭合」（`checked=True, findings=[]`）严格区分。
    """
    findings: list[dict] = []
    doc_id = str(doc.get("doc_id") or "?")
    claims = doc.get("claims") or []

    seen_ids: dict[str, str] = {}
    for i, c in enumerate(claims):
        if not isinstance(c, Mapping):
            findings.append(
                {
                    "kind": "garbled",
                    "level": "error",
                    "target": f"claims[{i}]",
                    "evidence": f"claims[{i}] 的类型是 {type(c).__name__}，不是对象",
                    "message": "断言必须是对象",
                }
            )
            continue
        cid = str(c.get("claim_id") or f"claims[{i}]")
        text = str(c.get("text") or "")
        cites = c.get("citations") or []
        ek = c.get("evidence_kind")

        # ---- 无引用
        if not cites:
            findings.append(
                {
                    "kind": "unsupported_claim",
                    "level": "error",
                    "target": cid,
                    "evidence": f"claim_id={cid} 的 citations={cites!r}（空）",
                    "message": "断言没有引用：数学断言的价值取决于它来自哪里",
                }
            )
        # ---- 过度声称
        if ek == "cross_check" and not str(c.get("disclaimer") or "").strip():
            findings.append(
                {
                    "kind": "overclaim",
                    "level": "error",
                    "target": cid,
                    "evidence": f"evidence_kind={ek!r} 且 disclaimer 为空",
                    "message": "数值交叉验证必须显式声明'不构成证明'",
                }
            )
        if ek in S.EVIDENCE_KINDS and ek != "proof":
            hit = [m for m in OVERCLAIM_MARKERS if m in text]
            if hit:
                findings.append(
                    {
                        "kind": "overclaim",
                        "level": "error",
                        "target": cid,
                        "evidence": f"evidence_kind={ek!r} 但正文含 {'、'.join(hit)}；正文摘要：{text[:80]!r}",
                        "message": "把交叉验证写成了证明",
                    }
                )
        # ---- 否定分类
        if c.get("is_negative") is True and not c.get("negation_kind"):
            findings.append(
                {
                    "kind": "missing_negation_kind",
                    "level": "error",
                    "target": cid,
                    "evidence": f"is_negative=True 且 negation_kind={c.get('negation_kind')!r}",
                    "message": "'未证明'与'已证否'必须分开",
                }
            )
        # ---- 重复 claim_id 且文本不同（可判定的"自相矛盾"）
        if cid in seen_ids and seen_ids[cid] != text:
            findings.append(
                {
                    "kind": "inconsistent_number",
                    "level": "error",
                    "target": cid,
                    "evidence": f"同一 claim_id={cid} 出现两次且 text 不同：{seen_ids[cid][:60]!r} vs {text[:60]!r}",
                    "message": "同一断言标识对应两段不同文字",
                }
            )
        seen_ids[cid] = text

    # ---- 依赖闭合（FC-23）
    if dependencies is None:
        dep_check = {
            "checked": False,
            "reason": "调用方未提供 dependencies ⇒ **没查依赖闭合**（不得读成'依赖都闭合'）",
            "open": [],
        }
    else:
        open_deps = [
            {
                "dep_id": str(d.get("dep_id") or ""),
                "status": str(d.get("status") or ""),
                "label": str(d.get("label") or ""),
                "status_reason": str(d.get("status_reason") or ""),
            }
            for d in dependencies
            if str(d.get("status") or "") in ("dangling", "external_unavailable")
        ]
        for d in open_deps:
            # ⚠️ 分级（FC-13）：`external_unavailable` 是"我们**已经知道并记录**了这个前提
            # 拿不到" —— 那是**已知边界**，不是谎报，所以是 warning。
            # 而 `dangling` 是"登记了一个依赖却既没闭合、也没说明为什么拿不到" —— 那是
            # **没交代**，属于 error。把两者都报成 error 会把红灯训练成噪音。
            lvl = "warning" if d["status"] == "external_unavailable" else "error"
            findings.append(
                {
                    "kind": "dangling_dep",
                    "level": lvl,
                    "target": d["dep_id"],
                    "evidence": (
                        f"dep_id={d['dep_id']} status={d['status']!r} label={d['label']!r}；"
                        f"status_reason={d['status_reason'][:120]!r}"
                    ),
                    "message": (
                        "引用了外部结论但本项目拿不到来源（已知边界，需人确认前提）"
                        if d["status"] == "external_unavailable"
                        else "依赖悬空且没有说明原因"
                    ),
                }
            )
        dep_check = {"checked": True, "reason": f"检查了 {len(list(dependencies))} 条依赖", "open": open_deps}

    errors = [f for f in findings if f["level"] == "error"]
    warnings = [f for f in findings if f["level"] == "warning"]
    return {
        "checked": True,
        "doc_id": doc_id,
        "findings": findings,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "info_count": len(findings) - len(errors) - len(warnings),
        "dep_check": dep_check,
        # ---- FC-10：三分档计数，禁止单一通过率。
        # "通过率 80%" 会掩盖"20% 是失败还是未检查"这个决定性差异。
        "verdict": "rejected" if errors else ("accepted_with_warnings" if warnings else "accepted"),
    }


# ---------------------------------------------------------------- 内部工具


def _doc_of(store: Any, doc_id: str) -> dict:
    row = next((r for r in store.rows("documents") if str(r.get("doc_id")) == str(doc_id)), None)
    if row is None:
        raise ValueError(f"稿件 {doc_id} 不存在（documents 表里没有这一行）⇒ 不能审一份不存在的稿件")
    return dict(row)


def _resolve_deps(store: Any, doc_id: str, dependencies: Any) -> tuple[Any, bool]:
    """把 `dependencies` 参数解析成 (传给 scan_document 的值, 是否查过)。

    哨兵 / 显式 None 的区别就是三态纪律本身：
    「我自己去库里读了」（查过）与「调用方没给清单」（**没查**）不能混。
    """
    if dependencies is _UNSPECIFIED:
        return dependencies_for_doc(store.rows("dependencies"), doc_id), True
    if dependencies is None:
        return None, False
    return [dict(d) for d in dependencies], True


def _set_doc_status(store: Any, doc_id: str, target: str, *, actor: str) -> tuple[bool, str | None, str]:
    """只改 `documents` 行的 `status` 字段。返回 (是否写成, 错误, 当前状态)。

    ## 为什么只改 status，连 `updated_at` 都不碰

    "H 只读"必须有一个**可核对的形式**：调用前后逐字节比对 `documents.json`，
    变化点应当**有且只有** status。顺手更新 `updated_at` 看起来无害，
    但它会让"H 到底动了什么"从"一眼看清"退化成"要逐字段 diff 才知道"。

    ## 为什么这个写会失败（而且必须如实报告）

    `Document.validate` 会在提交时校验**整张 documents 表**。若盘上这份稿件
    本身不合 schema（例如是手工改坏的、或旧版本写的），那么连"把它的状态改成
    in_review"都写不进去。这不是可以掩盖的细节：**发现照样落库，状态更新失败
    这件事本身也要出现在返回值里**，否则调用方会以为"审校流程正常结束了"。
    """
    cur = next(
        (str(r.get("status")) for r in store.rows("documents") if str(r.get("doc_id")) == str(doc_id)),
        "",
    )
    if cur == target:
        return True, None, cur
    try:
        with store.tx("documents", actor=actor, note=f"review status {cur}->{target}") as tx:
            row = tx.find("documents", doc_id=str(doc_id))
            if row is None:
                return False, f"稿件 {doc_id} 在事务内不存在", cur
            row["status"] = target
            tx.upsert("documents", row)
    except Exception as e:  # noqa: BLE001 - 见 docstring：失败必须被记录，不能被吞掉或上抛
        return False, f"{type(e).__name__}: {e}", cur
    return True, None, target


def _apply_finding_status(
    store: Any, changes: Sequence[Mapping[str, Any]], *, actor: str, note: str
) -> list[dict]:
    """批量改 finding 的 `status`（以及必要时补 `resolution_note`）。

    ⚠️ 只允许改这两个字段：finding 的 `kind/level/target/evidence/message` 是
    H 当初的**判断依据**，重算时不许被改写 —— 否则"当初为什么这么判"就没有了。
    """
    done: list[dict] = []
    if not changes:
        return done
    with store.tx("review_findings", actor=actor, note=note) as tx:
        for ch in changes:
            row = tx.find("review_findings", finding_id=str(ch["finding_id"]))
            if row is None:
                continue
            if row.get("status") == ch["status"]:
                continue
            row["status"] = ch["status"]
            if ch.get("resolution_note"):
                row["resolution_note"] = str(ch["resolution_note"])
            tx.upsert("review_findings", row)
            done.append({"finding_id": row["finding_id"], "status": row["status"]})
    return done


def _dedup_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """去重键：`(kind, target, message)`（doc_id 在调用处限定）。"""
    return (str(row.get("kind")), str(row.get("target")), str(row.get("message")))


# ---------------------------------------------------------------- 审校（写发现）


def review_document(
    store: Any,
    doc_id: str,
    *,
    round_no: int | None = None,
    dependencies: Any = _UNSPECIFIED,
    actor: str = "agent-H",
) -> dict:
    """审一份稿件：把机械发现落成 `ReviewFinding` 行，并更新 `documents.status`。

    返回 ``{"doc_id","checked","round","new_findings","duplicate_skipped","reopened",
    "error_count","warning_count","info_count","dep_check","status","status_updated",
    "status_error","verdict","reason"}``。

    ## 三段式（为什么是三个事务而不是一个）

    1. **落发现**（`review_findings`）：发现是审校的**产出**，必须落库 ——
       "发现了但没记下来"等于没发现。
    2. **重开谎报**（`review_findings`）：G 把一条 finding 标成 `fixed` 之后，
       如果重跑检查**仍然复现**，这条 finding 会被**重新打开**。没有这一步，
       G 只要点一下"已修复"，审校就只看状态、成了盖章机。
    3. **改状态**（`documents`，**独立事务**）：稿件可能本身不合 schema，
       于是这一步会失败。把它与落发现分开，失败时才不会连发现一起丢掉。

    ## 三态：`dependencies` 没查 ⇒ 不许判 accepted

    `dep_check.checked is False` 时 verdict 是 `"unverified"`，文档状态停在
    `in_review` —— 「依赖都闭合」这句话在没有查过的情况下**不许说出口**。
    """
    doc_id = str(doc_id)
    doc = _doc_of(store, doc_id)
    deps, _dep_provided = _resolve_deps(store, doc_id, dependencies)
    scan = scan_document(doc, dependencies=deps)

    existing = [dict(r) for r in store.rows("review_findings") if str(r.get("doc_id")) == doc_id]
    if round_no is None:
        # 轮次从"该稿件已有发现的最大轮次"往后走 —— 用库里的既有事实推，
        # 而不是用一个内存计数器：审校必须能被中断后接着跑。
        round_no = max((int(r.get("round") or 1) for r in existing), default=0) + 1
    round_no = int(round_no)
    if round_no < 1:
        raise ValueError("round_no 从 1 开始")

    seen = {_dedup_key(r) for r in existing}
    pending: list[dict] = []
    duplicate_skipped = 0
    for f in scan["findings"]:
        key = _dedup_key(f)
        if key in seen:
            duplicate_skipped += 1
            continue
        seen.add(key)
        pending.append(f)

    new_findings: list[dict] = []
    if pending:
        with store.tx(
            "review_findings", actor=actor, note=f"review_document doc:{doc_id} round {round_no}"
        ) as tx:
            for f in pending:
                row = S.ReviewFinding(
                    finding_id="",
                    doc_id=doc_id,
                    kind=str(f["kind"]),
                    level=str(f["level"]),
                    target=str(f["target"]),
                    # evidence 由 scan_document 给出（触发该发现的**实际值**）。
                    # 它绝不会是空的：schema.ReviewFinding.validate 会拒绝空 evidence，
                    # 这里也再核一次，让错误带上"是哪条检查没给证据"。
                    evidence=str(f["evidence"]),
                    message=str(f["message"]),
                    round=round_no,
                    suggestion=str(f.get("suggestion") or ""),
                    status="open",
                    resolution_note="",
                    created_at=S.now_iso(),
                    created_by=actor,
                )
                row.finding_id = tx.alloc_id("finding")
                row.validate()
                payload = row.to_dict()
                tx.upsert("review_findings", payload)
                new_findings.append(payload)

    # ---- 重开"标了 fixed 但其实还在"的发现（防止 G 用点状态的方式修好问题）
    current_keys = {_dedup_key(f) for f in scan["findings"]}
    reopened: list[dict] = []
    to_reopen = [
        r
        for r in existing
        if str(r.get("status")) == "fixed" and _dedup_key(r) in current_keys
    ]
    if to_reopen:
        _apply_finding_status(
            store,
            [
                {
                    "finding_id": r["finding_id"],
                    "status": "open",
                    "resolution_note": (
                        f"[round {round_no}] 重跑对应检查**仍然复现** ⇒ 之前的 fixed 不成立，重新打开"
                    ),
                }
                for r in to_reopen
            ],
            actor=actor,
            note=f"reopen doc:{doc_id}",
        )
        reopened = [{"finding_id": r["finding_id"], "kind": r.get("kind"), "target": r.get("target")} for r in to_reopen]

    dep_checked = bool(scan["dep_check"].get("checked"))
    if scan["error_count"]:
        verdict = "rejected"
    elif not dep_checked:
        # 「依赖闭合没查」不等于「依赖闭合」—— 不许在这个前提下判 accepted。
        verdict = "unverified"
    elif scan["warning_count"]:
        verdict = "accepted_with_warnings"
    else:
        verdict = "accepted"

    target_status = "accepted" if (scan["error_count"] == 0 and dep_checked) else "in_review"
    status_updated, status_error, status_now = _set_doc_status(store, doc_id, target_status, actor=actor)

    reason_bits = [
        f"机械检查发现 error={scan['error_count']}、warning={scan['warning_count']}、info={scan['info_count']}",
        (
            f"依赖闭合已检查（{scan['dep_check'].get('reason')}）"
            if dep_checked
            else f"依赖闭合**没查**（{scan['dep_check'].get('reason')}）⇒ 不能判 accepted"
        ),
        f"新增发现 {len(new_findings)} 条、与已有发现重复被跳过 {duplicate_skipped} 条",
    ]
    if reopened:
        reason_bits.append(f"重开 {len(reopened)} 条「标了 fixed 但重跑仍复现」的发现")
    if not status_updated:
        reason_bits.append(f"⚠️ 文档状态**未能更新**（{status_error}）—— 这通常因为盘上这份稿件本身不合 schema")

    return {
        "doc_id": doc_id,
        "checked": True,
        "round": round_no,
        "new_findings": new_findings,
        "duplicate_skipped": duplicate_skipped,
        "reopened": reopened,
        "error_count": scan["error_count"],
        "warning_count": scan["warning_count"],
        "info_count": scan["info_count"],
        "dep_check": scan["dep_check"],
        "status": status_now,
        "status_updated": status_updated,
        "status_error": status_error,
        "verdict": verdict,
        "reason": "；".join(reason_bits) + "。",
    }


# ---------------------------------------------------------------- 复审（判 fixed / open）


def verify_fixes(
    store: Any,
    doc_id: str,
    *,
    round_no: int,
    dependencies: Any = _UNSPECIFIED,
    max_review_rounds: int = 2,
    actor: str = "agent-H",
) -> dict:
    """复审：对上一轮的每条 finding **重跑对应检查**，判定 `fixed` / 仍 `open`。

    返回 ``{"doc_id","round","resolved","still_open","unresolved_findings","verdict",
    "reason",...}``。

    ## 终止性（FC-18 的同族要求）

    `error` 级发现一直不修、且已经到 `max_review_rounds` ⇒ 文档状态置
    `unresolved_review`，并且**必须把未解决的 finding 明确列出来**
    （`unresolved_findings` 非空）。「跑了 N 轮还是红」如果只体现在一个状态字符串上，
    接手的人就无从知道到底卡在哪一条 —— 不许隐藏。

    ## 判定口径

    判据**不是** G 自称修好了，而是"重跑检查还复现吗"：
    复现 ⇒ `open`（即使 G 已经把它标成 `fixed`，也会被重新打开）；
    不复现 ⇒ `fixed`。此外当前扫描里**新出现**的问题会以 `source="new_issue"`
    出现在 `still_open` 里（复审不是"只看旧账"）。
    """
    doc_id = str(doc_id)
    round_no = int(round_no)
    if round_no < 1:
        raise ValueError("round_no 从 1 开始")
    max_review_rounds = int(max_review_rounds)
    if max_review_rounds < 1:
        raise ValueError("max_review_rounds 至少为 1")

    doc = _doc_of(store, doc_id)
    deps, dep_checked = _resolve_deps(store, doc_id, dependencies)
    scan = scan_document(doc, dependencies=deps)
    current = {_dedup_key(f): f for f in scan["findings"]}
    findings = [dict(r) for r in store.rows("review_findings") if str(r.get("doc_id")) == doc_id]
    prev = [r for r in findings if int(r.get("round") or 1) < round_no]

    resolved: list[dict] = []
    still_open: list[dict] = []
    for r in prev:
        base = {
            "finding_id": r.get("finding_id"),
            "kind": r.get("kind"),
            "level": r.get("level"),
            "target": r.get("target"),
            "message": r.get("message"),
            "round": r.get("round"),
            "status": r.get("status"),
        }
        key = _dedup_key(r)
        if key in current:
            base["evidence"] = current[key].get("evidence")
            base["source"] = "prev_round"
            still_open.append(base)
        else:
            resolved.append(base)
    prev_keys = {_dedup_key(r) for r in prev}
    for key, f in current.items():
        if key in prev_keys:
            continue
        still_open.append(
            {
                "finding_id": None,
                "kind": f["kind"],
                "level": f["level"],
                "target": f["target"],
                "message": f["message"],
                "evidence": f.get("evidence"),
                "round": None,
                "status": "open",
                "source": "new_issue",
            }
        )

    # ---- 落状态：resolved ⇒ fixed；复现的旧账 ⇒ 重新打开（含"谎报修好")
    changes: list[dict] = []
    for item in resolved:
        changes.append(
            {
                "finding_id": item["finding_id"],
                "status": "fixed",
                "resolution_note": f"[round {round_no}] 重跑对应检查不再复现 ⇒ fixed",
            }
        )
    for item in still_open:
        if item.get("source") != "prev_round":
            continue
        if str(item.get("status")) != "fixed":
            continue
        changes.append(
            {
                "finding_id": item["finding_id"],
                "status": "open",
                "resolution_note": (
                    f"[round {round_no}] G 曾标为 fixed，但重跑对应检查**仍然复现** ⇒ 判定不成立，重新打开"
                ),
            }
        )
        item["status"] = "open"
        item["reopened"] = True
    finding_updates = _apply_finding_status(
        store, changes, actor=actor, note=f"verify_fixes doc:{doc_id} round {round_no}"
    )

    # ---- 判定（用"当前仍存在的 error"作准，而不是用 G 的自述）
    blocking = [
        f for f in still_open if str(f.get("level")) == "error" and str(f.get("status")) in ("open", "fixed")
    ]
    if not still_open:
        verdict = "accepted"
    elif blocking and round_no >= max_review_rounds:
        verdict = "unresolved_review"
    elif blocking:
        verdict = "revise_again"
    else:
        # 只剩 warning（已记录的已知边界）或已被人明确 wontfix 的项：
        # 它们仍然列在 still_open 里（不许隐藏），但不该把红灯训练成噪音（FC-13）。
        verdict = "accepted"

    target_status = {"accepted": "accepted", "revise_again": "in_review", "unresolved_review": "unresolved_review"}[
        verdict
    ]
    status_updated, status_error, status_now = _set_doc_status(store, doc_id, target_status, actor=actor)

    unresolved = [f for f in blocking]
    reason_bits = [
        f"第 {round_no} 轮复审（上限 max_review_rounds={max_review_rounds}）："
        f"上一轮 {len(prev)} 条发现里 resolved={len(resolved)}、仍复现={len(still_open) - len([f for f in still_open if f.get('source') == 'new_issue'])}",
        f"error 级未解决 {len(unresolved)} 条",
    ]
    if not dep_checked:
        reason_bits.append("⚠️ 依赖闭合**没查**（dependencies=None）⇒ 本轮结论不覆盖依赖闭合这一维")
    if verdict == "unresolved_review":
        reason_bits.append(
            "已达轮数上限且 error 级发现仍 open ⇒ 停止自动修订，交人复核（**未解决的发现已全部列出**，未隐藏）"
        )
    if not status_updated:
        reason_bits.append(f"⚠️ 文档状态**未能更新**（{status_error}）")

    return {
        "doc_id": doc_id,
        "round": round_no,
        "resolved": resolved,
        "still_open": still_open,
        "unresolved_findings": unresolved,
        "verdict": verdict,
        "reason": "；".join(reason_bits) + "。",
        "error_count": scan["error_count"],
        "warning_count": scan["warning_count"],
        "info_count": scan["info_count"],
        "dep_check": scan["dep_check"],
        "finding_updates": finding_updates,
        "status": status_now,
        "status_updated": status_updated,
        "status_error": status_error,
    }


# ---------------------------------------------------------------- 只读列举


def list_findings(
    store: Any,
    *,
    doc_id: str | None = None,
    status: str | None = None,
    level: str | None = None,
) -> dict:
    """只读列举审校发现。"""
    if status is not None and status not in S.FINDING_STATUSES:
        raise ValueError(f"status 必须是 {S.FINDING_STATUSES} 之一，收到 {status!r}")
    if level is not None and level not in S.FINDING_LEVELS:
        raise ValueError(f"level 必须是 {S.FINDING_LEVELS} 之一，收到 {level!r}")
    out: list[dict] = []
    for r in sorted(store.rows("review_findings"), key=lambda x: str(x.get("finding_id"))):
        if doc_id is not None and str(r.get("doc_id")) != str(doc_id):
            continue
        if status is not None and r.get("status") != status:
            continue
        if level is not None and r.get("level") != level:
            continue
        out.append(
            {
                "finding_id": r.get("finding_id"),
                "doc_id": r.get("doc_id"),
                "kind": r.get("kind"),
                "level": r.get("level"),
                "target": r.get("target"),
                "message": r.get("message"),
                "evidence": r.get("evidence"),
                "status": r.get("status"),
                "round": r.get("round"),
                "resolution_note": r.get("resolution_note"),
            }
        )
    return {"count": len(out), "findings": out}


# ---------------------------------------------------------------- 工具装配


def register(
    registry: ToolRegistry,
    *,
    store: Any = None,
    include_writers: bool = False,
    actor: str = "agent-H",
    **_: Any,
) -> None:
    """装配审校工具。

    ## 为什么写工具默认**不**注册

    「H 的工具面必须全部 `side_effect in ("none","read")`」是结构约束，不是口号。
    默认注册面只有 `review.scan_document`（`none`）与 `review.list_findings`（`read`）；
    会写盘的两个入口必须由调用方**显式** `include_writers=True` 才装配
    （`AgentH` 用它构造自己的"落库代理"，与它的自由工具箱分开）。
    默认把写工具塞进来，就等于承认这个约束只是写在文档里的愿望。
    """
    def _not_wired(**__: Any) -> Any:
        """未接线时**显式失败**（FC-08）：返回"没查"，绝不返回"没有发现"的空结果。"""
        return fail(
            "review 工具未接线（装配时未提供 store）⇒ **没查**，不是『没有发现』",
            kind="not_wired",
        )

    registry.register(
        ToolSpec(
            name="review.scan_document",
            summary="对一份稿件做全量机械审校（引用/证据等级/否定分类/依赖闭合），每条发现都带 evidence",
            params={
                "type": "object",
                "properties": {
                    "doc": {"type": "object"},
                    "dependencies": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["doc"],
                "additionalProperties": False,
            },
            handler=lambda doc, dependencies=_UNSPECIFIED: ok(
                scan_document(doc, dependencies=None if dependencies is _UNSPECIFIED else dependencies)
            ),
            side_effect="none",
            roles=_ROLES,
            returns="{'checked','doc_id','findings','error_count','warning_count','verdict','dep_check'}",
            tags=("review", "gate"),
        )
    )

    registry.register(
        ToolSpec(
            name="review.list_findings",
            summary="只读列举审校发现（可按稿件/状态/级别过滤），含每条发现的 evidence",
            params={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "status": {"type": "string", "enum": list(S.FINDING_STATUSES)},
                    "level": {"type": "string", "enum": list(S.FINDING_LEVELS)},
                },
                "additionalProperties": False,
            },
            handler=lambda doc_id=None, status=None, level=None: (
                _not_wired()
                if store is None
                else _guard_result(lambda: list_findings(store, doc_id=doc_id, status=status, level=level))
            ),
            side_effect="read",
            roles=_ROLES,
            returns="{'count','findings':[{'finding_id','doc_id','kind','level','target','message','evidence','status'}]}",
            tags=("review", "read"),
        )
    )

    if not include_writers:
        # 默认面到此为止：**全部 none/read**。写入口需要显式打开。
        return

    registry.register(
        ToolSpec(
            name="review.review_document",
            summary=(
                "审一份稿件：把机械发现落成 ReviewFinding（每条带 evidence），并更新文档状态；"
                "只写 review_findings 与 documents.status，不改 claims"
            ),
            params={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "round_no": {"type": "integer", "minimum": 1},
                    "dependencies": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["doc_id"],
                "additionalProperties": False,
            },
            handler=lambda **kw: (
                _not_wired()
                if store is None
                else _guard_result(lambda: review_document(store, actor=actor, **kw))
            ),
            side_effect="write_local",
            roles=_WRITER_ROLES,
            returns="{'doc_id','new_findings','duplicate_skipped','error_count','warning_count','verdict','status'}",
            tags=("review", "write"),
        )
    )

    registry.register(
        ToolSpec(
            name="review.verify_fixes",
            summary=(
                "复审：对上一轮每条 finding 重跑对应检查，判 fixed / 仍 open；"
                "到 max_review_rounds 仍红则置 unresolved_review 并**列出**未解决项"
            ),
            params={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "round_no": {"type": "integer", "minimum": 1},
                    "dependencies": {"type": "array", "items": {"type": "object"}},
                    "max_review_rounds": {"type": "integer", "minimum": 1},
                },
                "required": ["doc_id", "round_no"],
                "additionalProperties": False,
            },
            handler=lambda **kw: (
                _not_wired()
                if store is None
                else _guard_result(lambda: verify_fixes(store, actor=actor, **kw))
            ),
            side_effect="write_local",
            roles=_WRITER_ROLES,
            returns="{'doc_id','round','resolved','still_open','unresolved_findings','verdict'}",
            tags=("review", "write"),
        )
    )

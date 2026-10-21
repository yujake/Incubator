"""「待新增文献列表」的实现核心（业主 2026-10-20 口径）：按委托暂存 → 审 → 一键迁移 → 报告。

这一层与 `tools/search_tools.py` 的分工，照本仓的老规矩（`dedup.py` / `secretary.py`
都是这个形状）：

- 本模块是判据的真身：条数上限（`MAX_ADMIT_PER_CALL` / `MAX_ADMIT_PER_DELEGATION`）、
  重叠口径（`OVERLAP_HIGH_JACCARD` / `OVERLAP_KINDS`）、状态机
  （`schema.CANDIDATE_STATUSES`）、筛选理由的受控词表（`schema.CANDIDATE_REASON_CODES`）、
  报告的两块结构（`report_markdown` / `report_violations`）只有这一处实现；
- 工具层是模型的手：把本模块的结论翻成 `ToolResult`（`fail(kind=...)` 给模型看），
  不重新判一遍。两份判据必然漂，而漂的形态是"工具说拒了、实现却写进去了"。

## 列表的生命周期 = 一次查询委托（业主 2026-10-20 补充的第 1 条）

待新增列表不是全局常驻的：一行候选属于某一次委托（`request_id`，形如 `r-000001`，
就是 `search_requests` 里那一行）。于是：

- 新委托开始时，`stage_list` 的默认视图只看得到本委托的行（`current_request_id`）；
- 旧委托的行不参与本次筛选（查历史要显式给 `request_id`）；
- 迁移完一次委托就把它的列表清空（`cleared` / 终态 + `cleared_at`），于是"下一次委托
  看不到本委托的残留"—— 这一条由 `admit_all` 的结算与 `current_request_id` 的取值共同保证。

## 为什么"入库"不在本模块里写 literature 行

业主口径逐字：「入库走现有的 literature 登记路径（别绕开它）」。
现有路径有两条，而且它们本来就不同：

- 工具面：`tools/search_tools._h_register`（`search.register` 的 handler，走
  `store.tx` + `alloc_id("lit")` + 判重 + 收编文件）；
- 动作面：`agent_a.run_once` 的阶段 2（同一个事务里重做一次判重、回填请求行）。

所以本模块的 `admit` / `admit_all` 只做筛选与结算，把"该入库的那几条"交给调用方
注入的 `registrar`（就是上面那条现有路径），拿回 `lit_id` 之后再回填候选行。
"绕开登记路径"在结构上做不到：本模块里没有一处 `tx.upsert("literature", …)`。

## 三态纪律（与 `search_tools` 的模块 docstring 同源）

- `store is None` ⇒ 不是"没有重叠"，是判不了（`checked=False`）；
- 表读不出来 ⇒ 同上（`StoreError` 一路抛给调用方，由工具层折成 `table_unreadable`）；
- `overlap_score is None` ⇒ 没查过（不是 0.0 —— 0.0 是"查了，一点也不重叠"）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import dedup as D
from . import schema as S
from . import textutil as T
from .store import Store

__all__ = [
    "MAX_ADMIT_PER_CALL",
    "MAX_ADMIT_PER_DELEGATION",
    "OVERLAP_HIGH_JACCARD",
    "OVERLAP_KINDS",
    "REPORT_DIR",
    "LitStageError",
    "title_terms",
    "title_jaccard",
    "overlap_check",
    "current_request_id",
    "stage_entries",
    "list_candidates",
    "withdraw",
    "reject",
    "admission_plan",
    "apply_settlement",
    "decisions_from_plan",
    "admit",
    "admit_all",
    "report_markdown",
    "report_path",
    "write_report",
    "report_violations",
]

#: 一次 `lit.admit` 调用最多入库几篇（业主口径 ①）。
#:
#: 为什么是"每次调用"而不是"每次检索"：A 可以分批入库（先入 6 篇、再入 4 篇），
#: 而"一次检索至多 10 篇"那一条由 `MAX_ADMIT_PER_DELEGATION` 守 —— 两个上限管两件
#: 不同的事，合成一个会让"分两批把 20 篇都塞进去"变成合法。
MAX_ADMIT_PER_CALL: int = 10

#: 同一个委托（`request_id` = 一次检索委托）累计入库上限（业主口径 ①）。
#:
#: 它与 `MAX_ADMIT_PER_CALL` 都必需：只有每次调用的上限 ⇒ 分几批就能突破；
#: 只有委托上限 ⇒ 一次调用 100 篇也照样过。两条一起才等于"一次文献检索至多入库 10 篇"。
MAX_ADMIT_PER_DELEGATION: int = 10

#: 标题词集 Jaccard 的"重叠度高"阈值（业主口径 ④，自定但必须写在这里）。
#:
#: 0.60 的依据（不是拍脑袋）：同一篇文献的两种写法（预印本 vs 正式版、带/不带副标题）
#: 实测 Jaccard 落在 0.7–0.95；而同一领域的不同论文（共享 "abelian group" 这类
#: 高频词组）通常落在 0.1–0.35。0.60 落在两簇中间，且宁可误报——误报的代价只是
#: "多要一句 `new_content`"（人写一句话即可），漏报的代价是"同一篇进库两次"
#: （两条 lit_id、两套引文，下游无法合并）。
OVERLAP_HIGH_JACCARD: float = 0.60

#: `lit_candidates.overlap_kind` 的受控取值。
#:
#:   doi_exact     —— DOI 完全相同 ⇒ 视为重复（不是"高度重叠"：它就是同一篇，
#:                    没有任何"新内容"可陈述，所以给不给 `new_content` 都不放行）
#:   title_jaccard —— 按标题词集 Jaccard 算出来的重叠度（0..1，见 `title_jaccard`）
OVERLAP_KINDS: tuple[str, ...] = ("doi_exact", "title_jaccard")

#: 委托报告的落点（相对工作区根）：`reports/lit-<request_id>.md`。
#:
#: 为什么是文件而不是只放在工具返回值里（业主 2026-10-20 第 3 条：这是交付物）：
#: 下一次委托的 D/H 要用它 —— 而"D/H 读一个工具调用的返回值"这件事在结构上做不到
#: （它们是另外的角色、另外的循环）。写在 `reports/` 下之后，任何带 `fs.read` 的角色
#: 都读得到，它也就成了台账之外唯一一份"这次检索进了哪几篇、挡了哪几篇与为什么"的证据。
REPORT_DIR: str = "reports"


class LitStageError(RuntimeError):
    """待新增列表上的一次操作不成立（拒绝整笔，附机器可读的 `kind`）。

    与 `ToolError` 同族：工具层只捕这一个类型，翻成 `fail(kind=...)` 给模型看。
    `detail` 里放读数（槽位、条数、上限、重叠分数），供拒信逐条说清。
    """

    def __init__(self, message: str, *, kind: str, detail: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.kind = kind
        self.detail = dict(detail or {})


# --------------------------------------------------------------------------- 重叠口径


def title_terms(title: str | None) -> set[str]:
    """标题的词集（小写、只留字母数字、长度 ≥ 2 的词）。

    为什么不用 `textutil.similarity`（那是 difflib 的字符级比率）：字符级比率对
    "同一批词换个次序"几乎不敏感，而"同一篇文献换个次序"恰恰是最常见的重复形态
    （正式版把副标题挪到前面）。词集 Jaccard 对次序不敏感、对增删词敏感，
    正是这一档需要的口径。这不是判重主通道 —— 判重的唯一口径仍是
    `dedup.literature_keys` / `find_existing_literature`（DOI → 标题+年 → 仅标题），
    本函数只服务"重叠度高到要不要问一句 `new_content`"。
    """
    norm = T.normalize(title or "").lower()
    out: set[str] = set()
    for token in norm.replace("-", " ").replace("_", " ").split():
        token = "".join(ch for ch in token if ch.isalnum())
        if len(token) >= 2:
            out.add(token)
    return out


def title_jaccard(a: str | None, b: str | None) -> float:
    """两个标题的词集 Jaccard（`|A∩B| / |A∪B|`；任一为空 ⇒ 0.0）。

    0.0 与"没查"不是一回事：这里的 0.0 是"查了，两个词集没有交集"
    （或者有一边没有词）—— 调用方拿到的 `checked` 才回答"查没查"。
    """
    ta, tb = title_terms(a), title_terms(b)
    if not ta or not tb:
        return 0.0
    return round(len(ta & tb) / len(ta | tb), 4)


def overlap_check(store: Store | None, title: str, doi: str | None = None) -> dict:
    """与本地库（`literature` 表）比对：DOI 完全相同 ⇒ 重复；否则按标题词集 Jaccard。

    返回的字典逐键：

    - `checked`：这一趟到底查没查（`store is None` ⇒ `False`，不是"没有重叠"）；
    - `duplicate`：`True` 只在 DOI 与本地某一行完全相同时（这一档没有 `new_content`
      可救 —— 同一篇文献说不出"新内容"）；
    - `overlap_score` / `overlap_kind` / `overlap_with`：与哪一行、重叠多少；
    - `requires_new_content`：重叠度 ≥ `OVERLAP_HIGH_JACCARD` ⇒ `True`
      （调用方必须给 `new_content`，否则拒收）；
    - `reason`：一句人话，直接可以进拒信。

    表读不出来时不吞异常：`store.rows` 的 `StoreError` 一路抛给调用方
    （工具层折成 `table_unreadable`）。"表坏了"折成"没有重叠"会让重复文献静默进库。
    """
    if store is None:
        return {
            "checked": False,
            "duplicate": False,
            "overlap_score": None,
            "overlap_kind": "",
            "overlap_with": None,
            "requires_new_content": False,
            "reason": "未配置 store：读不到本地库 ⇒ 重叠**没查**（不是「没有重叠」）",
        }
    want_doi = D.normalize_doi(doi)
    best_score = 0.0
    best_lit: str | None = None
    best_title = ""
    for row in store.rows("literature"):
        row_doi = D.normalize_doi(row.get("doi"))
        if want_doi and row_doi and want_doi == row_doi:
            return {
                "checked": True,
                "duplicate": True,
                "overlap_score": 1.0,
                "overlap_kind": "doi_exact",
                "overlap_with": str(row.get("lit_id") or ""),
                "requires_new_content": True,
                "reason": (
                    f"DOI 与本地 literature 的 lit_id={row.get('lit_id')} 完全相同"
                    f"（{want_doi}）⇒ 视为重复，不入库"
                ),
            }
        score = title_jaccard(title, row.get("title"))
        if score > best_score:
            best_score, best_lit = score, str(row.get("lit_id") or "")
            best_title = str(row.get("title") or "")
    requires = best_score >= OVERLAP_HIGH_JACCARD
    if requires:
        reason = (
            f"与本地 lit_id={best_lit}（「{T.clip(best_title, 60)}」）的标题词集 Jaccard="
            f"{best_score} ≥ {OVERLAP_HIGH_JACCARD} ⇒ 重叠度高："
            "必须在 `new_content` 里说清本次检索要的新内容，否则拒收"
        )
    else:
        reason = (f"与本地库的最高标题词集 Jaccard={best_score}"
                  f"（阈值 {OVERLAP_HIGH_JACCARD}）")
    return {
        "checked": True,
        "duplicate": False,
        "overlap_score": best_score,
        "overlap_kind": "title_jaccard",
        "overlap_with": best_lit,
        "requires_new_content": requires,
        "reason": reason,
    }


# --------------------------------------------------------------------------- 委托 / 暂存


def _rows(store: Store) -> list[dict]:
    return store.rows("lit_candidates")


def _code_label(code: str) -> str:
    """受控理由码的短标签（写进行上的 `withdrawn_reason` / `reject_reason` / `clear_reason`）。

    行上的那一栏必须非空（`schema.LitCandidate.validate` 守），而调用方可能只给
    理由码、不给散文 —— 那就用登记表里的标签顶上，而不是留空或编一句。
    """
    return S.CANDIDATE_REASON_LABELS.get(str(code), str(code))


def _check_code(code: str) -> str:
    c = str(code or "").strip()
    if c not in S.CANDIDATE_REASON_CODES:
        raise LitStageError(
            f"理由码必须是登记表里的受控取值 {S.CANDIDATE_REASON_CODES} 之一，收到 {code!r}。"
            "自由发挥的理由没法进报告（报告只认受控取值）",
            kind="bad_reason_code",
            detail={"codes": list(S.CANDIDATE_REASON_CODES)},
        )
    return c


def current_request_id(store: Store | None) -> str:
    """当前委托 = 槽位号最大那一行所属的 `request_id`（没有行 ⇒ 空串）。

    为什么这样定"当前"：槽位号只增不复用（`store.alloc_id("candidate")`），
    于是"最后一个开始暂存的委托"就是号最大的那一行的委托 —— 不需要另一处
    "当前委托是谁"的状态（那种状态必然与盘上的行漂，而漂了不会报错）。
    """
    if store is None:
        return ""
    rows = _rows(store)
    if not rows:
        return ""
    newest = max(rows, key=lambda r: str(r.get("slot") or ""))
    return str(newest.get("request_id") or "")


def _resolve_request(store: Store | None, request_id: str | None) -> str:
    rid = str(request_id or "").strip() or current_request_id(store)
    if not rid:
        raise LitStageError(
            "说不清这是哪一次委托（待新增列表里还没有任何行，调用方也没给 request_id）⇒ "
            "没有委托就没有「本次」筛选，不许拿一个空集冒充",
            kind="no_delegation",
        )
    return rid


def stage_entries(
    store: Store | None,
    entries: Iterable[Mapping[str, Any]],
    *,
    request_id: str,
    batch: int | None = None,
    actor: str = "agent-A",
    note: str = "lit.stage_add",
) -> dict:
    """把候选追加进本次委托的待新增列表（一次可追加任意条，超过 10 条也允许）。

    为什么暂存不设上限：上限管的是入库（业主口径 ①），不是"广搜能拿回多少"。
    把上限提前到暂存这一档，会让"广搜 30 条、精选 8 条入库"这条正路直接走不通 ——
    而业主明确要求"广搜可以超过 10 篇，但正式入库最多 10"。

    槽位号由 `store.alloc_id("candidate")` 发：只增不复用（撤掉的号不会被再发一次），
    所以第 2 批的序号接着第 1 批往下排（12 条 + 3 条 = 1..15，撤掉的 3、7 空着）。

    `request_id` 必须给（业主 2026-10-20 第 1 条：列表按委托重置）——
    新委托换一个 `request_id` 就是"从空列表开始"，不需要（也不许）清空旧行。
    """
    if store is None:
        raise LitStageError(
            "未配置 store：没有待新增列表可写（不是「这批候选都重复」）",
            kind="no_store",
        )
    rid = str(request_id or "").strip()
    if not rid:
        raise LitStageError(
            "stage_add 必须给 request_id（这一批候选属于哪一次查询委托）："
            "列表按委托重置，没有委托号的候选会与下一次委托串在一起",
            kind="no_delegation",
        )
    try:
        S.require_process_id(rid, "request")
    except ValueError as exc:
        raise LitStageError(f"request_id 形态不对：{exc}", kind="bad_delegation",
                            detail={"request_id": rid}) from exc
    items = [dict(e) for e in entries]
    if not items:
        raise LitStageError("entries 是空的：一次 stage_add 至少要追加 1 条候选",
                            kind="empty_batch")
    with store.tx("lit_candidates", "counters", actor=actor, note=note) as tx:
        rows = tx.rows("lit_candidates")
        same = [r for r in rows if str(r.get("request_id")) == rid]
        the_batch = int(batch) if batch is not None else (
            max((int(r.get("batch") or 0) for r in same), default=0) + 1)
        if the_batch < 1:
            raise LitStageError(f"batch 必须是 >= 1 的整数，收到 {batch!r}", kind="bad_batch")
        staged: list[dict] = []
        for raw in items:
            title = str(raw.get("title") or "").strip()
            if not title:
                raise LitStageError(
                    "有一条候选没有标题：空标题的槽位将来查不出「撤掉的是哪一篇」",
                    kind="bad_entry",
                    detail={"entry": {k: raw.get(k) for k in ("doi", "provider")}},
                )
            slot = tx.alloc_id("candidate")
            row = S.LitCandidate(
                slot=slot,
                request_id=rid,
                batch=the_batch,
                status="pending",
                title=title,
                doi=(str(raw.get("doi")).strip() if raw.get("doi") else None),
                provider=str(raw.get("provider") or ""),
                year=raw.get("year"),
                type_code=str(raw.get("type_code") or raw.get("type") or "J"),
                summary=T.clip(str(raw.get("summary") or ""), 1200),
                url=str(raw.get("url") or raw.get("pdf_url") or ""),
                # 业主 2026-10-20 第 3 条：报告里每篇已入库的都要一句"为什么与本次检索相关"。
                # 它在这里就能给（审的时候顺手写），不必等到迁移那一刻。
                relevance=T.clip(str(raw.get("relevance") or ""), 400),
                added_at=S.now_iso(),
            )
            row.validate()
            tx.upsert("lit_candidates", row.to_dict(), note=note)
            staged.append({"slot": slot, "batch": the_batch, "title": title})
    return {"request_id": rid, "batch": the_batch, "count": len(staged), "staged": staged}


def _scoped_rows(rows: Sequence[Mapping[str, Any]], rid: str) -> list[dict]:
    """把行按委托过滤（"默认视图只看当前委托"的唯一实现）。

    三态，与 `request_id` 的三种取值一一对应：

    - `rid == "*"` ⇒ 不过滤（审计用：查全部委托）；
    - `rid` 非空 ⇒ 只留这一次委托的行；
    - `rid` 为空 ⇒ 一行都不给（不是"全表"）。"说不清这是哪一次委托"与"所有委托"
      是两件事，后者会把旧委托的行混进本次筛选 —— 而那正是业主第 1 条要挡的。

    单独成函数是为了让"按委托重置"这条判据有一个可被负控替代的落点
    （`tests/test_search_tools_stage_admit.py` 把它换成恒等函数 ⇒ 判据必须变红）。
    """
    if str(rid) == "*":
        return [dict(r) for r in rows]
    if not str(rid):
        return []
    return [dict(r) for r in rows if str(r.get("request_id") or "") == str(rid)]


def list_candidates(
    store: Store | None,
    *,
    request_id: str | None = None,
    batch: int | None = None,
    status: str | None = None,
) -> dict:
    """按委托 / batch / status 查待新增列表。空槽位照样出现在列表里。

    "空槽位"指 `status="withdrawn"` 的那些行：它们没有被物理删除（序号不复用），
    所以题名、`withdrawn_reason`、`added_at` 全都还在 —— 于是"第 3 号被撤了哪一篇、
    为什么"是查得出来的。这正是业主口径 ③ 的落点：撤掉 ≠ 删掉。

    默认视图只按当前委托过滤（业主 2026-10-20 第 1 条）；要看旧委托请显式给
    `request_id`（`request_id="*"` 表示全查，用于审计"历史有没有残留"）。
    """
    if store is None:
        raise LitStageError("未配置 store：读不到待新增列表（不是「列表是空的」）",
                            kind="no_store")
    if status is not None and status not in S.CANDIDATE_STATUSES:
        raise LitStageError(
            f"status 必须是 {S.CANDIDATE_STATUSES} 之一或 None，收到 {status!r}",
            kind="bad_status",
        )
    all_rows = _rows(store)
    rid = str(request_id or "").strip()
    if not rid:
        rid = current_request_id(store)
    scoped = _scoped_rows(all_rows, rid)
    if batch is not None:
        scoped = [r for r in scoped if int(r.get("batch") or 0) == int(batch)]
    rows = sorted(([r for r in scoped if str(r.get("status") or "") == status]
                   if status is not None else scoped), key=lambda r: str(r.get("slot") or ""))
    # 计数按委托过滤后、状态过滤前那一份算：调用方问"这一批还有几篇 pending"时
    # 需要同时看到全部态，否则 status=admitted 那一次查询会把"总数 12"读成"总数 9"。
    counts = {s: 0 for s in S.CANDIDATE_STATUSES}
    for r in scoped:
        s = str(r.get("status") or "")
        if s in counts:
            counts[s] += 1
    slots = [str(r.get("slot") or "") for r in rows]
    gaps: list[str] = []
    if slots:
        have = {int(s) for s in slots}
        gaps = [S.format_id(n) for n in range(min(have), max(have) + 1) if n not in have]
    return {
        "request_id": rid,
        "current_request_id": current_request_id(store),
        "batch": batch,
        "status": status,
        "count": len(rows),
        "counts": counts,
        "gaps": gaps,
        "rows": rows,
        "total_all_delegations": len(all_rows),
        "note": (
            "默认只返回**当前委托**的行（`request_id` = 最近一次暂存的那次委托）；"
            "查历史请显式给 request_id（`*` = 全部）。`withdrawn` 的行是空槽位："
            "序号不复用、题名与理由都留着；`rejected` 是审内容后拒收；"
            "`admitted` 已回填 lit_id；`cleared` 是迁移结算时被清空的残留（带 cleared_at）。"
        ),
    }


def _one(store: Store, slot: str) -> dict:
    for row in _rows(store):
        if str(row.get("slot") or "") == str(slot):
            return row
    raise LitStageError(
        f"待新增列表里没有槽位 {slot!r}（序号不复用，撤掉的号也不会再出现）",
        kind="unknown_slot",
        detail={"slot": slot},
    )


def _terminal(store: Store, slot: str, *, status: str, code: str, note: str,
              slot_field: str, actor: str, tx_note: str) -> dict:
    """把某一槽写成终态（withdrawn / rejected）：受控理由码 + 一行散文（可为空 ⇒ 用标签）。"""
    with store.tx("lit_candidates", actor=actor, note=tx_note) as tx:
        row = next((r for r in tx.rows("lit_candidates") if str(r.get("slot")) == str(slot)), None)
        if row is None:
            raise LitStageError(f"待新增列表里没有槽位 {slot!r}", kind="unknown_slot",
                                detail={"slot": slot})
        if str(row.get("status")) != "pending":
            raise LitStageError(
                f"槽位 {slot!r} 现在是 status={row.get('status')!r}，只有 pending 能改成 "
                f"{status}",
                kind="not_pending", detail={"slot": slot, "status": row.get("status")},
            )
        row = dict(row)
        row["status"] = status
        row["reason_code"] = code
        row[slot_field] = str(note or "").strip() or _code_label(code)
        S.LitCandidate(**{k: row[k] for k in row
                          if k in S.LitCandidate.__dataclass_fields__}).validate()
        tx.upsert("lit_candidates", row, note=tx_note)
    return {"slot": str(slot), "status": status, "reason_code": code,
            "reason": row[slot_field], "title": row.get("title"),
            "request_id": row.get("request_id"), "batch": row.get("batch")}


def withdraw(store: Store | None, slot: str, reason_code: str, note: str = "",
             *, actor: str = "agent-A") -> dict:
    """撤掉某一槽：写 `withdrawn_reason` + `reason_code`、状态置 `withdrawn`，不物理删除。

    撤掉之后可以再 `stage_add` 补位 —— 但新条进的是新序号（旧号不复用），
    所以列表里会同时看到"第 3 号（撤掉，理由…）"与"第 13 号（补进来的那条）"。

    `reason_code` 必须是 `schema.CANDIDATE_REASON_CODES` 里的受控取值
    （业主 2026-10-20 第 3 条：报告里的理由只认受控取值，不许自由发挥）。
    """
    if store is None:
        raise LitStageError("未配置 store：撤不掉（不是「已经撤过了」）", kind="no_store")
    code = _check_code(reason_code)
    return _terminal(store, slot, status="withdrawn", code=code, note=note,
                     slot_field="withdrawn_reason", actor=actor, tx_note="lit.stage_withdraw")


def reject(store: Store | None, slot: str, reason_code: str, note: str = "",
           *, actor: str = "agent-A") -> dict:
    """审内容后拒收：写 `reject_reason` + `reason_code`、状态置 `rejected`，不物理删除。"""
    if store is None:
        raise LitStageError("未配置 store：拒收不了（不是「已经拒过了」）", kind="no_store")
    code = _check_code(reason_code)
    return _terminal(store, slot, status="rejected", code=code, note=note,
                     slot_field="reject_reason", actor=actor, tx_note="lit.stage_reject")


# --------------------------------------------------------------------------- 入库


def _cap_of(cap: int | None) -> int:
    n = MAX_ADMIT_PER_CALL if cap is None else int(cap)
    if n < 1:
        raise LitStageError(f"入库上限必须是 >= 1 的整数，收到 {cap!r}", kind="bad_limit")
    return n


def _refusal(slot: str, title: Any, why: str, code: str,
             overlap: Mapping[str, Any] | None = None) -> dict:
    """一条"这一槽没入库"的记录（键集合固定：`slot` / `title` / `why` / `code` / `overlap`）。

    为什么键集合必须固定：工具层把它声明成数组元素，而"同一个数组里有的元素带
    `overlap`、有的不带"会让下游的键级判据失去对象
    （`tests/test_tools_returns_declaration.py` 的
    `test_every_element_of_an_array_carries_the_same_top_level_keys` 正是守这一条的）。
    没有重叠读数时给 `None`（"没有这一格"），而不是把键省掉。
    """
    return {"slot": str(slot), "title": title, "why": why, "code": code,
            "overlap": dict(overlap) if overlap else None}


def admission_plan(
    store: Store | None,
    *,
    request_id: str | None = None,
    slots: Sequence[str] | None = None,
    batch: int | None = None,
    new_content: str = "",
    cap: int | None = None,
    on_over_cap: str = "refuse_all",
    duplicate_branch_ok: bool = False,
) -> dict:
    """入库前的那一笔判断：条数上限 + 重叠检查 + 逐条该不该进（一行都不写）。

    ## 两档超限处置（`on_over_cap`）

    - `"refuse_all"`（`lit.admit` 用）：本次要入的条数超过上限 ⇒ 整笔拒绝，
      一条都不入。为什么整笔：如果前 10 条进了、第 11 条被挡，调用方会读成
      "第 11 条被审掉了"，而真相是"这一次调用根本不成立"。
    - `"truncate"`（`lit.admit_all` / A 的自动链路用）：按槽位号顺序把前 N 条
      通过检查的收进来，其余进 `cleared`（`reason_code="over_cap"`）——
      一键迁移的语义是"把通过的都迁走"，不是"有一条超限就全不动"。

    ## 逐条拒收（业主口径 ②④）

    - `status != "pending"`（已撤 / 已拒 / 已入库 / 已清空）⇒ 拒（`already_terminal`）；
    - DOI 与本地库某一行完全相同 ⇒ 视为重复，拒（`duplicate_doi`）。
      `duplicate_branch_ok=True` 时不拒、而是标 `existing_duplicate`：那是
      A 的自动链路要的语义 —— 现有登记路径的判重分支会命中它、只追加
      `source_request_ids` 而不新建行（"同一篇文献两个 lit_id"仍然不可能）。
    - 标题词集 Jaccard ≥ 0.60 且没有 `new_content` ⇒ 拒
      （`overlap_without_new_content`；行上的 `new_content` 优先，调用级兜底）；
    - 行上显式 `overlap_ok=False` ⇒ 拒（`overlap_ok_false`）。

    `new_content` 是调用级别的兜底：候选行上已经有 `new_content` 时以行上的为准
    （那一句是对着这一篇写的），调用级的那句只填空。
    """
    if store is None:
        raise LitStageError("未配置 store：入不了库（不是「都重复了」）", kind="no_store")
    if on_over_cap not in ("refuse_all", "truncate"):
        raise LitStageError(f"on_over_cap 只能是 refuse_all / truncate，收到 {on_over_cap!r}",
                            kind="bad_mode")
    limit = _cap_of(cap)
    rid = _resolve_request(store, request_id)
    rows = _rows(store)
    scoped = [r for r in rows if str(r.get("request_id") or "") == rid]
    if slots is None:
        if batch is None:
            raise LitStageError(
                "admit 要么给 slots（要入库的那几个槽位），要么给 batch（这一批全部待审的）",
                kind="no_target",
            )
        wanted = [str(r.get("slot")) for r in sorted(scoped, key=lambda r: str(r.get("slot") or ""))
                  if int(r.get("batch") or 0) == int(batch) and str(r.get("status")) == "pending"]
    else:
        wanted = []
        for raw in slots:
            s = str(raw or "").strip()
            if s and s not in wanted:
                wanted.append(s)
        if not wanted:
            raise LitStageError("slots 是空的：没有要入库的东西", kind="no_target")
    by_slot = {str(r.get("slot") or ""): r for r in scoped}
    unknown = [s for s in wanted if s not in by_slot]
    if unknown:
        outside = [s for s in unknown if s in {str(r.get("slot")) for r in rows}]
        raise LitStageError(
            f"这些槽位不在**本次委托**（{rid}）的待新增列表里：{unknown}"
            + (f"；其中 {outside} 属于别的委托（列表按委托重置，旧委托的行不参与本次筛选）"
               if outside else "（序号不复用，请用 lit.stage_list 查一遍）"),
            kind="unknown_slot", detail={"slots": unknown, "request_id": rid},
        )
    batches = {int(by_slot[s].get("batch") or 0) for s in wanted}
    already = sum(1 for r in scoped if str(r.get("status")) == "admitted")

    items: list[dict] = []
    refused: list[dict] = []
    over_cap: list[dict] = []
    for slot in wanted:
        row = by_slot[slot]
        status = str(row.get("status") or "")
        if status != "pending":
            refused.append(_refusal(slot, row.get("title"), (
                f"status={status}，只有 pending（待审）能入库"
                + ("（撤掉的槽位要补位请再 stage_add，新条进新序号）" if status == "withdrawn" else "")
            ), "already_terminal"))
            continue
        ov = overlap_check(store, str(row.get("title") or ""), row.get("doi"))
        nc = str(row.get("new_content") or "").strip() or str(new_content or "").strip()
        if ov.get("duplicate"):
            if duplicate_branch_ok:
                items.append({"slot": slot, "row": row, "overlap": ov, "new_content": nc,
                              "title": row.get("title"), "existing_duplicate": True})
            else:
                refused.append(_refusal(slot, row.get("title"), ov["reason"], "duplicate_doi", ov))
            continue
        if ov.get("requires_new_content") and not nc:
            refused.append(_refusal(slot, row.get("title"), ov["reason"],
                                    "overlap_without_new_content", ov))
            continue
        if row.get("overlap_ok") is False:
            refused.append(_refusal(slot, row.get("title"),
                                    "该槽位显式标了 overlap_ok=False（调用方自己说不可收）",
                                    "overlap_ok_false", ov))
            continue
        items.append({"slot": slot, "row": row, "overlap": ov, "new_content": nc,
                      "title": row.get("title"), "existing_duplicate": False})

    call_size = len(items)
    base = {
        "kind": "",
        "whole_call_refused": False,
        "reason": "",
        "request_id": rid,
        "batch": sorted(batches)[0] if len(batches) == 1 else None,
        "batches": sorted(batches),
        "call_limit": limit,
        "delegation_admitted": already,
        "delegation_limit": MAX_ADMIT_PER_DELEGATION,
        "refused": refused,
        "cleared": over_cap,
    }
    if on_over_cap == "refuse_all":
        if call_size > limit:
            return {**base, "ok": False, "kind": "over_cap_call", "whole_call_refused": True,
                    "reason": (
                        f"本次调用要入库 {call_size} 条，超过单次上限 {limit} 条 ⇒ **整笔拒绝**"
                        f"（一条都没入：分批突破上限不算合法）。请精选到 ≤{limit} 条，"
                        f"或分成多次调用（同一委托累计入库仍受 {MAX_ADMIT_PER_DELEGATION} 条限制）"),
                    "call_size": call_size, "admitted": []}
        if already + call_size > MAX_ADMIT_PER_DELEGATION:
            return {**base, "ok": False, "kind": "over_cap_delegation", "whole_call_refused": True,
                    "reason": (
                        f"这次委托（{rid}）已经入库 {already} 条，这次还要入 {call_size} 条 ⇒ "
                        f"累计 {already + call_size} 条，超过该委托上限 "
                        f"{MAX_ADMIT_PER_DELEGATION} 条 ⇒ **整笔拒绝**（一条都没入）。"
                        "一次文献检索正式入库至多 10 篇，必须精选"),
                    "call_size": call_size, "admitted": []}
        return {**base, "ok": True, "call_size": call_size, "admitted": items}

    # ---- truncate：按槽位顺序放到配额为止，其余进 cleared(over_cap)
    quota = max(0, min(limit, MAX_ADMIT_PER_DELEGATION - already))
    keep, drop = items[:quota], items[quota:]
    for item in drop:
        over_cap.append(_refusal(item["slot"], item["title"], (
            f"本次委托（{rid}）的入库配额已满（上限 {MAX_ADMIT_PER_DELEGATION} 条，"
            f"已入 {already} 条 / 本次收 {quota} 条）⇒ 这一条不入库"
        ), "over_cap", item.get("overlap")))
    return {**base, "ok": True, "call_size": len(keep), "admitted": keep,
            "cleared": over_cap, "quota": quota}


def apply_settlement(tx: Any, decisions: Iterable[Mapping[str, Any]]) -> list[dict]:
    """把一批终态决定写回候选行（`tx` 由调用方给 —— 让它能与登记同处一个事务）。

    `decisions` 的每一项：`{slot, status, lit_id?, reason_code?, note?, overlap_*}`
    （`status` 取 `admitted` / `rejected` / `cleared` / `withdrawn`）。

    为什么把它做成"拿 tx 进来"的函数：A 的自动链路（`agent_a.run_once`）里，
    "写 literature 行"与"回填候选行"必须在同一个事务里 —— 否则崩在中间会留下
    "literature 有了、候选还 pending"的一对，下一次迁移会把它当新的再登记一次。
    工具面那一路（`lit.admit` / `lit.admit_all`）的登记路径自带事务，于是它自己开
    一个只写 `lit_candidates` 的事务调这里（同样是一个原子步）。
    """
    rows = {str(r.get("slot") or ""): r for r in tx.rows("lit_candidates")}
    written: list[dict] = []
    for d in decisions:
        slot = str(d.get("slot") or "")
        row = dict(rows.get(slot) or {})
        if not row:
            continue
        status = str(d.get("status") or "")
        if status not in S.CANDIDATE_STATUSES:
            continue
        row["status"] = status
        code = str(d.get("reason_code") or "")
        note = str(d.get("note") or "").strip()
        if code:
            row["reason_code"] = code
        if status == "admitted":
            row["lit_id"] = str(d.get("lit_id") or "")
            row["admitted_at"] = S.now_iso()
            for k in ("overlap_score", "overlap_kind", "overlap_with"):
                if d.get(k) not in (None, ""):
                    row[k] = d[k]
            if str(d.get("new_content") or "").strip():
                row["new_content"] = str(d["new_content"]).strip()
        elif status == "withdrawn":
            row["withdrawn_reason"] = note or _code_label(code)
        elif status == "rejected":
            row["reject_reason"] = note or _code_label(code)
        elif status == "cleared":
            row["cleared_at"] = S.now_iso()
            row["clear_reason"] = note or _code_label(code)
        S.LitCandidate(**{k: row[k] for k in row
                          if k in S.LitCandidate.__dataclass_fields__}).validate()
        tx.upsert("lit_candidates", row, note=f"lit.settle:{status}")
        rows[slot] = row
        written.append(row)
    return written


def _decisions_from(plan: Mapping[str, Any], lit_ids: Mapping[str, str],
                    failures: Mapping[str, str]) -> list[dict]:
    """把 `admission_plan` 的结论 + 登记结果翻成 `apply_settlement` 要的决定。"""
    out: list[dict] = []
    for item in plan.get("admitted") or []:
        slot = str(item["slot"])
        lit_id = str(lit_ids.get(slot) or "")
        if lit_id:
            ov = item.get("overlap") or {}
            out.append({"slot": slot, "status": "admitted", "lit_id": lit_id,
                        "overlap_score": ov.get("overlap_score"),
                        "overlap_kind": ov.get("overlap_kind"),
                        "overlap_with": ov.get("overlap_with"),
                        "new_content": item.get("new_content")})
        else:
            out.append({"slot": slot, "status": "rejected", "reason_code": "registration_failed",
                        "note": failures.get(slot) or "登记路径没有给出 lit_id"})
    for r in plan.get("refused") or []:
        if str(r.get("code")) == "already_terminal":
            continue
        out.append({"slot": str(r["slot"]), "status": "rejected",
                    "reason_code": str(r.get("code") or ""), "note": str(r.get("why") or "")})
    for c in plan.get("cleared") or []:
        out.append({"slot": str(c["slot"]), "status": "cleared",
                    "reason_code": str(c.get("code") or "over_cap"),
                    "note": str(c.get("why") or "")})
    return out


def decisions_from_plan(plan: Mapping[str, Any], lit_ids: Mapping[str, str],
                        failures: Mapping[str, str] | None = None) -> list[dict]:
    """公开入口：`admission_plan` 的结论 + 登记结果 ⇒ `apply_settlement` 要的决定。

    A 的自动链路（`agent_a.run_once`）要用它：那条路自己在一个事务里写 literature
    （它还要搬 staging 里下载好的文件），所以它需要"决定"而不是"入库函数"。
    判据（哪些拒、哪些清空、理由码怎么落）仍然只在本模块这一处。
    """
    return _decisions_from(plan, lit_ids, failures or {})


def _register(plan: Mapping[str, Any], registrar: Callable[[Mapping[str, Any]], dict]
              ) -> tuple[dict[str, str], dict[str, str], dict[str, dict]]:
    """逐条走调用方注入的现有登记路径，返回 `(lit_ids, failures, got)`。"""
    lit_ids: dict[str, str] = {}
    failures: dict[str, str] = {}
    got_all: dict[str, dict] = {}
    for item in plan.get("admitted") or []:
        slot = str(item["slot"])
        try:
            got = dict(registrar(item["row"]) or {})
        except Exception as exc:  # noqa: BLE001 - 登记路径的失败要如实记，不许折成成功
            failures[slot] = f"登记路径失败：{type(exc).__name__}: {exc}"
            continue
        got_all[slot] = got
        lit_id = str(got.get("lit_id") or "")
        if lit_id:
            lit_ids[slot] = lit_id
        else:
            failures[slot] = (f"登记路径没给出 lit_id"
                              f"（{got.get('reason') or got.get('error') or '无理由'}）")
    return lit_ids, failures, got_all


def admit(
    store: Store | None,
    *,
    registrar: Callable[[Mapping[str, Any]], dict],
    request_id: str | None = None,
    slots: Sequence[str] | None = None,
    batch: int | None = None,
    new_content: str = "",
    cap: int | None = None,
    actor: str = "agent-A",
    write_report_file: bool = True,
) -> dict:
    """正式入库（逐条）：过 `admission_plan` ⇒ 走现有登记路径 ⇒ 回填候选行。

    超限即整笔拒绝（`on_over_cap="refuse_all"`，见 `admission_plan`）。
    逐条被挡的槽位不在这里终态（保持 `pending`，理由在 `refused[]` 里）：
    `lit.admit` 是"补一句 `new_content` 再试"的入口；终态留给 `admit_all` 的结算
    或调用方的 `lit.stage_reject`。登记失败同样保持 `pending`（它还可以重试）。
    本函数不清空列表，但它会刷新委托报告 —— 业主第 3 条把报告说成交付物：
    只要这个委托动过库，报告就得在盘上。
    """
    plan = admission_plan(store, request_id=request_id, slots=slots, batch=batch,
                          new_content=new_content, cap=cap, on_over_cap="refuse_all")
    if not plan.get("ok"):
        return {**plan, "admitted": [], "registered": 0, "report": None, "report_path": None}
    lit_ids, failures, got_all = _register(plan, registrar)
    # 逐条档不结算"没进"的那几条：`lit.admit` 是"再试一次"的入口 —— 被
    # `overlap_without_new_content` / `duplicate_doi` 挡下的槽位保持 `pending`，
    # 于是调用方可以补一句 `new_content` 再入，或用 `lit.stage_reject` 显式给它终态
    # （理由码一样进报告）。"结算"是一次委托的收尾动作，属于 `admit_all` ——
    # 两档的差别在这里，不在判据上（判据只有 `admission_plan` 一处）。
    decisions = [d for d in _decisions_from(plan, lit_ids, failures)
                 if d["status"] == "admitted"]
    if decisions:
        with store.tx("lit_candidates", actor=actor, note="lit.admit") as tx:
            apply_settlement(tx, decisions)
    done = []
    for item in plan.get("admitted") or []:
        slot = str(item["slot"])
        if slot in lit_ids:
            ov = item.get("overlap") or {}
            done.append({"slot": slot, "title": item["title"], "lit_id": lit_ids[slot],
                         "created": bool(got_all.get(slot, {}).get("created")),
                         "overlap_score": ov.get("overlap_score"),
                         "overlap_kind": ov.get("overlap_kind"),
                         "overlap_with": ov.get("overlap_with"),
                         "new_content": item.get("new_content")})
    refused = [r for r in plan.get("refused") or []]
    for slot, why in failures.items():
        row = next((i["row"] for i in plan["admitted"] if str(i["slot"]) == slot), {})
        refused.append(_refusal(slot, row.get("title"), why, "registration_failed"))
    rep = write_report(store, plan["request_id"]) if write_report_file else None
    return {
        "ok": True,
        "kind": "",
        "whole_call_refused": False,
        "reason": "",
        "request_id": plan["request_id"],
        "batch": plan["batch"],
        "call_size": plan["call_size"],
        "call_limit": plan["call_limit"],
        "delegation_admitted": plan["delegation_admitted"] + len(done),
        "delegation_limit": plan["delegation_limit"],
        "admitted": done,
        "refused": refused,
        "cleared": [],
        "registered": len(done),
        "report": rep,
        "report_path": (rep or {}).get("path"),
    }


def admit_all(
    store: Store | None,
    *,
    registrar: Callable[[Mapping[str, Any]], dict],
    request_id: str | None = None,
    new_content: str = "",
    cap: int | None = None,
    actor: str = "agent-A",
    write_report_file: bool = True,
) -> dict:
    """一键迁移（业主 2026-10-20 第 2 条）：把本委托 `pending` 且过审的行一次迁进 literature。

    ## 它做四件事，顺序不能换

    1. 取本委托所有 `pending` 行（槽位顺序），过 `admission_plan(on_over_cap="truncate")`：
       DOI 重复 / 高重叠无 `new_content` / `overlap_ok=False` 的逐条拒收；
       超配额的进 `cleared(over_cap)`（一键迁移不整笔拒绝 —— 它的语义是"把通过的都迁走"）；
    2. 通过的那些走现有登记路径（`registrar`）落 literature；
    3. 结算清空本委托：成功的落 `admitted`、被拒的落 `rejected(理由码)`、
       剩下的落 `cleared(over_cap)` + `cleared_at` —— 于是"迁移后 `stage_list(本委托)`
       没有 `pending` 残留"，下一次委托也看不到本委托的行（`request_id` 已经换了）；
    4. 写委托报告（`reports/lit-<request_id>.md`）：已入库一块 + 未入库一块（含受控理由）。

    "不许物理删"是结构性的：本函数只改 `status` 与那几格证据，一次 `delete` 都没有。
    """
    if store is None:
        raise LitStageError("未配置 store：入不了库（不是「都重复了」）", kind="no_store")
    rid = _resolve_request(store, request_id)
    rows = [r for r in _rows(store) if str(r.get("request_id") or "") == rid]
    pending_slots = [str(r.get("slot")) for r in sorted(rows, key=lambda r: str(r.get("slot") or ""))
                     if str(r.get("status")) == "pending"]
    if not pending_slots:
        rep = write_report(store, rid) if write_report_file else None
        return {
            "ok": True, "kind": "", "whole_call_refused": False,
            "reason": "本委托没有待审的行（列表已经是全终态）",
            "request_id": rid, "call_size": 0, "call_limit": _cap_of(cap),
            "delegation_admitted": sum(1 for r in rows if str(r.get("status")) == "admitted"),
            "delegation_limit": MAX_ADMIT_PER_DELEGATION,
            "admitted": [], "refused": [], "cleared": [], "registered": 0,
            "report": rep, "report_path": (rep or {}).get("path"),
        }

    plan = admission_plan(store, request_id=rid, slots=pending_slots, new_content=new_content,
                          cap=cap, on_over_cap="truncate")
    lit_ids, failures, got_all = _register(plan, registrar)
    decisions = _decisions_from(plan, lit_ids, failures)
    with store.tx("lit_candidates", actor=actor, note="lit.admit_all") as tx:
        apply_settlement(tx, decisions)
        # 结算之后再扫一遍：任何还停在本委托 pending 上的行都落 cleared（`not_screened`），
        # 这样"迁移后本委托没有 pending"是一条结构性事实，而不是"我们相信它没有"。
        leftover = [dict(r) for r in tx.rows("lit_candidates")
                    if str(r.get("request_id") or "") == rid
                    and str(r.get("status")) == "pending"]
        if leftover:
            apply_settlement(tx, [
                {"slot": str(r["slot"]), "status": "cleared", "reason_code": "not_screened",
                 "note": "一键迁移结算时仍未审完，随本次委托一并清空（保留可追）"}
                for r in leftover
            ])
        settled = [dict(r) for r in tx.rows("lit_candidates")
                   if str(r.get("request_id") or "") == rid]
    settled.sort(key=lambda r: str(r.get("slot") or ""))
    rep = write_report(store, rid, rows=settled) if write_report_file else None
    done = []
    for item in plan.get("admitted") or []:
        slot = str(item["slot"])
        if slot in lit_ids:
            ov = item.get("overlap") or {}
            done.append({"slot": slot, "title": item["title"], "lit_id": lit_ids[slot],
                         "created": bool(got_all.get(slot, {}).get("created")),
                         "overlap_score": ov.get("overlap_score"),
                         "overlap_kind": ov.get("overlap_kind"),
                         "overlap_with": ov.get("overlap_with"),
                         "new_content": item.get("new_content")})
    refused = list(plan.get("refused") or [])
    for slot, why in failures.items():
        refused.append(_refusal(slot, next((i["row"].get("title") for i in plan["admitted"]
                                           if str(i["slot"]) == slot), ""),
                                why, "registration_failed"))
    return {
        "ok": True,
        "kind": "",
        "whole_call_refused": False,
        "reason": "",
        "request_id": rid,
        "call_size": plan["call_size"],
        "call_limit": plan["call_limit"],
        "delegation_admitted": plan["delegation_admitted"] + len(done),
        "delegation_limit": plan["delegation_limit"],
        "admitted": done,
        "refused": refused,
        "cleared": list(plan.get("cleared") or []),
        "registered": len(done),
        "report": rep,
        "report_path": (rep or {}).get("path"),
    }


# --------------------------------------------------------------------------- 委托报告


def report_path(store: Store, request_id: str) -> Path:
    """报告落点：`<工作区>/reports/lit-<request_id>.md`（下一次委托的 D/H 直接 `fs.read`）。"""
    return Path(store.root) / REPORT_DIR / f"lit-{request_id}.md"


def report_markdown(request_id: str, rows: Sequence[Mapping[str, Any]],
                    *, generated_at: str = "") -> str:
    """委托报告正文：两块都必须有（业主 2026-10-20 第 3 条）。

    - `## 已入库`：每篇的 `lit_id` / 标题 / 年份 / DOI（或 provider）+ 一句"为什么与本次
      检索相关"（`relevance`，没写就退回 `new_content`，再没有就写明"未写"）；
    - `## 未入库`：每篇的槽位 / 标题 / 受控理由码（`schema.CANDIDATE_REASON_CODES`）
      + 一行散文（撤掉 / 拒收 / 重叠度高无新内容 / 超配额 …）。

    两块即使没有行也各留一行 `（无）`：否则"这一块是空的"与"这一块被忘了写"在
    报告上同形，而判据要问的正是"两块都在不在"。
    """
    stamp = generated_at or S.now_iso()
    admitted = [r for r in rows if str(r.get("status")) == "admitted"]
    other = [r for r in rows if str(r.get("status")) in ("withdrawn", "rejected", "cleared")]
    lines: list[str] = [
        f"# 文献检索委托 {request_id} 的入库报告",
        "",
        f"- 委托：`{request_id}`",
        f"- 生成时间：{stamp}",
        "- 盘点：" + "、".join(
            f"{s}={sum(1 for r in rows if str(r.get('status')) == s)}"
            for s in S.CANDIDATE_STATUSES),
        "",
        f"## 已入库（{len(admitted)} 篇）",
        "",
    ]
    if not admitted:
        lines.append("（无）")
    for r in admitted:
        doi = r.get("doi") or f"provider={r.get('provider') or '?'}"
        lines.append(f"- `lit:{r.get('lit_id')}` 《{r.get('title')}》"
                     f"（{r.get('year') if r.get('year') is not None else '年份不详'}）"
                     f" {doi}")
        why = str(r.get("relevance") or r.get("new_content") or "").strip()
        lines.append(f"  相关性：{why or '（A 未写相关性说明）'}")
    lines += ["", f"## 未入库（{len(other)} 篇）", ""]
    if not other:
        lines.append("（无）")
    for r in other:
        code = str(r.get("reason_code") or "(未登记理由码)")
        detail = (str(r.get("withdrawn_reason") or "").strip()
                  or str(r.get("reject_reason") or "").strip()
                  or str(r.get("clear_reason") or "").strip())
        code_text = S.CANDIDATE_REASON_LABELS.get(code, code)
        lines.append(f"- 槽位 {r.get('slot')} 《{r.get('title')}》 — 理由：{code}"
                     f"（{code_text}）" + (f"；{detail}" if detail else ""))
    lines.append("")
    return "\n".join(lines)


def write_report(store: Store, request_id: str, *, rows: Sequence[Mapping[str, Any]] | None = None,
                 generated_at: str = "") -> dict:
    """把委托报告写到 `reports/lit-<request_id>.md`（不存在就建目录）。"""
    rid = str(request_id or "").strip()
    if not rid:
        raise LitStageError("写报告必须知道是哪一次委托（request_id 为空）",
                            kind="no_delegation")
    body_rows = list(rows) if rows is not None else [
        r for r in _rows(store) if str(r.get("request_id") or "") == rid]
    body_rows.sort(key=lambda r: str(r.get("slot") or ""))
    text = report_markdown(rid, body_rows, generated_at=generated_at)
    path = report_path(store, rid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    admitted = sum(1 for r in body_rows if str(r.get("status")) == "admitted")
    other = sum(1 for r in body_rows if str(r.get("status")) in ("withdrawn", "rejected", "cleared"))
    return {
        "path": path.as_posix(),
        "rel_path": f"{REPORT_DIR}/{path.name}",
        "chars": len(text),
        "admitted": admitted,
        "not_admitted": other,
        "request_id": rid,
    }


def report_violations(text: str) -> list[str]:
    """委托报告的判据：两块都在、都非空、未入库的理由都是受控取值。

    返回违规描述列表（空 = 通过）。由 `tests/test_search_tools_stage_admit.py` 的正控
    与负控直接打它 —— 负控若不走同一条判据，就证明不了"去掉一块会红"。
    """
    bad: list[str] = []
    body = str(text or "")
    if not body.strip():
        return ["报告是空的"]
    sections: dict[str, str] = {}
    current = ""
    for raw in body.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = ""
            continue
        if current:
            sections[current] += line + "\n"
    for name in ("已入库", "未入库"):
        hit = next((k for k in sections if k.startswith(name)), None)
        if hit is None:
            bad.append(f"缺 `## {name}` 块（这一块是交付物的一部分，不是可选）")
            continue
        if not sections[hit].strip():
            bad.append(f"`## {hit}` 块是空的（没有条目时也要写（无））")
    other = next((v for k, v in sections.items() if k.startswith("未入库")), "")
    for line in other.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        if "理由：" not in line:
            bad.append(f"未入库的这一条没有「理由：」：{line[:60]}")
            continue
        code = line.split("理由：", 1)[1].split("（", 1)[0].strip()
        if code not in S.CANDIDATE_REASON_CODES:
            bad.append(f"未入库的理由码 {code!r} 不在受控取值里（不许自由发挥）：{line[:60]}")
    admitted_text = next((v for k, v in sections.items() if k.startswith("已入库")), "")
    for line in admitted_text.splitlines():
        if line.strip().startswith("- ") and "`lit:" not in line:
            bad.append(f"已入库的这一条没有 lit_id：{line.strip()[:60]}")
    return bad

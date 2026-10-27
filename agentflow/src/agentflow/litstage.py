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

import contextvars
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import dedup as D
from . import schema as S
from . import textutil as T
from .store import Store

__all__ = [
    "CANDIDATE_DECISIONS",
    "MAX_ADMIT_PER_CALL",
    "MAX_ADMIT_PER_DELEGATION",
    "OVERLAP_HIGH_JACCARD",
    "OVERLAP_KINDS",
    "REPORT_DIR",
    "UNDECIDED_TITLE_CHARS",
    "LitStageError",
    "candidate_identity",
    "fold_legacy",
    "judged_state",
    "undecided",
    "undecided_reason",
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

#: 「待新增文献列表」现行的决策词表：三态（业主 2026-10-26 Q16 口径：
#: 「待裁 / 入库 / 拒收」，注册即待裁）。
#:
#: 与 `schema.CANDIDATE_STATUSES`（五个值）的关系必须说清，否则这里就是第二份唯一真源：
#:
#: - `schema.CANDIDATE_STATUSES` 是「磁盘上读得进来的取值集合」—— 它必须容得下两个历史档
#:   （`withdrawn` / `cleared`），否则老工作区的行连写回都写不回去（那是数据毁灭，不是迁移），
#:   而那个文件是 FC-27 禁改区；
#: - 本词表是「现在这台状态机能写、能判」的三态：本模块只写这三个值，两个历史档一律经
#:   `fold_legacy` 在读侧折进来（`cleared` ⇒ `rejected` + `over_cap`，
#:   `withdrawn` ⇒ `rejected` + `withdrawn_by_reviewer`）。于是写侧再也不会产出第四态。
CANDIDATE_DECISIONS: tuple[str, ...] = ("pending", "admitted", "rejected")

#: 历史档 ⇒ `(折成哪一态, 默认理由码, 事实在哪个字段里)`：读侧折算的唯一实现。
#:
#: `over_cap` 这一条是业主 Q16 第 ① 条点名的：「`cleared`（配额满）必须折进
#: rejected + reason_code=over_cap，不留第四态」。`withdrawn` 走同一台机器：
#: 「撤掉」与「拒收」的差别从此落在受控理由码上（`withdrawn_by_reviewer`），
#: 不再多占一个状态格 —— 状态格只有一个轴：这一条判过没有。
_LEGACY_CANDIDATE: dict[str, tuple[str, str, str]] = {
    "cleared": ("rejected", "over_cap", "clear_reason"),
    "withdrawn": ("rejected", "withdrawn_by_reviewer", "withdrawn_reason"),
}

#: 提交闸拒信里题名截前多少字（业主 Q16 第 ③ 条：`<slot + 标题前 40 字>`）。
UNDECIDED_TITLE_CHARS: int = 40


def fold_legacy(row: Mapping[str, Any]) -> dict:
    """把一行历史档折成三态（读侧唯一的折算点；不改盘上的行，返回副本）。

    折出来的行把"当初为什么走到这一档"搬进 `reject_reason`：`cleared` 的那句在
    `clear_reason` 里、`withdrawn` 的那句在 `withdrawn_reason` 里 —— 折完之后
    行仍然说得出理由，而不是变成一个只有状态码的空壳。理由码保留行上已有的受控取值
    （`over_cap` / `not_screened` 这些是当初真的发生的事），只有当它缺失或不受控时
    才退回该档的默认码。
    """
    out = dict(row)
    legacy = _LEGACY_CANDIDATE.get(str(out.get("status") or ""))
    if legacy is None:
        return out
    status, default_code, field = legacy
    out["status"] = status
    code = str(out.get("reason_code") or "")
    out["reason_code"] = code if code in S.CANDIDATE_REASON_CODES else default_code
    if not str(out.get("reject_reason") or "").strip():
        out["reject_reason"] = (str(out.get(field) or "").strip()
                               or _code_label(out["reason_code"]))
    return out


def judged_state(row: Mapping[str, Any]) -> str:
    """这一条判过没有：`pending` / `admitted` / `rejected`（先折算历史档）。

    判据（业主 Q16 原话「A 确实读过、逐篇决定过」）落在三档上：

    - `rejected` ⇒ 判过。拒收本身就是决定，不论是人判的（`rejected_off_topic` …）
      还是确定性判据判的（`over_cap` / `not_screened`）—— 后两者由机器做，A 不需要读；
    - `admitted` 且 `relevance` 非空 ⇒ 判过。那一句「为什么与本次检索相关」就是
      "我读过这一篇"的证据（`schema.LitCandidate.relevance` 的口径原本就是它）；
    - `admitted` 但 `relevance` 空 ⇒ 没判过。这是本判据最要紧的一格：入库了却
      写不出为什么相关的行，没有任何"读过"的证据 —— 真机 `projects/mp3-r3` 的 33 条
      正是这个形状（同一秒整批入库、`relevance` 48/48 全空）。它不改入库判据
      （`webui/readers._library_admission` 照旧只读 `status == "admitted"`）：
      文献库面问「这一篇在不在库里」，提交闸问「A 判过没有」，两个问题。
    - 其余（`pending`、以及认不出的状态）⇒ 没判过。"认不出"不许折成"判过"。
    """
    folded = fold_legacy(row)
    status = str(folded.get("status") or "")
    if status == "admitted":
        return "admitted" if str(folded.get("relevance") or "").strip() else "pending"
    if status in ("pending", "rejected"):
        return status
    return "pending"


def undecided(rows: Sequence[Mapping[str, Any]]) -> list[dict]:
    """还没判的那些条：`[{slot, title, status, why}]`（提交闸唯一的读数来源）。

    `why` 区分两档，因为做法不同：待裁的 `pending` 要一轮判；"入库了但没有
    relevance"的那一档要补那一句（或判拒），它不是"还没开始"。
    """
    waiting: list[dict] = []
    for row in rows:
        if judged_state(row) != "pending":
            continue
        folded = fold_legacy(row)
        why = ("这一条还没有 relevance（没写「为什么与本次检索相关」），"
               "而它已经挂着 lit_id —— 入库发生了、读过的证据不在，按没判算"
               if str(folded.get("lit_id") or "").strip() else
               "这一条还停在 pending（没判过）")
        waiting.append({"slot": str(row.get("slot") or ""),
                        "title": str(row.get("title") or ""),
                        "status": str(folded.get("status") or ""),
                        "why": why})
    waiting.sort(key=lambda item: item["slot"])
    return waiting


def _decision_counts(rows: Sequence[Mapping[str, Any]]) -> dict:
    """按三态数一遍（`{"pending": n, "admitted": n, "rejected": n}`，键恒在这三个）。

    它是拒信与报告里"数没全更新为入库和拒收"那句话的读数来源：业主 Q16 的判据
    问的就是这个数（`pending` 必须是 0）。
    """
    counts = {s: 0 for s in CANDIDATE_DECISIONS}
    for row in rows:
        counts[judged_state(row)] += 1
    return counts


def undecided_reason(waiting: Sequence[Mapping[str, Any]],
                     request_id: str = "") -> str:
    """提交闸的拒信原文：逐条点名 + 做法（业主 Q16 第 ③ 条）。

    为什么拒信要逐条点名而不是报一个数：「还有 14 条没判」这句谁都对得上，
    而 A 手上要做的是"去判哪一条"。所以每条给 `槽位 + 题名前 40 字`，
    与 `lit.stage_list` 的 `slot/title` 两格逐字对得上（它照着念就能判）。
    """
    slots = "、".join(
        f"{item['slot']}《{T.clip(str(item.get('title') or ''), UNDECIDED_TITLE_CHARS)}》"
        for item in waiting)
    scope = f"本次委托（{request_id}）" if request_id else "本委托"
    return (
        f"还有 {len(waiting)} 条没判：{slots} ⇒ 整批不许提交入库。"
        f"{scope}的待新增列表必须逐条判过（判过的证据：判收的带一句 relevance，"
        "判拒的带 relevance + 受控 reason_code）才能提交。"
        "做法：逐条来 —— 判收的用 `lit.admit`（这一条的 relevance 要有值：缺就用 "
        "`lit.stage_add` 带 relevance 重进**同一篇**，同一委托内同一 DOI 只占一个槽，"
        "补进原槽、不发新号）；判拒的用 `lit.stage_reject`"
        "（受控理由码 + 一句为什么）。已经挂着 lit_id 却没有 relevance 的那几条，"
        "用 `lit.stage_reject` 判拒（受控理由码），或把这一篇重新 `lit.stage_add` "
        "并带上 relevance 再判 —— 撤掉与拒收都只换状态、不删行。"
    )


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


def _jaccard_of(ta: set[str], tb: set[str]) -> float:
    """两个已词法化的标题词集的 Jaccard（`title_jaccard` 的免重复词法化版）。"""
    if not ta or not tb:
        return 0.0
    return round(len(ta & tb) / len(ta | tb), 4)


def literature_index(store: Store) -> list[dict]:
    """把 `literature` 表读一次、每行的标题词集算一次（重叠比对的索引）。

    为什么要有这一格：`overlap_check` 原来是"一条候选读一遍全表 + 逐行重算词集"，
    而 `admission_plan` 是逐槽调它的 ⇒ 10 个槽 × 300 行文献 = 表读 10 次、
    `title_terms` 调 6000 次（实测 `temp/rbe3_measure.py`，2026-10-27）。
    表读一次、词集算一次之后，同一次判断的读数一模一样（它只读、不动任何行）。

    `checked` 的语义不变：表读不出来时 `store.rows` 照旧抛 `StoreError`，
    由调用方折成 `table_unreadable` —— 这一层不吞异常。
    """
    out: list[dict] = []
    for row in store.rows("literature"):
        out.append({
            "lit_id": str(row.get("lit_id") or ""),
            "doi": D.normalize_doi(row.get("doi")),
            "title": str(row.get("title") or ""),
            "terms": title_terms(row.get("title")),
        })
    return out


#: 一次 `admission_plan` 里共享的重叠索引（见 :func:`overlap_check` 的同名参数）。
#:
#: ## 为什么是 ContextVar 而不是给 `overlap_check` 加一个必给的参数
#:
#: `overlap_check` 是判据用的接缝：`tests/test_search_tools_stage_admit.py` 的负控把一个
#: 三参数 lambda 换上去（`lambda store, title, doi=None: {…}`），用它证明"关掉重叠检查 ⇒
#: 高重叠那篇会被收进来"。第一版我给 `admission_plan` 加了 `index=` 关键字实参 ——
#: 那个负控当场 `TypeError: got an unexpected keyword argument 'index'`，而它本来是绿的。
#: 判据说的是"接缝的形状不许改"，所以改成按执行上下文传：收益（表读一次、词集算一次）
#: 保住，接缝的调用形状一个字没动。用 ContextVar 而不是模块级变量：`scheduler` 的工作
#: 线程会并发跑到这里，模块级变量会让两条链路互相串味（与 `cancellation._CURRENT_TOKEN`
#: 同一个理由、同一个做法）。
_ACTIVE_LIT_INDEX: contextvars.ContextVar = contextvars.ContextVar(
    "agentflow_lit_overlap_index", default=None)


def _overlap_with_index(store: Store, title: Any, doi: Any,
                        index: Sequence[Mapping[str, Any]]) -> dict:
    """在"已经建好索引"的上下文里跑一次 `overlap_check`（调用形状仍是三个参数）。

    为什么要这一层薄封装：索引要按执行上下文传给 `overlap_check`（见
    `_ACTIVE_LIT_INDEX` 那段说明 —— 给它加参数会改掉判据用的接缝形状），
    所以"挂上 → 调 → 复位"必须收在一处，且复位要在 `finally` 里
    （中途抛异常留下一个挂着的索引，下一次调用就会读到一个过期的全表）。
    """
    token = _ACTIVE_LIT_INDEX.set(tuple(index))
    try:
        return overlap_check(store, title, doi)
    finally:
        _ACTIVE_LIT_INDEX.reset(token)


def overlap_check(store: Store | None, title: str, doi: str | None = None) -> dict:
    """与本地库（`literature` 表）比对：DOI 完全相同 ⇒ 重复；否则按标题词集 Jaccard。

    索引的来源三选一，读数逐字相同：当前执行上下文里挂着的（`admission_plan` 逐槽
    调它一次判断只读一遍全表、每个标题只算一次词集）、否则现建一份。

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
    want_terms = title_terms(title)
    cands = _ACTIVE_LIT_INDEX.get()
    if cands is None:
        cands = literature_index(store)
    best_score = 0.0
    best_lit: str | None = None
    best_title = ""
    for item in cands:
        row_doi = str(item.get("doi") or "")
        if want_doi and row_doi and want_doi == row_doi:
            return {
                "checked": True,
                "duplicate": True,
                "overlap_score": 1.0,
                "overlap_kind": "doi_exact",
                "overlap_with": str(item.get("lit_id") or ""),
                "requires_new_content": True,
                "reason": (
                    f"DOI 与本地 literature 的 lit_id={item.get('lit_id')} 完全相同"
                    f"（{want_doi}）⇒ 视为重复，不入库"
                ),
            }
        terms = item.get("terms")
        score = _jaccard_of(want_terms, terms) if isinstance(terms, set) else title_jaccard(
            title, item.get("title"))
        if score > best_score:
            best_score, best_lit = score, str(item.get("lit_id") or "")
            best_title = str(item.get("title") or "")
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


def current_request_id_of(rows: Sequence[Mapping[str, Any]]) -> str:
    """当前委托的"已经拿到行"版：同一个判据，不再把表读一遍（见 `current_request_id`）。

    为什么要这一格：`list_candidates` 一拍里要用它两次（解析默认视图 + 回填
    `current_request_id` 那一格），而 `current_request_id(store)` 每次都
    `store.rows("lit_candidates")` 重读一遍全表 ⇒ 一拍读 2~3 次同一张表。
    判据只有一份：`current_request_id` 现在也走这里。
    """
    if not rows:
        return ""
    newest = max(rows, key=lambda r: str(r.get("slot") or ""))
    return str(newest.get("request_id") or "")


def current_request_id(store: Store | None) -> str:
    """当前委托 = 槽位号最大那一行所属的 `request_id`（没有行 ⇒ 空串）。

    为什么这样定"当前"：槽位号只增不复用（`store.alloc_id("candidate")`），
    于是"最后一个开始暂存的委托"就是号最大的那一行的委托 —— 不需要另一处
    "当前委托是谁"的状态（那种状态必然与盘上的行漂，而漂了不会报错）。
    """
    if store is None:
        return ""
    return current_request_id_of(_rows(store))


def _resolve_request(store: Store | None, request_id: str | None) -> str:
    rid = str(request_id or "").strip() or current_request_id(store)
    if not rid:
        raise LitStageError(
            "说不清这是哪一次委托（待新增列表里还没有任何行，调用方也没给 request_id）⇒ "
            "没有委托就没有「本次」筛选，不许拿一个空集冒充",
            kind="no_delegation",
        )
    return rid


def candidate_identity(title: Any, doi: Any) -> str:
    """一条候选在一次委托内的身份：规范化 DOI 优先，DOI 空才退回规范化标题。

    为什么 DOI 优先，而不是"标题与 DOI 一起比"：同一篇在两次检索里交回的题名
    可能差一个连字符或副标题位置（真机 `mp3-r4` 的 000001 与 000004 就是
    `Cartan‐type` 与 `Cartan-type`），而 DOI 是同一串 —— 身份若把标题也算进去，
    这种"同一篇"就会漏配，于是又长出一个槽位。DOI 空时才退回标题（与
    `dedup.literature_keys` 的次序一致：DOI → 标题+年 → 仅标题，这里只用"能拿到的那一级"）。

    这不是判重键（判重键仍是 `dedup.literature_keys` / `find_existing_literature`），
    也不跨委托：它只回答"这一次委托的待新增列表里，这一篇是不是已经有一个槽"。
    """
    key = D.normalize_doi(doi)
    if key:
        return "doi:" + key
    return "title:" + T.normalize(str(title or ""))


def _top_up(row: dict, raw: Mapping[str, Any]) -> list[str]:
    """把这一条 entry 里非空的那几格补进已有的 pending 槽；返回真写了的字段名。

    只补"这次给了、那一槽还没有或值不同"的格：空串/None 不覆盖已有值 ——
    否则一次"只带 relevance 的重进"会把摘要、URL 洗成空（那些格是当初广搜带回来的）。
    返回字段名列表（不是布尔）是给调用方留读数：`fields` 空 = 这一条没有新内容，
    它早就已经在列表里了（这正是"A 又登了一次同一篇"该看到的那句话）。
    """
    wrote: list[str] = []
    pairs: tuple[tuple[str, Any, int], ...] = (
        ("relevance", raw.get("relevance"), 400),
        ("summary", raw.get("summary"), 1200),
        ("url", raw.get("url") if raw.get("url") is not None else raw.get("pdf_url"), 0),
        ("year", raw.get("year"), 0),
        ("type_code", raw.get("type_code") if raw.get("type_code") else raw.get("type"), 0),
        ("provider", raw.get("provider"), 0),
    )
    for name, value, cap in pairs:
        if value is None:
            continue
        if isinstance(value, str):
            if not value.strip():
                continue
            value = T.clip(value.strip(), cap) if cap else value.strip()
        current = row.get(name)
        if str(current if current is not None else "") == str(value):
            continue
        row[name] = value
        wrote.append(name)
    return wrote


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
        updated: list[dict] = []
        # 同一委托内同一篇只占一个槽（G9 修法 ①）：身份命中一个还没判过的槽 ⇒
        # 把这一条新给的内容补进那一槽，不发新号。判过的槽（rejected / admitted）不并：
        # 它们要留着"当初为什么拒/撤"的记录，合并会把那一段历史抹掉。
        open_slots: dict[str, dict] = {}
        for r in same:
            if str(r.get("status")) == "pending":
                open_slots.setdefault(candidate_identity(r.get("title"), r.get("doi")), dict(r))
        for raw in items:
            title = str(raw.get("title") or "").strip()
            if not title:
                raise LitStageError(
                    "有一条候选没有标题：空标题的槽位将来查不出「撤掉的是哪一篇」",
                    kind="bad_entry",
                    detail={"entry": {k: raw.get(k) for k in ("doi", "provider")}},
                )
            ident = candidate_identity(title, raw.get("doi"))
            open_row = open_slots.get(ident)
            if open_row is not None:
                wrote = _top_up(open_row, raw)
                if wrote:
                    S.LitCandidate(**{k: open_row[k] for k in open_row
                                      if k in S.LitCandidate.__dataclass_fields__}).validate()
                    tx.upsert("lit_candidates", open_row, note=note)
                updated.append({"slot": str(open_row.get("slot") or ""),
                                "batch": int(open_row.get("batch") or 0),
                                "title": str(open_row.get("title") or ""),
                                "fields": wrote})
                continue
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
            # 刻意不把刚建的这一槽放进 `open_slots`：同一次调用内"条目数 == 新槽数"
            # 这个约定不能破。理由在代码外：`agent_a/run_once.py` 用
            # `zip(fresh_entries, slots)` 配对"哪一条候选下的载、登记的哪一篇"
            # （`entry_by_slot = dict(zip(slots, fresh_entries))`）—— 若一次调用里两条
            # 同身份的 entry 并成一个槽，那个 zip 就整体错位一格，下载与登记会配上
            # 另一篇的元数据（静默、且看起来成功）。跨调用的重复才是真机要治的形态
            # （r-000001：自动链路一批、A 补 relevance 另一批）。
    return {"request_id": rid, "batch": the_batch, "count": len(staged),
            "staged": staged, "updated": updated}


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

    返回的每一行都是三态折算后的（`litstage.fold_legacy`）：盘上的 `cleared`
    读成 `rejected` + `reason_code=over_cap`，`withdrawn` 读成 `rejected` +
    `withdrawn_by_reviewer`，理由搬进 `reject_reason`。所以列表视图里永远只有
    `pending` / `admitted` / `rejected` 三档（业主 2026-10-26 Q16）。

    空槽位（原来叫 `withdrawn`、现在折成 `rejected` + `withdrawn_by_reviewer`）
    并没有被物理删除（序号不复用），所以题名、理由、`added_at` 全都还在 —— 于是
    "第 3 号被撤了哪一篇、为什么"是查得出来的。这正是业主口径 ③ 的落点：撤掉 ≠ 删掉。

    `status` 过滤同时认两种形态：折算后的三态（`pending`/`admitted`/`rejected`）
    与盘上的历史档名（`cleared` / `withdrawn`，照原样查得到那几条）—— 后者是为了
    "查历史"这条路不因为折算而断（老工作区里按 `cleared` 查仍然查得出那 14 条）。

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
    # 「当前委托」算一次、两处用（默认视图与回填那一格）：它原来是两/三次
    # `current_request_id(store)`，每次都把同一张表重读一遍。
    current = current_request_id_of(all_rows)
    rid = str(request_id or "").strip() or current
    scoped = _scoped_rows(all_rows, rid)
    if batch is not None:
        scoped = [r for r in scoped if int(r.get("batch") or 0) == int(batch)]
    if status is not None:
        rows = [fold_legacy(r) for r in scoped
                if str(r.get("status") or "") == status
                or judged_state(r) == status]
    else:
        rows = [fold_legacy(r) for r in scoped]
    rows.sort(key=lambda r: str(r.get("slot") or ""))
    # 计数按委托过滤后、状态过滤前那一份算：调用方问"这一批还有几篇 pending"时
    # 需要同时看到全部态，否则 status=admitted 那一次查询会把"总数 12"读成"总数 9"。
    # 键集合仍是 `schema.CANDIDATE_STATUSES` 那五个（`lit.stage_list` 的冻结声明
    # 就是这么写的），但两个历史档永远是 0：它们已经折进 `rejected`。
    counts = {s: 0 for s in S.CANDIDATE_STATUSES}
    for r in scoped:
        s = judged_state(r)
        if s in counts:
            counts[s] += 1
    slots = [str(r.get("slot") or "") for r in rows]
    gaps: list[str] = []
    if slots:
        have = {int(s) for s in slots}
        gaps = [S.format_id(n) for n in range(min(have), max(have) + 1) if n not in have]
    waiting = undecided(scoped)
    # 同一委托内同一篇占多个槽的读数（G9 修法 ②：只报数，不动 counts 的分子分母）。
    groups: dict[str, list[str]] = {}
    for r in scoped:
        groups.setdefault(candidate_identity(r.get("title"), r.get("doi")), []).append(
            str(r.get("slot") or ""))
    dup_groups = sorted(
        ({"key": k, "slots": sorted(v)} for k, v in groups.items() if len(v) > 1),
        key=lambda g: g["slots"][0])
    return {
        "request_id": rid,
        "duplicate_rows": sum(len(g["slots"]) for g in dup_groups),
        "duplicate_groups": dup_groups,
        "current_request_id": current,
        "batch": batch,
        "status": status,
        "count": len(rows),
        "counts": counts,
        "gaps": gaps,
        "rows": rows,
        "total_all_delegations": len(all_rows),
        "note": (
            "默认只返回当前委托的行（`request_id` = 最近一次暂存的那次委托）；"
            "查历史请显式给 request_id（`*` = 全部）。状态只有三档："
            "`pending` 待裁 / `admitted` 入库 / `rejected` 拒收；"
            "历史的 `cleared` 读成 rejected+over_cap、`withdrawn` 读成 "
            "rejected+withdrawn_by_reviewer（撤掉的槽位仍在，序号不复用）。"
            f"本委托还有 {len(waiting)} 条没判：只要还大于 0，`lit.admit_all` "
            "就整批拒绝（`lit.admit` 逐条入库不受它拦）。"
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


def _terminal(store: Store, slot: str, *, code: str, note: str,
              slot_field: str, actor: str, tx_note: str) -> dict:
    """把某一槽写成判过的那一档：`status="rejected"` + 受控理由码 + 一行散文。

    为什么不再有"写成 withdrawn"这条分支（2026-10-26 Q16）：状态只有三态
    （待裁 / 入库 / 拒收），"撤掉"与"拒收"的差别现在落在受控理由码上
    （`withdrawn_by_reviewer` 还是 `rejected_low_quality`），不再多占一个状态格。
    `slot_field` 保留原样：`lit.stage_withdraw` 仍然把那一句同时写进
    `withdrawn_reason`（老读者按那一列查"撤了什么"照旧查得到），
    `reject_reason` 两边都写满 —— 折完之后行仍然说得出理由。

    可改的条件是 `judged_state(row) == "pending"`，不是"status 字面是 pending"：
    历史链路整批入库、`relevance` 空着的那几条（真机 33 条就是这个形状）也算
    "没判过"，于是它们还能被逐条判拒 —— 否则那种行会永远卡在"写不进 relevance、
    又不许判拒"里，提交闸对它所在的那次委托就成了永久关闭。
    """
    with store.tx("lit_candidates", actor=actor, note=tx_note) as tx:
        row = next((r for r in tx.rows("lit_candidates") if str(r.get("slot")) == str(slot)), None)
        if row is None:
            raise LitStageError(f"待新增列表里没有槽位 {slot!r}", kind="unknown_slot",
                                detail={"slot": slot})
        if judged_state(row) != "pending":
            raise LitStageError(
                f"槽位 {slot!r} 已经判过了（{judged_state(row)}，盘上 status="
                f"{row.get('status')!r}）⇒ 只有还没判的那一槽能改成 rejected",
                kind="not_pending", detail={"slot": slot, "status": row.get("status")},
            )
        row = dict(row)
        row["status"] = "rejected"
        row["reason_code"] = code
        row[slot_field] = str(note or "").strip() or _code_label(code)
        row["reject_reason"] = row[slot_field]
        S.LitCandidate(**{k: row[k] for k in row
                          if k in S.LitCandidate.__dataclass_fields__}).validate()
        tx.upsert("lit_candidates", row, note=tx_note)
    return {"slot": str(slot), "status": "rejected", "reason_code": code,
            "reason": row[slot_field], "title": row.get("title"),
            "request_id": row.get("request_id"), "batch": row.get("batch")}


def withdraw(store: Store | None, slot: str, reason_code: str, note: str = "",
             *, actor: str = "agent-A") -> dict:
    """撤掉某一槽：状态落 `rejected` + 受控理由码（`withdrawn_by_reviewer`），不物理删除。

    撤掉之后可以再 `stage_add` 补位 —— 但新条进的是新序号（旧号不复用），
    所以列表里会同时看到"第 3 号（撤掉，理由…）"与"第 13 号（补进来的那条）"。
    那一句同时写进 `withdrawn_reason` 与 `reject_reason`：前者是老读者查
    "撤了什么"的那一列，后者是三态里"拒收的理由"那一列。

    `reason_code` 必须是 `schema.CANDIDATE_REASON_CODES` 里的受控取值
    （业主 2026-10-20 第 3 条：报告里的理由只认受控取值，不许自由发挥）。
    """
    if store is None:
        raise LitStageError("未配置 store：撤不掉（不是「已经撤过了」）", kind="no_store")
    code = _check_code(reason_code)
    return _terminal(store, slot, code=code, note=note,
                     slot_field="withdrawn_reason", actor=actor,
                     tx_note="lit.stage_withdraw")


def reject(store: Store | None, slot: str, reason_code: str, note: str = "",
           *, actor: str = "agent-A") -> dict:
    """审内容后拒收：状态落 `rejected` + 受控理由码 + `reject_reason`，不物理删除。"""
    if store is None:
        raise LitStageError("未配置 store：拒收不了（不是「已经拒过了」）", kind="no_store")
    code = _check_code(reason_code)
    return _terminal(store, slot, code=code, note=note,
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
    require_judged: bool = False,
) -> dict:
    """入库前的那一笔判断：提交闸 + 条数上限 + 重叠检查 + 逐条该不该进（一行都不写）。

    这是"入库这个动作"的唯一入口判据：`lit.admit` / `lit.admit_all` / A 的自动链路
    三条路都从这里过，谁也不许在调用点上各判一次（判据两份必然漂，而漂的形态是
    "工具说拒了、实现却写进去了"）。

    ## 提交闸（业主 2026-10-26 Q16 第 ③ 条）

    `require_judged=True` 的那两条路（`lit.admit_all` 与 A 的自动链路）是"整批提交"：
    本委托只要还有一条没判，整批一条都不许入库，拒信逐条点名（`undecided_reason`）。
    "判过"的定义只此一处：`judged_state`（`pending` 与"入库了却写不出 relevance"都算没判）。

    逐条入库（`lit.admit`，`require_judged=False`）不受这条闸拦 —— 它就是判决本身：
    它要过的是下面那条"每一条入库都必须带 relevance"的逐条判据。

    ## 两档超限处置（`on_over_cap`）

    - `"refuse_all"`（`lit.admit` 用）：本次要入的条数超过上限 ⇒ 整笔拒绝，
      一条都不入。为什么整笔：如果前 10 条进了、第 11 条被挡，调用方会读成
      "第 11 条被审掉了"，而真相是"这一次调用根本不成立"。
    - `"truncate"`（`lit.admit_all` / A 的自动链路用）：按槽位号顺序把前 N 条
      通过检查的收进来，其余落 `rejected` + `reason_code="over_cap"` ——
      一键迁移的语义是"把通过的都迁走"，不是"有一条超限就全不动"。
      落盘处不再是第四态 `cleared`（业主 Q16 第 ① 条：配额满必须折进
      rejected + over_cap），但 `plan["cleared"]` 这个键名沿用下来：
      它是"没进去的那几条"这一个读数格，不是状态名（`lit.admit` 的 `returns=`
      已经把它钉在冻结声明里，改名要人重冻快照）。

    ## 逐条拒收（业主口径 ②④）

    - 这一条已经判过（`judged_state != "pending"`）⇒ 拒（`already_terminal`）；
    - 这一条没有 relevance（行上没有、调用级也没给）⇒ 拒（`missing_relevance`），
      行保持原样：没写"为什么与本次检索相关"就等于没读过它（Q16 第 ② 条）。
      "入库了但 relevance 空"的历史行也走这一格 —— 它先要补上那一句才谈得上入库；
      补不上就判拒（`lit.stage_reject`），别把它折成"入库了"。
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
    scoped = [fold_legacy(r) for r in rows
              if str(r.get("request_id") or "") == rid]
    if slots is None:
        if batch is None:
            raise LitStageError(
                "admit 要么给 slots（要入库的那几个槽位），要么给 batch（这一批全部待审的）",
                kind="no_target",
            )
        wanted = [str(r.get("slot")) for r in sorted(scoped, key=lambda r: str(r.get("slot") or ""))
                  if int(r.get("batch") or 0) == int(batch) and judged_state(r) == "pending"]
    else:
        wanted = []
        for raw in slots:
            s = str(raw or "").strip()
            if s and s not in wanted:
                wanted.append(s)
        if not wanted and not require_judged:
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
    already = sum(1 for r in scoped if judged_state(r) == "admitted")

    items: list[dict] = []
    refused: list[dict] = []
    over_cap: list[dict] = []
    # 索引建一次、逐槽复用：`overlap_check` 自己也会建，但那是"每条候选一遍全表"。
    lit_index = literature_index(store)
    for slot in wanted:
        row = by_slot[slot]
        state = judged_state(row)
        if state != "pending":
            refused.append(_refusal(slot, row.get("title"), (
                f"这一条已经判过了（{state}）⇒ 不许再判它一次"
                + ("（拒收是终态：这一篇若其实要收，`lit.stage_add` 带 relevance 重进会"
                   "另发一个新槽 —— 旧槽的拒收记录保留、报告会把它列进未入库；"
                   "所以只是缺 relevance 时别先撤，直接补进原槽）"
                   if state == "rejected" else "")
            ), "already_terminal"))
            continue
        relevance = str(row.get("relevance") or "").strip()
        if not relevance:
            refused.append(_refusal(slot, row.get("title"), (
                "这一条没有 relevance（没写「为什么与本次检索相关」）⇒ 不许入库："
                "判过的证据就是那一句。"
                "做法：判拒就用 `lit.stage_reject`（受控理由码）；要收就用 `lit.stage_add` "
                f"带 relevance 重进**同一篇**（同一委托内同一 DOI 只占一个槽：补进 "
                f"{slot} 这一槽，不发新号）。**不要先撤掉再重进** —— 撤掉之后再登记就是"
                "另一个槽位，报告上同一批题名会同时出现在「已入库」与「未入库」两块。"
            ), "missing_relevance"))
            continue
        ov = _overlap_with_index(store, str(row.get("title") or ""), row.get("doi"),
                                 lit_index)
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
    if require_judged:
        # 提交闸（Q16 第 ③ 条）：整批提交的那两条路，本委托只要还有一条没判，
        # 一条都不许入库。判据只有 `undecided` 那一处（打桩成恒空 ⇒ 本闸失效，
        # 见 tests/test_pending_list_is_three_state.py 的反真空那一条）。
        waiting = undecided(scoped)
        if waiting:
            return {**base, "ok": False, "kind": "undecided_items",
                    "whole_call_refused": True,
                    "reason": undecided_reason(waiting, rid),
                    "undecided": waiting, "counts": _decision_counts(scoped),
                    "call_size": 0, "admitted": []}
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


#: 结算核对的读数（进程内账，与 `clock.waits()` 同形：一条一条攒，判据自己 reset）。
#:
#: ## 为什么要有这一格（2026-10-27，R-BE3 的 ①-3）
#:
#: `apply_settlement` 里有两个 `continue`：决定指向的槽位在表里读不到、或状态码不在三态里，
#: 那一笔决定就被"静默丢掉" —— 写侧什么都不说。而调用方的 `admitted[]` 取自登记路径回来的
#: `lit_ids`，并不取自结算结果 ⇒ 并发窗口里可以出现"报告说已入库、候选行还是 pending"。
#:
#: 这一格把那两种形态变成看得见的事实（读数，不改行为）：
#: - `apply_settlement` 丢掉一笔决定 ⇒ 立刻记一条 `kind="dropped_slot" / "dropped_status"`；
#: - 结算之后由 :func:`settlement_mismatch` 回读一次候选行 ⇒ "报的说入库了、行上不是"记
#:   `kind="status_not_written" / "lit_id_not_written" / "missing_row"`。
#:
#: 修不修行为要等这条读数先跑出一批真机数据（业主口径：先要读数）。
_SETTLEMENT_READINGS: list[dict] = []
#: 读数最多留几条（进程内账，无上限就是无界增长）。
_SETTLEMENT_READINGS_MAX: int = 64
#: 这一族读数的受控码（`settlement_readings()` 的 `rows[].code` 恒为它）。
SETTLEMENT_MISMATCH: str = "settlement_mismatch"


def _note_settlement_mismatch(**fields: Any) -> None:
    """记一条结算核对读数（纯旁路：记账炸了不许带坏结算）。"""
    try:
        _SETTLEMENT_READINGS.append({"code": SETTLEMENT_MISMATCH, **fields})
        del _SETTLEMENT_READINGS[:-_SETTLEMENT_READINGS_MAX]
    except Exception:  # noqa: BLE001 - 旁路
        pass


def settlement_readings(*, reset: bool = False) -> dict:
    """读出结算核对的账；`reset=True` 顺手清空（判据之间的隔离点）。

    空清单是有内容的读数（"结算与报告一致"），不是"这一格没查"——
    没查成由各条读数自己的 `checked` 说。
    """
    rows = list(_SETTLEMENT_READINGS)
    if reset:
        _SETTLEMENT_READINGS.clear()
    return {"checked": True, "count": len(rows), "rows": rows,
            "reason": "" if not rows else (
                f"{len(rows)} 条结算核对不一致（报告与候选行对不上，或决定被丢掉）")}


def settlement_mismatch(store: Store | None, decisions: Iterable[Mapping[str, Any]], *,
                        request_id: str = "") -> dict:
    """结算之后回读一次候选行，核对"报告说入库"与"行上真是那样"（只读）。

    为什么必须在这里回读、而不是在 `apply_settlement` 里顺手看一眼：那一步在事务内，
    `tx.rows` 交回的就是刚被 `upsert` 改过的那一份 —— 在里面比等于自己跟自己比。
    真正要核的是"这一笔提交之后盘上是什么"，所以调用点必须在 `with store.tx(...)` 之后。

    三态：`store is None` ⇒ `checked=False`（没查成，不是"一致"）；否则逐条比，比出来的
    每一处差异都记进 :data:`_SETTLEMENT_READINGS`，并由这里返回同一批。
    """
    if store is None:
        return {"checked": False, "count": 0, "rows": [],
                "reason": "没有 store：结算核对没查成（不是「一致」）"}
    want = [dict(d) for d in decisions
            if str(d.get("status") or "") in CANDIDATE_DECISIONS
            or str(d.get("status") or "") in _LEGACY_CANDIDATE]
    live = {str(r.get("slot") or ""): r for r in _rows(store)}
    bad: list[dict] = []
    for d in want:
        slot = str(d.get("slot") or "")
        row = live.get(slot)
        if row is None:
            bad.append({"kind": "missing_row", "slot": slot,
                        "request_id": str(request_id or ""),
                        "expected": str(d.get("status") or ""), "got": "",
                        "why": "结算决定指向的槽位在盘上读不到 ⇒ 那一笔决定没有落点"})
            continue
        # 状态轴用折算后的 `status`，不用 `judged_state`：后者把"入库了却没写 relevance"
        # 也算 pending，那是"判过没有"那条判据的轴，不是"这一笔结算写没写进去"。
        got = str(fold_legacy(row).get("status") or "")
        exp = str(fold_legacy(dict(d)).get("status") or "")
        if got != exp:
            bad.append({"kind": "status_not_written", "slot": slot,
                        "request_id": str(request_id or ""),
                        "expected": exp, "got": got,
                        "why": ("报告说这一条已经是 " + exp + "，而候选行上读到 " + (got or "（空）")
                                + " ⇒ 那一笔结算没有落到盘上")})
            continue
        if exp == "admitted":
            want_lit = str(d.get("lit_id") or "")
            got_lit = str(row.get("lit_id") or "")
            if want_lit and got_lit != want_lit:
                bad.append({"kind": "lit_id_not_written", "slot": slot,
                            "request_id": str(request_id or ""),
                            "expected": want_lit, "got": got_lit,
                            "why": ("报告说这一条入库成 lit:" + want_lit
                                    + "，而候选行上是 " + (got_lit or "（空）"))})
    for item in bad:
        _note_settlement_mismatch(**item)
    return {"checked": True, "count": len(bad), "rows": bad,
            "reason": "" if not bad else f"{len(bad)} 条结算决定与盘上的行对不上"}


def apply_settlement(tx: Any, decisions: Iterable[Mapping[str, Any]]) -> list[dict]:
    """把一批终态决定写回候选行（`tx` 由调用方给 —— 让它能与登记同处一个事务）。

    `decisions` 的每一项：`{slot, status, lit_id?, reason_code?, note?, overlap_*}`。
    `status` 只认三态（`admitted` / `rejected`，以及"还没判完"的 `pending`）；
    历史档名（`cleared` / `withdrawn`）照收，但落盘前折成 `rejected` +
    受控理由码（`over_cap` / `withdrawn_by_reviewer`）—— 业主 Q16 第 ① 条：
    配额满必须折进 rejected + over_cap，不留第四态。折法用的是 `fold_legacy`
    同一张表（一份判据，两个方向都读它）。

    为什么把它做成"拿 tx 进来"的函数：A 的自动链路（`agent_a.run_once`）里，
    "写 literature 行"与"回填候选行"必须在同一个事务里 —— 否则崩在中间会留下
    "literature 有了、候选还 pending"的一对，下一次迁移会把它当新的再登记一次。
    工具面那一路（`lit.admit` / `lit.admit_all`）的登记路径自带事务，于是它自己开
    一个只写 `lit_candidates` 的事务调这里（同样是一个原子步）。

    两个 `continue` 分支（槽位读不到 / 状态码不认）行为不变、仍然丢掉那一笔，
    但现在会各记一条读数（`dropped_slot` / `dropped_status`）：这一笔决定没落盘
    这件事从此有据可查（见 :func:`settlement_readings`）。
    """
    rows = {str(r.get("slot") or ""): r for r in tx.rows("lit_candidates")}
    written: list[dict] = []
    for d in decisions:
        slot = str(d.get("slot") or "")
        row = dict(rows.get(slot) or {})
        if not row:
            _note_settlement_mismatch(kind="dropped_slot", slot=slot,
                                      expected=str(d.get("status") or ""), got="",
                                      why="结算决定指向的槽位在表里读不到 ⇒ 这一笔被丢掉")
            continue
        status = str(d.get("status") or "")
        legacy = _LEGACY_CANDIDATE.get(status)
        if legacy is not None:
            # 历史档名：折成 rejected，理由码默认用该档那一个（行上已有受控码则保留）。
            status = legacy[0]
            if not str(d.get("reason_code") or "").strip():
                d = {**d, "reason_code": legacy[1]}
        if status not in CANDIDATE_DECISIONS:
            _note_settlement_mismatch(kind="dropped_status", slot=slot,
                                      expected=str(d.get("status") or ""), got="",
                                      why="结算决定的状态码不认 ⇒ 这一笔被丢掉")
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
            for k in ("new_content", "relevance"):
                if str(d.get(k) or "").strip():
                    row[k] = str(d[k]).strip()
        elif status == "rejected":
            row["reject_reason"] = note or _code_label(code)
        S.LitCandidate(**{k: row[k] for k in row
                          if k in S.LitCandidate.__dataclass_fields__}).validate()
        tx.upsert("lit_candidates", row, note=f"lit.settle:{status}")
        rows[slot] = row
        written.append(row)
    return written


def _decisions_from(plan: Mapping[str, Any], lit_ids: Mapping[str, str],
                    failures: Mapping[str, str]) -> list[dict]:
    """把 `admission_plan` 的结论 + 登记结果翻成 `apply_settlement` 要的决定。

    两个"不落终态"的码必须在这里筛掉，否则会把一次可重试的拒绝写成终态：
    `already_terminal`（这一条早就判过）与 `missing_relevance`（这一条还没写
    "为什么相关" —— 它得留在 pending，等补上证据或判拒）。
    """
    out: list[dict] = []
    for item in plan.get("admitted") or []:
        slot = str(item["slot"])
        lit_id = str(lit_ids.get(slot) or "")
        if lit_id:
            ov = item.get("overlap") or {}
            row = item.get("row") or {}
            out.append({"slot": slot, "status": "admitted", "lit_id": lit_id,
                        "overlap_score": ov.get("overlap_score"),
                        "overlap_kind": ov.get("overlap_kind"),
                        "overlap_with": ov.get("overlap_with"),
                        "relevance": str(row.get("relevance") or ""),
                        "new_content": item.get("new_content")})
        else:
            out.append({"slot": slot, "status": "rejected", "reason_code": "registration_failed",
                        "note": failures.get(slot) or "登记路径没有给出 lit_id"})
    for r in plan.get("refused") or []:
        if str(r.get("code")) in ("already_terminal", "missing_relevance"):
            continue
        out.append({"slot": str(r["slot"]), "status": "rejected",
                    "reason_code": str(r.get("code") or ""), "note": str(r.get("why") or "")})
    for c in plan.get("cleared") or []:
        # 配额满那一档：落 rejected + over_cap（Q16 第 ① 条），不再写 `cleared`。
        # plan 里那个键名沿用 `cleared`（冻结声明里就是它），但它的含义是
        # "这一批没进去的那几条"。
        out.append({"slot": str(c["slot"]), "status": "rejected",
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
        # 结算"之后"回读一次（必须在事务外：事务内比等于自己跟自己比），
        # 对不上的记进 `settlement_readings()`。行为不变，只多一条读数。
        settlement_mismatch(store, decisions, request_id=plan["request_id"])
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
    """一键迁移 / 提交整批（业主 2026-10-20 第 2 条 + 2026-10-26 Q16 第 ③ 条的提交闸）。

    ## 提交闸先跑（Q16）：本委托还有一条没判 ⇒ 整批一条都不许入库

    `require_judged=True` 的那一笔判据在 `admission_plan` 里，拒信逐条点名
    （`槽位 + 题名前 40 字`）并给做法。所以"无脑一键迁移"这条路没有了：
    逐条判（`lit.admit` 用带 relevance 的那几条 / `lit.stage_reject` 判拒）
    是唯一的入库方式，`lit.admit_all` 是"判完之后收口 + 写报告"。

    ## 闸过了之后它做三件事，顺序不能换

    1. 取本委托还没判的行（槽位顺序），过 `admission_plan(on_over_cap="truncate")`：
       DOI 重复 / 高重叠无 `new_content` / `overlap_ok=False` 的逐条拒收；
       超配额的落 `rejected(over_cap)`（不再是第四态 `cleared`）；
    2. 通过的那些走现有登记路径（`registrar`）落 literature；
    3. 结算本委托：成功的落 `admitted`、被拒的落 `rejected(理由码)`、其余落
       `rejected(over_cap / not_screened)` —— 于是"迁移后 `stage_list(本委托)`
       没有 `pending` 残留"，下一次委托也看不到本委托的行（`request_id` 已经换了）；
    4. 写委托报告（`reports/lit-<request_id>.md`）：已入库 / 未入库 / 待裁三块。

    "不许物理删"是结构性的：本函数只改 `status` 与那几格证据，一次 `delete` 都没有。
    """
    if store is None:
        raise LitStageError("未配置 store：入不了库（不是「都重复了」）", kind="no_store")
    rid = _resolve_request(store, request_id)
    rows = [fold_legacy(r) for r in _rows(store)
            if str(r.get("request_id") or "") == rid]
    pending_slots = [str(r.get("slot")) for r in sorted(rows, key=lambda r: str(r.get("slot") or ""))
                     if judged_state(r) == "pending"]
    # 提交闸跑在这两处之前：即使一条 pending 都没有也要跑 —— 否则"已经判完"
    # 与"还没判完但一行 pending 都不剩（入库了却没有 relevance）"在盘上同形，
    # 而后者正是真机那 33 条的形状。
    plan = admission_plan(store, request_id=rid, slots=pending_slots, new_content=new_content,
                          cap=cap, on_over_cap="truncate", require_judged=True)
    if not plan.get("ok"):
        return {**plan, "admitted": [], "registered": 0, "report": None, "report_path": None}
    if not pending_slots:
        rep = write_report(store, rid, rows=rows) if write_report_file else None
        return {
            "ok": True, "kind": "", "whole_call_refused": False,
            "reason": "本委托没有待判的行（三态都落定了）",
            "request_id": rid, "call_size": 0, "call_limit": plan["call_limit"],
            "delegation_admitted": _decision_counts(rows)["admitted"],
            "delegation_limit": MAX_ADMIT_PER_DELEGATION,
            "admitted": [], "refused": [], "cleared": [], "registered": 0,
            "report": rep, "report_path": (rep or {}).get("path"),
        }

    lit_ids, failures, got_all = _register(plan, registrar)
    decisions = _decisions_from(plan, lit_ids, failures)
    with store.tx("lit_candidates", actor=actor, note="lit.admit_all") as tx:
        apply_settlement(tx, decisions)
        # 结算之后再扫一遍：任何还停在本委托 pending 上的行都落 rejected +
        # `not_screened`（不再是第四态 `cleared`），这样"迁移后本委托没有 pending"
        # 是一条结构性事实，而不是"我们相信它没有"。
        leftover = [dict(r) for r in tx.rows("lit_candidates")
                    if str(r.get("request_id") or "") == rid
                    and judged_state(r) == "pending"]
        if leftover:
            apply_settlement(tx, [
                {"slot": str(r["slot"]), "status": "rejected", "reason_code": "not_screened",
                 "note": "一键迁移结算时仍未判完，随本次委托一并判拒（行保留、可追）"}
                for r in leftover
            ])
        settled = [dict(r) for r in tx.rows("lit_candidates")
                   if str(r.get("request_id") or "") == rid]
    # 结算之后回读一次（事务外）：对不上的记进 `settlement_readings()`。
    # 只核对第一次结算那一批（`decisions`）—— 收尾那一批（`leftover` ⇒ rejected）
    # 本来就是"扫到哪算哪"，核它没有信息量。
    settlement_mismatch(store, decisions, request_id=rid)
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
    """委托报告正文：三块都必须有（业主 2026-10-26 Q16 加第三块「待裁」）。

    - `## 已入库`：每篇的 `lit_id` / 标题 / 年份 / DOI（或 provider）+ 一句"为什么与本次
      检索相关"（`relevance`，没写就退回 `new_content`，再没有就写明"未写"）；
    - `## 未入库`：每篇的槽位 / 标题 / 受控理由码（`schema.CANDIDATE_REASON_CODES`）
      + 一行散文（拒收 / 重叠度高无新内容 / 超配额 …）。历史档（`cleared` /
      `withdrawn`）在这里按折算后的 `rejected` 出现；
    - `## 待裁`：还没判的每一条（`undecided`）—— 这一块是 Q16 的要害：没有它，
      "A 还没读的那几条"在报告上与"根本没检索到"同形，而它们下一步的动作完全不同。

    三块即使没有行也各留一行 `（无）`：否则"这一块是空的"与"这一块被忘了写"在
    报告上同形，而判据要问的正是"三块都在不在"。

    一条"入库了却没写 relevance"的历史行会同时出现在前两块之外的第二块（待裁）与
    第一块（已入库）里：已入库说它在库里，待裁说它没有判过的证据 —— 那不是重复
    计数，是两个不同的问题（Q16 的提交闸读的正是后者）。
    """
    stamp = generated_at or S.now_iso()
    folded = [fold_legacy(r) for r in rows]
    admitted = [r for r in folded if str(r.get("status")) == "admitted"]
    other = [r for r in folded if str(r.get("status")) == "rejected"]
    waiting = undecided(rows)
    counts = _decision_counts(rows)
    # 已入库的篇数按去重后的 lit_id 计数，不是按行数：两条候选行都可能判重命中
    # 同一个 literature 行（`source_request_ids` 累积到同一行），按行数报
    # "已入库 2 篇"而库里只多了一篇，那是假读数。lit_id 才是"库里多了几篇"的单位。
    admitted_ids = sorted({str(r.get("lit_id") or "") for r in admitted} - {""})
    lines: list[str] = [
        f"# 文献检索委托 {request_id} 的入库报告",
        "",
        f"- 委托：`{request_id}`",
        f"- 生成时间：{stamp}",
        # 盘点只数三态（历史的 cleared / withdrawn 已经折进 rejected）：
        # 报五个格的计数会把"盘上有第四态"这件事重新写回报告里。
        "- 盘点：" + "、".join(f"{s}={counts[s]}" for s in CANDIDATE_DECISIONS)
        + "（三态；历史的 cleared 折进 rejected+over_cap、withdrawn 折进 "
          "rejected+withdrawn_by_reviewer）",
        "",
        f"## 已入库（{len(admitted_ids)} 篇）",
        "",
    ]
    if not admitted:
        lines.append("（无）")
    missing_relevance: list[str] = []
    for r in admitted:
        doi = r.get("doi") or f"provider={r.get('provider') or '?'}"
        lit_id = str(r.get("lit_id") or "?")
        lines.append(f"- `lit:{r.get('lit_id')}` 《{r.get('title')}》"
                     f"（{r.get('year') if r.get('year') is not None else '年份不详'}）"
                     f" {doi}")
        why = str(r.get("relevance") or r.get("new_content") or "").strip()
        if why:
            lines.append(f"  相关性：{why}")
        else:
            # 兜底不许是一句"谁都对得上"的话（改前是「A 未写相关性说明」）：
            # 那样读者看不出缺的是哪几条，也没法回头去要那一句。
            lines.append(f"  相关性：未写（缺的是 `lit:{lit_id}` 这一条的 "
                         "relevance / new_content）")
            missing_relevance.append(lit_id)
    if missing_relevance:
        # 一行点名缺哪几条（同时是 `report_violations` 的机器读数入口：
        # 已入库的行全缺相关性说明时它记一条 violation，同时 `## 待裁` 块会把
        # 这几条逐条列出来 —— Q16 之后它们不再只是读数，而是提交闸不放行的原因）。
        lines.append("- 缺相关性说明的条目（" + str(len(missing_relevance)) + " 篇）："
                     + "、".join(f"`lit:{lit_id}`" for lit_id in missing_relevance)
                     + " —— 这几条在 `## 待裁` 块里，判完（补 relevance 或判拒）才放行")
    lines += ["", f"## 未入库（{len(other)} 篇）", ""]
    if not other:
        lines.append("（无）")
    # 同一篇的另一槽位（G9 修法 ②）：只标注，不删行、不改这一块的篇数 ——
    # 删掉会让"库里明明有"与"报告说没入库"的差异看不见；改篇数就是读侧悄悄少算一篇。
    admitted_ident: dict[str, str] = {}
    for r in admitted:
        admitted_ident.setdefault(
            candidate_identity(r.get("title"), r.get("doi")),
            str(r.get("lit_id") or ""))
    for r in other:
        code = str(r.get("reason_code") or "(未登记理由码)")
        detail = (str(r.get("reject_reason") or "").strip()
                  or str(r.get("withdrawn_reason") or "").strip()
                  or str(r.get("clear_reason") or "").strip())
        code_text = S.CANDIDATE_REASON_LABELS.get(code, code)
        twin = admitted_ident.get(candidate_identity(r.get("title"), r.get("doi")), "")
        tail = (f"（同一篇已在 `lit:{twin}` —— 这是它的另一个槽位，属重复登记；条数不因此改）"
                if twin else "")
        lines.append(f"- 槽位 {r.get('slot')} 《{r.get('title')}》 — 理由：{code}"
                     f"（{code_text}）" + (f"；{detail}" if detail else "") + tail)
    lines += ["", f"## 待裁（{len(waiting)} 条）", ""]
    if not waiting:
        lines.append("（无）")
    for item in waiting:
        lines.append(f"- 槽位 {item['slot']} "
                     f"《{T.clip(str(item.get('title') or ''), UNDECIDED_TITLE_CHARS)}》"
                     f" — {item['why']}")
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
    # 与报告标题同一口径：去重后的 lit_id（两条候选命中同一行时只算一篇）。
    counts = _decision_counts(body_rows)
    admitted = len({str(r.get("lit_id") or "") for r in body_rows
                    if judged_state(r) == "admitted"} - {""})
    return {
        "path": path.as_posix(),
        "rel_path": f"{REPORT_DIR}/{path.name}",
        "chars": len(text),
        "admitted": admitted,
        "not_admitted": counts["rejected"],
        "undecided": counts["pending"],
        "request_id": rid,
    }


def report_violations(text: str) -> list[str]:
    """委托报告的判据：三块都在、都非空、未入库的理由都是受控取值。

    第三块（`## 待裁`）是 2026-10-26 Q16 加的：没有它，"A 还没判的那几条"
    在报告上只剩"未入库 0 篇"这一句 —— 而那与"这一批什么都没检索到"同形。

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
    for name in ("已入库", "未入库", "待裁"):
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
    bad.extend(_relevance_violations(admitted_text))
    return bad


#: 报告「已入库」一块里一条条目的开头形态：`- `lit:000000` 《题名》…`。
#:
#: 判据要按条目读回紧跟其后的那行 `相关性：`，就必须能认出"新条目从这里开始"。
#: 不用"所有以 `- ` 开头的行"：缺相关性时报告里还有一行汇总条目
#: （`- 缺相关性说明的条目（N 篇）：…`），它也以 `- ` 开头。
_REPORT_ADMITTED_ROW = re.compile(r"^-\s*`lit:([^`]+)`\s*《")


def _relevance_violations(admitted_text: str) -> list[str]:
    """已入库的条目 relevance 全空 ⇒ 一条违规读数（只记读数，不拦门）。

    为什么要这一档：`relevance` 是业主 2026-10-20 口径里"它为什么与本次检索
    相关"的那一句，报告「已入库」一块要用它；而 A 的自动链路暂存候选时一次
    都没带过 relevance，于是这一格永远空着 —— 报告照常写出，没有任何一处会
    因此变红，那一句就永远缺着。

    它只进 `report_violations` 的返回值，不改变任何一档的放行/拒绝：
    派生的报告、已入库的文献、委托的终局都与它无关。全部条目都有说明时
    不报；只有一部分缺时不报（那一档由报告正文逐条点名）。
    """
    entries: list[str] = []
    missing: list[str] = []
    current = ""
    for raw in str(admitted_text or "").splitlines():
        line = raw.strip()
        hit = _REPORT_ADMITTED_ROW.match(line)
        if hit:
            current = hit.group(1)
            entries.append(current)
            continue
        if current and line.startswith("相关性：") and "未写" in line:
            missing.append(current)
    if entries and len(missing) == len(entries):
        return [
            f"已入库 {len(entries)} 篇的 relevance 全空（A 没写「为什么与本次检索相关」）；"
            "这一条只记读数，不拦门"
        ]
    return []

"""「待新增文献列表」的实现核心：按委托暂存 → 审 → 一键迁移 → 报告。

这一层与 `tools/search_tools.py` 的分工，照本仓的老规矩（`dedup.py` / `secretary.py`
都是这个形状）：

- 本模块是判据的真身：条数上限（`MAX_ADMIT_PER_CALL` / `MAX_ADMIT_PER_DELEGATION`）、
  重叠口径（`OVERLAP_HIGH_JACCARD` / `OVERLAP_KINDS`）、状态机
  （`schema.CANDIDATE_STATUSES`）、筛选理由的受控词表（`schema.CANDIDATE_REASON_CODES`）、
  报告的两块结构（`report_markdown` / `report_violations`）只有这一处实现；
- 工具层是模型的手：把本模块的结论翻成 `ToolResult`（`fail(kind=...)` 给模型看），
  不重新判一遍。两份判据必然漂，而漂的形态是"工具说拒了、实现却写进去了"。

## 列表的生命周期 = 一次查询委托（2026-11-16 Q1：判收不注册、提交才注册）

待新增列表不是全局常驻的：一行候选属于某一次委托（`request_id`，形如 `r-000001`，
就是 `search_requests` 里那一行）。于是：

- 新委托开始时，`stage_list` 的默认视图只看得到本委托的行（`current_request_id`）；
- 旧委托的行不参与本次筛选（查历史要显式给 `request_id`）；
- 判收 ≠ 注册（业主口径）：`lit.admit` 只把这一条判成 `qualified`（有入库资格、
  还没注册、没有号）；正式文献号由 `admit_all` 在"提交"那一刻批量注册并回填。
  三态（待裁 / 通过 / 拒）不变：`qualified` 是"通过"在注册之前的那一格，
  `judged_state` 把它读成"判过（判定是入库）"，所以提交闸不会把它当待裁。
- 提交（`admit_all`）分两个渲染时刻：先落 无号快照
  `reports/lit-<rid>.submitted.md`（"交报告"那一刻的原件，入库组不带号），
  再批量注册、把 `lit_id` 回填到同一行，最后重渲染 带号定稿
  `reports/lit-<rid>.md`。回填不是字符串替换：`report_markdown` 是纯函数，
  注册之后再渲染一次即可（见 `write_report`）。
- 清表 = 给本委托的每一行打 `cleared_at` + `clear_reason`（不物理删：
  审计要留），同时把整份行落归档 `data/lit_candidates/archive-<rid>.jsonl`。
  清表之后本委托不可再生成报告（受控拒 `already_settled`）；
  `current_request_id` 在表为空时回落到归档里最新的一份（槽位号最大那一行消失时不至于
  "说不清这是哪一次委托"）。

## 为什么"入库"不在本模块里写 literature 行

入库走现有的 literature 登记路径（别绕开它）。
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
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import dedup as D
from . import identity as IDENT
from . import litavail as LAV
from . import litread as LR
from . import schema as S
from . import textutil as T
from .store import Store, lease_expired, make_lease

__all__ = [
    "CANDIDATE_DECISIONS",
    "CANDIDATE_RECORDS",
    "MAX_ADMIT_PER_CALL",
    "MAX_ADMIT_PER_DELEGATION",
    "OVERLAP_HIGH_JACCARD",
    "QUALIFIED",
    "REPORT_DIR",
    "REPORT_SNAPSHOT_SUFFIX",
    "UNDECIDED_TITLE_CHARS",
    "LitStageError",
    "candidate_identity",
    "cleared_of",
    "current_request_id",
    "fold_legacy",
    "is_settled",
    "judged_state",
    "latest_archived_request",
    "note_readback",
    "readback_receipt",
    "undecided",
    "undecided_reason",
    "submission_slots",
    "title_terms",
    "title_jaccard",
    "overlap_check",
    "stage_entries",
    "list_candidates",
    "withdraw",
    "reject",
    "admission_plan",
    "apply_settlement",
    "apply_qualification",
    "decisions_from_plan",
    "admit",
    "admit_all",
    "report_markdown",
    "report_path",
    "report_snapshot_path",
    "write_report",
    "report_violations",
    "archive_path",
    "archived_request_ids",
    "clear_delegation",
]

#: 一次 `lit.admit` 调用最多入库几篇（单次调用上限）。
#:
#: 为什么是"每次调用"而不是"每次检索"：A 可以分批入库（先入 6 篇、再入 4 篇），
#: 而"一次检索至多 10 篇"那一条由 `MAX_ADMIT_PER_DELEGATION` 守 —— 两个上限管两件
#: 不同的事，合成一个会让"分两批把 20 篇都塞进去"变成合法。
MAX_ADMIT_PER_CALL: int = 10

#: 同一个委托（`request_id` = 一次检索委托）累计入库上限。
#:
#: 它与 `MAX_ADMIT_PER_CALL` 都必需：只有每次调用的上限 ⇒ 分几批就能突破；
#: 只有委托上限 ⇒ 一次调用 100 篇也照样过。两条一起才等于"一次文献检索至多入库 10 篇"。
MAX_ADMIT_PER_DELEGATION: int = 10

#: 标题词集 Jaccard 的"重叠度高"阈值（自定但必须写在这里）。
#:
#: 0.60 的依据（不是拍脑袋）：同一篇文献的两种写法（预印本 vs 正式版、带/不带副标题）
#: 同一篇论文的标题变体 Jaccard 通常很高；而同一领域的不同论文（共享 "abelian group" 这类
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
#: 为什么是文件而不是只放在工具返回值里（这是交付物）：
#: 下一次委托的 D/H 要用它 —— 而"D/H 读一个工具调用的返回值"这件事在结构上做不到
#: （它们是另外的角色、另外的循环）。写在 `reports/` 下之后，任何带 `fs.read` 的角色
#: 都读得到，它也就成了台账之外唯一一份"这次检索进了哪几篇、挡了哪几篇与为什么"的证据。
REPORT_DIR: str = "reports"

#: 「交报告」那一刻的无号快照：`reports/lit-<request_id>.submitted.md`。
#:
#: 为什么要有两份而不是一份 + 字符串替换：`report_markdown` 是纯函数（行进去、文本出来），
#: 所以"回填"= 注册之后再渲染一次。快照留档给出"回填前后同事实、只差号"这条判据的对照物
#: （见 `tests/test_lit_submit_registers_only_at_submit.py`）；替换占位符那条路会多出
#: "占位符被题名注入"与"盘中短暂存在脏报告"两个坑。
REPORT_SNAPSHOT_SUFFIX: str = ".submitted.md"

#: 「清表」那一刻写进行上的理由（`clear_reason`）：它说明清的是哪一次动作，
#: 而不是"这一行从来没被处理过"（后者正是 `cleared` 历史档的语义，已退场）。
CLEAR_REASON: str = ("本委托已交报告并批量注册：清表（行保留、不物理删；"
                     "原件与映射在 data/lit_candidates/archive-<request_id>.jsonl）")

#: 「待新增文献列表」现行的决策词表：三态（
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
#:
#: 2026-11-16（Q1）：`qualified` 不是第四态，它是"通过"在注册之前的那一格 ——
#: 业主口径「判收不注册、提交时才注册」把"判过"与"进库"拆成了两步，而报告与提交闸问的是
#: "判过没有"。所以：
#:   · `judged_state(qualified) == "admitted"`（判定是入库，只是还没号）；
#:   · 盘上的行状态多一个取值 `QUALIFIED`（`schema.CANDIDATE_STATUSES` 由 FC-27 补丁加），
#:     但决策词表仍是三档（一个轴：这一条判过没有，判成什么）；
#:   · `CANDIDATE_RECORDS` 是"盘上这一行现在长哪一档"的四档写法（报告盘点用它）。
CANDIDATE_DECISIONS: tuple[str, ...] = ("pending", "admitted", "rejected")

#: 判收但还没注册的那一格（业主口径：有入库资格、无号）。
#:
#: 它必须有自己的一格，不能借 `pending`：`pending` 喂给提交闸会变成"还没判"（永远提交不了），
#: 借 `admitted` 会违反"`admitted` 必带 lit_id"的不变量（那一格是"已注册"）。
QUALIFIED: str = "qualified"

#: 盘上这一行的四档（报告"盘点"那一行用它，与 `CANDIDATE_DECISIONS` 的差一格就是 `qualified`）。
CANDIDATE_RECORDS: tuple[str, ...] = ("pending", QUALIFIED, "admitted", "rejected")

#: 历史档 ⇒ `(折成哪一态, 默认理由码, 事实在哪个字段里)`：读侧折算的唯一实现。
#:
#: `over_cap` 这一条点名的：「`cleared`（配额满）必须折进
#: rejected + reason_code=over_cap，不留第四态」。`withdrawn` 走同一台机器：
#: 「撤掉」与「拒收」的差别从此落在受控理由码上（`withdrawn_by_reviewer`），
#: 不再多占一个状态格 —— 状态格只有一个轴：这一条判过没有。
_LEGACY_CANDIDATE: dict[str, tuple[str, str, str]] = {
    "cleared": ("rejected", "over_cap", "clear_reason"),
    "withdrawn": ("rejected", "withdrawn_by_reviewer", "withdrawn_reason"),
}

#: 提交闸拒信里题名截前多少字（`<slot + 标题前 40 字>`）。
UNDECIDED_TITLE_CHARS: int = 40


def cand_ref(slot: Any) -> str:
    """临时文献号的唯一构造点：`cand:<槽位>`（例如 `cand:000029`）。

    为什么是它、而且只在这里拼：
    - 裸六位数字就是正式号的形状（`slot 000000–000045` 与 `lit_id 000000–000011`
      在真机上直接重合）⇒ 临时号必须是形式上当不成正式号的东西。`cand:` 含冒号，
      `schema.is_valid_id` 拒收；报告里"已入库"的正则 `` `lit:`` 也吃不掉它。
    - 它由 `slot` 派生，不落字段：给 `lit_candidates` 加一列 = 改 schema（FC-27）。
    - 解析点仍在 `text_tools._CANDIDATE_PREFIXES`（`cand:` / `candidate:` / `slot:`），
      本函数只管写出来的那一种形态；各处不许再手拼。
    - 作废时刻 = 清表：清表之后 `cand:<slot>` 解析不到行（`unknown_slot`），
      "临时"因此有判据、可观察。
    """
    text = str(slot or "").strip()
    return f"cand:{text}" if text else ""


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

    判据（「A 确实逐篇决定过」）落在三档上（注意：它证明的是"决定过"，不是"读过"
    —— "读过"是另一道闸 `_read_evidence_gate`，证据是抽读回执 + `fs.read` 观察台账）：

    - `rejected` ⇒ 判过。拒收本身就是决定，不论是人判的（`rejected_off_topic` …）
      还是确定性判据判的（`over_cap` / `not_screened`）—— 后两者由机器做，A 不需要读；
    - `admitted` 且 `relevance` 非空 ⇒ 决定过。那一句「为什么与本次检索相关」是
      "我为这一篇写过判词"的证据（`schema.LitCandidate.relevance` 的口径原本就是它）；
      它不是"读过"的证据：AH6 的 12 条就是同一秒整批写下的。
    - `qualified`（2026-11-16 Q1）且 `relevance` 非空 ⇒ 决定过，判定是入库
      （有资格、还没注册）。这一格与 `admitted` 在这条判据上同值：它问的是
      "判过没有"，不是"进库没有" —— 进库读 `status == "admitted"`（报告分块、
      文献库面 `webui/readers._library_admission` 都读那一格）。
    - `admitted` 但 `relevance` 空 ⇒ 没决定过。这是本判据最要紧的一格：入库了却
      写不出为什么相关的行，没有任何"决定过"的证据 —— 现场那 33 条
      正是这个形状（同一秒整批入库、`relevance` 48/48 全空）。它不改入库判据
      （`webui/readers._library_admission` 照旧只读 `status == "admitted"`）：
      文献库面问「这一篇在不在库里」，提交闸问「A 判过没有」，两个问题。
    - 其余（`pending`、以及认不出的状态）⇒ 没判过。"认不出"不许折成"判过"。
    """
    folded = fold_legacy(row)
    status = str(folded.get("status") or "")
    if status in ("admitted", QUALIFIED):
        return "admitted" if str(folded.get("relevance") or "").strip() else "pending"
    if status in ("pending", "rejected"):
        return status
    return "pending"


def _pending_why(row: Mapping[str, Any]) -> tuple[str, str]:
    """一条"还没判完"的行：`(盘上的 status, 为什么还停着)`（两种写法的唯一来源）。

    调用点有两个：提交闸的读数（`undecided`）与报告正文的待裁块。后者刻意不调
    `undecided`：那一格是闸的读数，打桩它（反真空的做法）不该让报告也一起说谎
    —— 报告自己按 `judged_state` 数，才是"闸与报告各钉一头"。
    """
    folded = fold_legacy(row)
    status = str(folded.get("status") or "")
    if status == QUALIFIED:
        why = ("这一条判了收（有入库资格）却没有 relevance —— 判过的证据就是那一句，"
               "补进原槽（lit.stage_add 带 relevance 重进同一篇）或改用 "
               "lit.stage_reject 判拒；它还没有正式文献号（提交时才发）")
    elif str(folded.get("lit_id") or "").strip():
        why = ("这一条还没有 relevance（没写「为什么与本次检索相关」），"
               "而它已经挂着 lit_id —— 入库发生了、读过的证据不在，按没判算")
    else:
        why = "这一条还停在 pending（没判过）"
    return status, why


def undecided(rows: Sequence[Mapping[str, Any]]) -> list[dict]:
    """还没判的那些条：`[{slot, title, status, why}]`（提交闸唯一的读数来源）。

    `why` 区分两档，因为做法不同：待裁的 `pending` 要一轮判；"入库了但没有
    relevance"的那一档要补那一句（或判拒），它不是"还没开始"。
    """
    waiting: list[dict] = []
    for row in rows:
        if judged_state(row) != "pending":
            continue
        status, why = _pending_why(row)
        waiting.append({"slot": str(row.get("slot") or ""),
                        "title": str(row.get("title") or ""),
                        "status": status,
                        "why": why})
    waiting.sort(key=lambda item: item["slot"])
    return waiting


def _decision_counts(rows: Sequence[Mapping[str, Any]]) -> dict:
    """按三态数一遍（`{"pending": n, "admitted": n, "rejected": n}`，键恒在这三个）。

    它是拒信与报告里"数没全更新为入库和拒收"那句话的读数来源：提交闸的判据
    问的就是这个数（`pending` 必须是 0）。
    """
    counts = {s: 0 for s in CANDIDATE_DECISIONS}
    for row in rows:
        counts[judged_state(row)] += 1
    return counts


def submission_slots(scoped: Sequence[Mapping[str, Any]],
                     slots: Sequence[str] | None = None) -> list[str]:
    """这一次提交覆盖哪些槽（按批提交的唯一作用域实现）：点名就看点名的，不点名 = 已判定的全部。

    为什么"不点名"的默认必须是「已判定的全部」、而不是「整委托」：15 槽里判完 5 槽时，
    A 必须能只提交这 5 槽（其余 10 槽保持 pending、进下一批）。要求整委托 15 槽全判
    才能交，等于把"判完"的粒度绑死在委托上 —— 真机 `projects/lp-ball-4` 的 7 个委托
    105 槽因此一条都交不了（A 的 final 逐字：「对 105 个槽逐条花调用的预算」不够）。

    点名时允许点到未判的槽：这一层不做判断，闸（`_judged_gate`）会逐条点名拒
    （`undecided_items`）—— "这一批内全判"是硬要求，不由调用方口头保证。
    """
    if slots is not None:
        wanted: list[str] = []
        for raw in slots:
            s = str(raw or "").strip()
            if s and s not in wanted:
                wanted.append(s)
        return wanted
    return [str(r.get("slot") or "") for r in
            sorted(scoped, key=lambda r: str(r.get("slot") or ""))
            if judged_state(r) != "pending"]


def undecided_reason(waiting: Sequence[Mapping[str, Any]],
                     request_id: str = "") -> str:
    """提交闸的拒信原文：逐条点名 + 做法。

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
        "判拒的带受控 reason_code；标 `readable` 的还要有抽读回执 + `fs.read`，"
        "见 `text.extract(lit_id=\"cand:<槽位>\")`）才能提交。"
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


# --------------------------------------------------------------------------- 回读回执


#: 「A 回读过自己刚写的清单」的回执（落盘，按 `(实例, 委托号)` 分开；K16 / AL-06）。
#:
#: ## 为什么要有这一格（业主 2026-11-16 裁定 9 / 15）
#:
#: 业主原话「是 A 侧原来就有的待录入文献列表的逐个自审没做好」。AH6 实测：A1 整趟
#: 0 次 `lit.stage_list` —— 它从未回读自己刚写进列表的那 46 条，却在 07:31:29
#: 一次性批量写下 12 条 relevance、07:32:41 一次 `lit.admit` 10 条通过。提交闸"跑了"，
#: 但它审的证据（relevance）本身就是批量造的，于是闸挡不住"没逐条看过"。
#:
#: 所以回读从"建议"变成"提交前的前置条件"：`lit.stage_list` 记回执，`admission_plan`
#: 的提交路径（`require_readback=True`）验回执覆盖了要提交的每一个槽位；没有就受控拒
#: （`no_readback`，逐条点名缺哪几个槽），而不是留一条没人读的读数。
#:
#: 为什么选"受控拒"而不是"读数点名"：读数不挡路。现场已经证明"闸跑了"这句话可以与
#: "A 根本没读"同时成立 —— 再留一条能被忽略的读数，等于把同一个失败再演一遍。
#:
#: ## 为什么从进程内改成落盘（K16，2026-11-19）
#:
#: 改前是 `_READBACKS[(root, request_id)]` 一个进程内字典：重启就没了（fail-closed 只
#: 多读一次，可接受），但它还少一根轴 —— `request_id` 是委托号，不是实例号：
#: 两个 A 实例对同一委托交错 stage / submit 时，A1 的回执会被 A2 的 `stage_add` 删掉，
#: A1 提交时被拒 `no_readback`，而那是别人造成的拒（AL-06 缺的读数就是这个交错的形态）。
#: 现在回执落在 `<工作区>/data/lit_readbacks.jsonl`（零 schema：它是文件，不是表），
#: 一行一条 `{request_id, instance, actor, slots, count, at}`，键是 `(instance, request_id)`：
#: 另一个进程 / 重启之后都读得到（AL-06 的 d 条），而另一个实例的 stage 改动只作废
#: 它自己的回执。
#:
#: 为什么 `lit.stage_list` 的副作用声明仍是 `read` 而这里要写盘：回执不是"列表被改了"
#: 这件事的副作用，它是"这一趟读过"的凭据；写的是旁路台账（与 `data/lit_availability.jsonl`
#: / `data/lit_reads.jsonl` 同一层），不动任何受 schema 管的表。改前"进程内足够"的
#: 前提是"回执只服务同一进程里的下一次提交"，而 AL-06 的现场正是这个前提不成立。
READBACK_LEDGER_NAME = "lit_readbacks.jsonl"


def readback_ledger_path(root: str | Path) -> Path:
    """回执台账的落点：`<工作区>/data/lit_readbacks.jsonl`（只算路径）。"""
    return Path(str(root)) / "data" / READBACK_LEDGER_NAME


def _readback_actor() -> tuple[str, str]:
    """这一次回读是谁：`(实例标签, actor 名)`（实例读不到 ⇒ 空串，不编一个）。"""
    instance = str(IDENT.current_instance() or "").strip()
    return instance, IDENT.actor_for("A", instance)


def _append_readback(store: Store, rec: Mapping[str, Any]) -> None:
    """追加一行回执（写不进去就受控抛：'没记上'不许读成'读过了'）。"""
    path = readback_ledger_path(store.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(rec), ensure_ascii=False, sort_keys=True, default=str) + "\n"
    with path.open("a", encoding="utf-8", newline="") as fh:
        fh.write(line)


def _readback_lines(store: Store | None) -> list[dict[str, Any]]:
    """回执台账的全部行（坏行跳过：它不构成"这一条读过"的证据）。"""
    path = readback_ledger_path(store.root) if store is not None else None
    if path is None or not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        try:
            got = json.loads(raw)
        except ValueError:
            continue                    # 坏行不算回执（读不出来 ≠ 读过了）
        if isinstance(got, dict):
            out.append(got)
    return out


def note_readback(store: Store | None, request_id: str,
                  rows: Sequence[Mapping[str, Any]]) -> dict:
    """记一条回执：这个实例刚刚用 `lit.stage_list` 读过这一次委托的清单。

    只认具体委托（`request_id=""` / `"*"` 不记）：全查那一次的视图不回答"这一批
    回读过没有"。回执记的是槽位集合，不是状态 —— 判完之后状态会变，槽位集合
    不变；所以"回读 → 逐条判 → 提交"这条正路的回执一直有效，而中途再 `stage_add`
    会把它作废（见 :func:`stage_entries`）。
    """
    rid = str(request_id or "").strip()
    if store is None or not rid or rid == "*":
        return {}
    instance, actor = _readback_actor()
    slots = sorted({str(r.get("slot") or "") for r in rows if str(r.get("slot") or "")})
    rec = {"request_id": rid, "instance": instance, "actor": actor,
           "slots": slots, "count": len(slots), "at": S.now_iso()}
    try:
        _append_readback(store, rec)
    except OSError:
        # 写不进台账 ⇒ 这一次回读没有凭据；不许在内存里假装记上了（那样另一个进程
        # 看不到、而这个进程的提交闸会放行）。返回空字典 = 这一格没记成。
        return {}
    return dict(rec)


def readback_receipt(store: Store | None, request_id: str) -> dict | None:
    """这个实例对这一次委托的回执（没有 ⇒ `None`；`None` 不是"读过了"）。

    取台账里同一 `(instance, request_id)` 的最后一行：`stage_add` 写的作废
    记录是同一形状的空槽位行（见 :func:`_drop_readback`），读到它就返回 `None`，
    于是"没有回读过"与"回读之后清单又变了"在拒信里仍是两句话。
    """
    rid = str(request_id or "").strip()
    if store is None or not rid:
        return None
    instance, _actor = _readback_actor()
    found: dict | None = None
    for rec in _readback_lines(store):
        if str(rec.get("request_id") or "") != rid:
            continue
        if str(rec.get("instance") or "") != instance:
            continue
        found = rec
    if not found or bool(found.get("invalidated")):
        return None
    return dict(found)


def reset_readbacks() -> None:
    """回执的隔离点（判据的旧入口；今天回执落盘，进程内没有可清的缓存）。

    保留这个名字是因为调用方（判据夹具 / 旧脚本）用它表达"从零开始"：每个判据
    自己一份 `tmp_path` 工作区，落盘回执天然按工作区隔离，所以这里无事可做 ——
    它是"没有进程内账"这件事的读数，而不是一个静默的空操作。
    """


def _drop_readback(store: Store | None, request_id: str) -> None:
    """清单变了 ⇒ 这个实例的旧回执作废（下一次提交前必须重读）。"""
    rid = str(request_id or "").strip()
    if store is None or not rid:
        return
    instance, actor = _readback_actor()
    try:
        _append_readback(store, {"request_id": rid, "instance": instance,
                                 "actor": actor, "slots": [], "count": 0,
                                 "invalidated": True, "at": S.now_iso()})
    except OSError:
        # 作废记不上 ⇒ 旧回执仍然有效（fail-open 到"多信一次旧读数"）。这条退路
        # 只在磁盘写不进去时出现；下一次 `readback_receipt` 仍会给旧槽位集合，
        # 而提交闸按槽位差集判 —— 新增的槽位一定缺回读，所以不会放走没读过的行。
        return


def _readback_reason(request_id: str, missing: Sequence[str], *,
                     has_receipt: bool) -> str:
    """回读闸的拒信：点名缺哪几个槽 + 给做法（不是一句"请先回读"）。"""
    scope = f"本次委托（{request_id}）" if request_id else "本委托"
    if not has_receipt:
        head = (f"{scope}没有回读记录：提交之前，A 必须用 `lit.stage_list` 把**自己刚写进"
                "列表的那一份清单**读回来、逐条过一遍。")
    else:
        head = (f"{scope}回读之后清单又变了（新槽位没被读过）：提交之前要再 "
                "`lit.stage_list` 读一次。")
    slots = "、".join(str(s) for s in missing) or "（全部槽位）"
    return (
        f"{head}这次要提交的槽位里缺回读：{slots} ⇒ **整批不许提交入库**。"
        "做法：`lit.stage_list`（`request_id` 给本次委托）→ 对着返回的每一行做两件事："
        "① 给这一条的可读性判定（readable / metadata_only / extract_failed / unknown，"
        "判收时写进 `lit.admit` 的 items[].availability；标 `readable` 之前必须先用 "
        "`text.extract(path=…, lit_id=\"cand:<槽位>\")` 抽读、再用 `fs.read` 读那份 `.txt`）；"
        "② 判收带 relevance、判拒带受控理由码（`lit.stage_reject` 不收档位，判拒只需理由码"
        "与一句为什么）。回读之后再提交。"
    )


def _availability_reason(request_id: str, bad: Sequence[tuple[str, str]],
                         *, missing: Sequence[str] = ()) -> str:
    """可读性闸的拒信：逐条点名"哪一槽是哪一档、为什么不能入"。

    三档不同的处置必须说清（否则 A 只能整批撤掉重来）：
    - 没有判定 / `unknown`：这一条还没审过可读性 —— 去审（能读到就写 readable /
      metadata_only；抽过但失败写 extract_failed），不要拿"没查"当"可读"；
    - `extract_failed`：抽过但失败 —— 不入库，按受控理由码判拒（`rejected_low_quality`），
      候选行留着、原因写在行上；
    - `metadata_only` 且没有定位符：仅题录可以入，但它必须指得出处（DOI 或 URL）；
      2026-11-16（AR1）起它还必须有一条"试过、拿不到可读文本"的 `extract_failed`
      尝试回执 —— 零读取尝试的仅题录由后面的 `_read_evidence_gate` 按同一档拒。
    """
    scope = f"本次委托（{request_id}）" if request_id else "本委托"
    parts: list[str] = []
    if missing:
        parts.append("还没有可读性判定：" + "、".join(str(s) for s in missing))
    for slot, tier in bad:
        if tier == LAV.EXTRACT_FAILED:
            parts.append(f"{slot} 是 extract_failed（抽过但失败）⇒ 不入库")
        elif tier == LAV.UNKNOWN:
            parts.append(f"{slot} 是 unknown（没查过可读性）⇒ 不入库")
        elif tier == LAV.METADATA_ONLY:
            parts.append(f"{slot} 是 metadata_only 但没有定位符（DOI/URL）⇒ 不入库")
        else:
            parts.append(f"{slot} 的可读性判定 {tier!r} 不成立")
    return (
        f"{scope}的可读性判定过不了入库闸：{'；'.join(parts)} ⇒ **整批不许提交入库**。"
        "口径（业主裁定 ③）：`extract_failed` 与 `unknown` 不许入库；仅题录可以入，"
        "但必须指得出处。做法：抽过但失败的用 `lit.stage_reject`（`reason_code="
        "`rejected_low_quality`，note 写清是乱码/无文本层）—— `lit.stage_reject` **不收**"
        "可读性档位，档位只经 `lit.admit` 的 items[].availability 与抽读回执落盘；"
        "没查的去抽读（`text.extract(path=<全文路径>, lit_id=\"cand:<槽位>\")` 再用 "
        "`fs.read` 读那份 `.txt`），不要用 unknown 交差。"
    )


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
    `title_terms` 调 6000 次。
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
    """一组行里"最近一次暂存"的委托号：槽位号最大那一行的 `request_id`。

    这是"号只增不复用"那个事实的读法，不是"当前委托是谁"的完整答案 —— 后者
    还要问"谁正在做哪一个委托"（见 :func:`_instance_request_ids` 与
    :func:`current_request_id`）。保留这个只吃行的版本，是为了让 `pending_all_delegations`
    这类"手里已经有行、不想再读一遍表"的调用方有一条不重读的实现（判据仍是同一处）。
    """
    if not rows:
        return ""
    newest = max(rows, key=lambda r: str(r.get("slot") or ""))
    return str(newest.get("request_id") or "")


def _instance_request_ids(store: Store | None, instance: str) -> set[str]:
    """这个 A 实例正在做（或在队列里点名做过）的委托号集合（K16 / AL-02）。

    判据只有一处来源：`search_requests` 行上的 `claimed_by` / `submitted_by`
    —— AL-10 已经认定"按实例的领取"是本框架里唯一按实例的 claim（`claimed_by` +
    `lease_until`）。用 `identity.split_actor("A", actor)` 把 actor 拆成实例标签，
    所以 `agent-A-A2` 与 `agent-A-lit` 分得开；`agent-A`（角色级）不归任何实例。

    读不出来 ⇒ 返回空集（不是"所有委托"）：判不了就不回落，交给
    `_resolve_request` 的 `no_delegation` 受控拒 —— 「不知道」不许读成「大家都行」。
    """
    if store is None or not instance:
        return set()
    try:
        rows = store.rows("search_requests")
    except Exception:  # noqa: BLE001 —— 读不出来 = 判不了（空集，不回落）
        return set()
    mine: set[str] = set()
    for row in rows:
        rid = str(row.get("request_id") or "").strip()
        if not rid:
            continue
        for field_name in ("claimed_by", "submitted_by"):
            actor = str(row.get(field_name) or "").strip()
            if not actor:
                continue
            got = IDENT.split_actor("A", actor)
            if str(got.get("instance") or "") == instance:
                mine.add(rid)
                break
    return mine


def _current_request_id(store: Store | None, rows: Sequence[Mapping[str, Any]],
                        *, instance: str | None = None) -> str:
    """当前委托（唯一实现）：有实例标签 ⇒ 只认这个实例的委托；没有 ⇒ 旧口径。

    - 实例标签为空（直调 / 夹具 / 没接身份的那一层）：槽位最大那一行的委托，表空
      再回落归档 —— 改动前逐字同义。
    - 实例标签非空：先问 `search_requests` 这一行归不归它（`_instance_request_ids`），
      再在属于它的那些委托的行里取槽位最大那一行。它没有委托 ⇒ 返回空串，
      不回落到全表最大槽位（那正是 K16 的 c 条：第二个 A 实例读到了第一个的委托）。
    """
    if store is None:
        return ""
    inst = str(IDENT.current_instance() if instance is None else instance or "").strip()
    if not inst:
        return current_request_id_of(rows) or latest_archived_request(store.root)
    mine = _instance_request_ids(store, inst)
    if not mine:
        return ""
    return current_request_id_of(
        [r for r in rows if str(r.get("request_id") or "") in mine])


def current_request_id(store: Store | None) -> str:
    """当前委托（按实例；K16 / AL-02；判据见 :func:`_current_request_id`）。

    改前这里是"槽位号最大那一行所属的 request_id，全表"：两个 A 实例同时跑时，
    第二个实例拿到的永远是第一个实例的委托（谁最后暂存谁说了算）。现在实例标签
    从 `identity.current_instance()` 读（工具调用由 `conductor.calling_as` 挂上），
    委托集合从 `search_requests` 的 `claimed_by` / `submitted_by` 取。

    2026-11-16（Q1）那条回落仍在（实例为空时）：表里一行都没有时读归档里最新的一份，
    让"表空"与"这次委托已收工"分得开。
    """
    return _current_request_id(store, _rows(store) if store is not None else [])


def _resolve_request(store: Store | None, request_id: str | None) -> str:
    rid = str(request_id or "").strip() or current_request_id(store)
    if not rid:
        raise LitStageError(
            "说不清这是哪一次委托（这个实例名下没有正在做的委托，调用方也没给 "
            "request_id）⇒ 没有委托就没有「本次」筛选，不许拿一个空集冒充，"
            "也不许借用别的实例的委托（把 request_id 明确写出来）",
            kind="no_delegation",
        )
    return rid


def pending_all_delegations(rows: Sequence[Mapping[str, Any]], *,
                            current: str | None = None) -> dict:
    """全表待裁行的按委托分组读数（作用域写死成全表，没有"只看当前委托"这一档）。

    ## 为什么它必须是一个独立函数、而且不带委托过滤参数

    VC1 P1-6 的现场（2026-11-17 真机 `projects/lp-ball-3`）：`lit.stage_list` 的默认
    视图与提交闸（`admission_plan` 的 `_judged_gate`）都只取"当前委托"的行 ——
    `current_request_id` 是槽位号最大那一行所属的委托。于是新委托一开始，旧委托的
    `pending` 对这两处就隐身了；而收工闸 `literature_pending` 看的是全表 ⇒ 一个
    "谁也看不见、谁也清不掉"的 blocker（30 条跨两个委托，收口时 A 只被问起当前那份）。

    修法不是给每个调用点各写一遍"取全表"，而是把"全表 + 按委托分组"做成唯一实现：
    调用方拿不到过滤参数，就不存在"某一处悄悄退回当前委托"这条路。要只看当前委托的
    调用方（`lit.stage_list` 的默认视图）先自己 `_scoped_rows` 再 `undecided`，
    作用域在调用点显式可见 —— 这正是本函数不提供过滤参数的理由。

    ## `current`（K16 / AL-02）

    输出里那个 `current` 标志要回答"这一组是不是我这一趟的委托"。改前它在函数内
    用 `current_request_id_of(rows)` 现算（= 全表最大槽位）⇒ 第二个 A 实例的读数会把
    第一个实例的委托标成"当前"。现在按实例算好的那个值由调用点传进来（判据只有
    `_current_request_id` 一处）；不传（旧调用 / 夹具）才退回旧口径。
    """
    groups: dict[str, list[dict]] = {}
    for row in rows:
        if judged_state(row) != "pending":
            continue
        groups.setdefault(str(row.get("request_id") or ""), []).append(dict(row))
    if current is None:
        current = current_request_id_of(rows)
    else:
        current = str(current or "")
    by: list[dict] = []
    for rid in sorted(groups):
        items = sorted(groups[rid], key=lambda r: str(r.get("slot") or ""))
        by.append({
            "request_id": rid,
            "pending": len(items),
            "slots": [str(r.get("slot") or "") for r in items],
            "titles": [T.clip(str(r.get("title") or ""), UNDECIDED_TITLE_CHARS)
                       for r in items],
            "current": rid == current,
        })
    return {"total": sum(int(g["pending"]) for g in by),
            "current_request_id": current, "by_delegation": by}


def pending_scope_note(reading: Mapping[str, Any], *, exclude: str = "") -> str:
    """把"全表待裁按委托分组"写成一句人能照着做的事（提交闸 / 收工闸 / A 都用这一句）。

    `exclude` 用来剔掉"本委托"：提交闸那一处，本委托那几条另有 `undecided_reason`
    逐条点名，这里只补"别的委托上还有多少、谁来清"。剔完为空 ⇒ 返回空串（不硬凑一句）。

    "谁清"必须点到具体入口，否则这句话只是把数字重复一遍：A 的 `run_once`
    （`request_ids` 空 = 认领全部有 pending 的委托）+ 逐条 `lit.admit` /
    `lit.stage_reject` + 逐委托 `lit.admit_all` 提交（批量注册 + 回填 + 清表）。
    """
    groups = [g for g in reading.get("by_delegation") or []
              if str(g.get("request_id") or "") != str(exclude or "")]
    total = sum(int(g.get("pending") or 0) for g in groups)
    if not groups:
        return ""
    parts = "、".join(
        f"{g.get('request_id') or '（无委托号）'} 还剩 {int(g.get('pending') or 0)} 条"
        for g in groups)
    head = (f"全表还有 {total} 条待裁，分布在 {len(groups)} 个委托上"
            f"（跨委托，不只当前那一份）：{parts}。")
    if exclude:
        head = (f"另有 {len(groups)} 个委托上还有 {total} 条待裁：{parts}"
                "（它们不拦这一次提交，但收工闸看全表、会拦）。")
    return head + (
        "谁能清：A 的 `run_once`（`request_ids` 给空就认领全部有 pending 的委托，"
        "也可以逐个点名）→ 逐条 `lit.admit` 判收 / `lit.stage_reject` 判拒 → "
        "再**逐委托** `lit.admit_all` 提交（批量注册 + 回填 + 清表）。"
        "只清当前委托不够：收工闸数的是全表。"
    )


# --------------------------------------------------------------------------- 清表 / 归档


def _archive_dir(root: Any) -> Path:
    """归档目录：`<工作区>/data/lit_candidates/`（与 `data/lit_availability.jsonl` 同族）。"""
    return Path(root) / "data" / "lit_candidates"


def archive_path(store: Store, request_id: str) -> Path:
    """一次委托的整份归档：`data/lit_candidates/archive-<request_id>.jsonl`。

    一委托一文件、JSONL、零 schema（先例 `data/lit_availability.jsonl` / `data/lit_reads.jsonl`）。
    它回答的是"这次委托的每一条候选最后长什么样、其中哪一条变成了哪一篇"——
    报告的未入库组按业主口径没有号、也没有槽位，所以这条链只能靠归档。
    """
    return _archive_dir(store.root) / f"archive-{str(request_id or '').strip()}.jsonl"


def _atomic_write(path: Path, text: str) -> None:
    """整份覆盖写（先 `.tmp` 再 `os.replace`）：崩在中间不留半截文件。

    幂等：同一份行重写一次得到逐字节相同的文件 —— 于是"归档完、还没清表"之间崩掉
    时，重跑覆盖同一份内容，不会重复追加。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def _archive_rows(store: Store, request_id: str,
                  rows: Sequence[Mapping[str, Any]]) -> dict:
    """把本委托的整份行落归档（返回 `{path, rel_path, count}`）。"""
    rid = str(request_id or "").strip()
    ordered = sorted((dict(r) for r in rows), key=lambda r: str(r.get("slot") or ""))
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, default=str) + "\n"
                   for r in ordered)
    path = archive_path(store, rid)
    _atomic_write(path, body)
    return {"path": path.as_posix(),
            "rel_path": f"data/lit_candidates/{path.name}",
            "count": len(ordered)}


def latest_archived_request(root: Any) -> str:
    """归档里最新的一份委托号（没有归档 ⇒ 空串）。

    "最新"按文件 mtime 取，不按号大小：号是六位十进制、跨工作区复制时会重排，
    而 mtime 记的是"哪一份是刚刚写下去的"。
    """
    if root in (None, ""):
        return ""
    folder = _archive_dir(Path(root))
    if not folder.is_dir():
        return ""
    files = [p for p in folder.glob("archive-*.jsonl") if p.is_file()]
    if not files:
        return ""
    newest = max(files, key=lambda p: p.stat().st_mtime_ns)
    rid = newest.stem
    return rid[len("archive-"):] if rid.startswith("archive-") else ""


def archived_request_ids(root: Any) -> list[str]:
    """归档里出现过的全部委托号（升序；没有归档 ⇒ 空表）。

    收工门那一格用它数"这个工作区里已经有几份收过工的委托"（`closed_delegations`）——
    "0 步"与"读不到"因此分得开：空表是读数，读目录抛错由调用方折成 unknown。
    """
    if root in (None, ""):
        return []
    folder = _archive_dir(Path(root))
    if not folder.is_dir():
        return []
    out: list[str] = []
    for p in sorted(folder.glob("archive-*.jsonl")):
        if not p.is_file():
            continue
        rid = p.stem
        out.append(rid[len("archive-"):] if rid.startswith("archive-") else rid)
    return out


def is_settled(store: Store, request_id: str) -> bool:
    """这一次委托是不是已经"整份定稿 + 清表"：本委托的每一行都有 `cleared_at`。

    "已收工"不能靠"表里没有行"判：本实现不物理删，行永远在。FX3·甲 起也不能只看
    "归档在盘上"：一个委托现在可以分多批提交，第一批就会写归档，而那时还有 pending
    的槽（归档是整份委托的快照，本来就含未判行）。所以判据改成"每一行都清过表"——
    这正是 `cleared_of` 的口径，也是收工闸读的那一格（两处同一个事实，不另数一遍）。

    三态：行读不到 ⇒ 这里返回 False（读不到 ≠ 已收工），调用方若要分辨三态请自己读表。
    """
    rid = str(request_id or "").strip()
    if not rid:
        return False
    try:
        rows = [dict(r) for r in store.rows("lit_candidates")
                if str(r.get("request_id") or "") == rid]
    except Exception:  # noqa: BLE001 - 读不到 ≠ 已收工（三态由调用方另判）
        return False
    return cleared_of(rows)


def cleared_of(rows: Sequence[Mapping[str, Any]]) -> bool:
    """这一批行（同一委托）是不是都清过表：全都有 `cleared_at`。

    空列表 ⇒ False（"没有行"不是"清过表"：那可能是这一委托一行都没有，
    或表读坏了 —— 三态纪律，"没有"与"清过了"必须分得开）。
    """
    items = list(rows)
    if not items:
        return False
    return all(str(r.get("cleared_at") or "").strip() for r in items)


def claim_delegation(store: Store, request_id: str, *, actor: str,
                     lease_seconds: int = 900) -> dict:
    """认领一次委托的待裁行：行上写 `claimed_by` / `lease_until` / `claimed_at`（AL-11）。

    返回 `{request_id, state, holder, lease_until, slots, why}`：

    - `state="mine"`：这一笔真的在行上落了认领（`claimed=True`）；
    - `state="other"`：另一个实例的租约还没到期 ⇒ 不写一个字节（`claimed=False`）；
    - `state="mine_again"`：同一个 actor 的租约还在 ⇒ 续写（幂等，不抢别人的）；
    - `state="unknown"`：本委托一行都没有 / 表读坏了 ⇒ 不认领（判不了 ≠ 可以写）。

    为什么要有这一格（K16 / AL-11 的现场）：改前 `_claim_pending` 只写一条
    `lit.claim_pending` 事件 —— 两个 A 实例同时进来时，二者都"认领"同一批委托，
    盘上没有任何互斥。事件是 append-only 的审计面，它答不了"这一批现在归谁"。
    判据只有这一处；租约语义与 `search_requests` 的领取同一套
    （`store.make_lease` / `store.lease_expired`），不另造一份。
    """
    rid = str(request_id or "").strip()
    who = str(actor or "").strip()
    out: dict[str, Any] = {"request_id": rid, "state": "unknown", "holder": "",
                           "lease_until": "", "slots": [], "claimed": False,
                           "why": ""}
    if not rid or not who:
        out["why"] = "没有委托号或没有写者身份 ⇒ 认领无从谈起（不写）"
        return out
    with store.tx("lit_candidates", actor=who, note="a.claim_pending") as tx:
        rows = [dict(r) for r in tx.rows("lit_candidates")
                if str(r.get("request_id") or "") == rid
                and not str(r.get("cleared_at") or "").strip()]
        out["slots"] = [str(r.get("slot") or "") for r in rows]
        if not rows:
            out["why"] = "这一次委托没有待裁行（已判完或已清表）⇒ 没有可认领的东西"
            return out
        holders = {str(r.get("claimed_by") or "").strip() for r in rows}
        live = {str(r.get("lease_until") or "") for r in rows
                if not lease_expired(r.get("lease_until"))}
        if live and holders - {"", who}:
            out.update(state="other", holder="、".join(sorted(holders - {""})),
                       lease_until=sorted(live)[-1],
                       why="另一个实例还持着这一次委托（租约未到期）⇒ 不写")
            return out
        at = S.now_iso()
        lease = make_lease(int(lease_seconds))
        for row in rows:
            row["claimed_by"] = who
            row["lease_until"] = lease
            row["claimed_at"] = at
            tx.upsert("lit_candidates", row, note="a.claim_pending")
        out.update(state=("mine_again" if live else "mine"), holder=who,
                   lease_until=lease, claimed=True)
        tx.info("lit.claim_pending", request_id=rid, actor=who,
                slots=out["slots"], lease_until=lease)
    return out


def clear_delegation(store: Store, request_id: str, *, actor: str = "agent-A",
                     mapping: Sequence[Mapping[str, Any]] = (),
                     reason: str = "",
                     only_slots: Sequence[str] | None = None) -> dict:
    """清表：给本委托的行打 `cleared_at` + `clear_reason`（不物理删）。

    `only_slots`（FX3·甲）：只清这一批提交过的行；不给 ⇒ 清本委托全部行（老调用点）。
    未提交的 pending 行不打 `cleared_at` —— 它们要能被下一批继续提交，而收工闸的
    `delegation_not_cleared` 也正是靠"还有行没有 cleared_at"如实红。

    三件一起落（顺序不能换）：
    1. 事务内先把整份行（含未判的 pending）写进归档 JSONL（幂等整份覆盖）——
       归档回答的是"这次委托的每一条候选最后长什么样"，所以它按委托整份写，不按批；
    2. 逐行打标记 + `tx.info("lit.close", …, mapping=[{slot, lit_id}])` ——
       映射关系进事件日志（改行/删行的唯一可重放证据，`store.Tx.delete` 同理）；
    3. 不写 `status`：`admitted` 的行必须在库里继续是 `admitted`
       （文献库面 `webui/readers._library_admission` 只读那一格），
       `rejected` 的行必须继续说得出理由。清表清的是"待入库列表这一趟的活"，
       不是"库里的行"。

    返回 `{request_id, cleared, archived, mapping, rows, at}`。
    """
    rid = str(request_id or "").strip()
    if not rid:
        raise LitStageError("清表必须知道是哪一次委托（request_id 为空）",
                            kind="no_delegation")
    with store.tx("lit_candidates", actor=actor, note="lit.close") as tx:
        rows = [dict(r) for r in tx.rows("lit_candidates")
                if str(r.get("request_id") or "") == rid]
        at = S.now_iso()
        scope = (None if only_slots is None
                 else {str(s or "") for s in only_slots})
        # 先在内存里打好标记，再归档：归档里那一份要看得见"这一次清表是什么时候、
        # 为什么"（清表本身就是审计对象，不是归档之后才发生的事）。
        for row in rows:
            if scope is not None and str(row.get("slot") or "") not in scope:
                continue
            if not str(row.get("cleared_at") or "").strip():
                row["cleared_at"] = at
                row["clear_reason"] = str(reason or CLEAR_REASON)
        archived = _archive_rows(store, rid, rows)
        pairs: list[dict] = []
        for row in rows:
            if scope is not None and str(row.get("slot") or "") not in scope:
                continue
            tx.upsert("lit_candidates", row, note="lit.close.clear")
            pairs.append({"slot": str(row.get("slot") or ""),
                          "lit_id": str(row.get("lit_id") or ""),
                          "status": str(row.get("status") or ""),
                          "cleared_at": str(row.get("cleared_at") or "")})
        tx.info("lit.close", request_id=rid, cleared=len(pairs),
                archive=archived["rel_path"],
                mapping=[{"slot": p["slot"], "lit_id": p["lit_id"]}
                         for p in pairs if p["lit_id"]],
                statuses={s: sum(1 for p in pairs if p["status"] == s)
                          for s in CANDIDATE_RECORDS})
    return {"request_id": rid, "cleared": len(pairs), "archived": archived,
            "mapping": [p for p in pairs if p["lit_id"]], "rows": pairs, "at": at,
            "given_mapping": [dict(m) for m in mapping]}


def candidate_identity(title: Any, doi: Any) -> str:
    """一条候选在一次委托内的身份：规范化 DOI 优先，DOI 空才退回规范化标题。

    为什么 DOI 优先，而不是"标题与 DOI 一起比"：同一篇在两次检索里交回的题名
    可能差一个连字符或副标题位置（存量行里就有
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

    为什么暂存不设上限：上限管的是入库，不是"广搜能拿回多少"。
    把上限提前到暂存这一档，会让"广搜 30 条、精选 8 条入库"这条正路直接走不通 ——
    而口径明确要求"广搜可以超过 10 篇，但正式入库最多 10"。

    槽位号由 `store.alloc_id("candidate")` 发：只增不复用（撤掉的号不会被再发一次），
    所以第 2 批的序号接着第 1 批往下排（12 条 + 3 条 = 1..15，撤掉的 3、7 空着）。

    `request_id` 必须给（列表按委托重置）——
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
                # 报告里每篇已入库的都要一句"为什么与本次检索相关"。
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
    # 清单变了 ⇒ 上一份回读回执作废：这一次新加进来的槽位还没人读过，提交前必须重读
    # （否则"回读过"这句话会覆盖一份它没见过的清单 —— 那正是 AH6 里 12 条 relevance 的形态）。
    _drop_readback(store, rid)
    return {"request_id": rid, "batch": the_batch, "count": len(staged),
            "staged": staged, "updated": updated}


def _scoped_rows(rows: Sequence[Mapping[str, Any]], rid: str) -> list[dict]:
    """把行按委托过滤（"默认视图只看当前委托"的唯一实现）。

    三态，与 `request_id` 的三种取值一一对应：

    - `rid == "*"` ⇒ 不过滤（审计用：查全部委托）；
    - `rid` 非空 ⇒ 只留这一次委托的行；
    - `rid` 为空 ⇒ 一行都不给（不是"全表"）。"说不清这是哪一次委托"与"所有委托"
      是两件事，后者会把旧委托的行混进本次筛选 —— 而那正是委托边界要挡的。

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
    `pending` / `admitted` / `rejected` 三档。

    空槽位（原来叫 `withdrawn`、现在折成 `rejected` + `withdrawn_by_reviewer`）
    并没有被物理删除（序号不复用），所以题名、理由、`added_at` 全都还在 —— 于是
    "第 3 号被撤了哪一篇、为什么"是查得出来的。这正是"撤掉 ≠ 删掉"的落点：撤掉 ≠ 删掉。

    `status` 过滤同时认两种形态：折算后的三态（`pending`/`admitted`/`rejected`）
    与盘上的历史档名（`cleared` / `withdrawn`，照原样查得到那几条）—— 后者是为了
    "查历史"这条路不因为折算而断（老工作区里按 `cleared` 查仍然查得出那 14 条）。

    默认视图只按当前委托过滤；要看旧委托请显式给
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
    # 「当前委托」算一次、两处用（默认视图与回填那一格）：按实例算（K16 / AL-02），
    # 判据在 `_current_request_id` 一处；这里只是不把同一张表再读一遍。
    current = _current_request_id(store, all_rows)
    rid = str(request_id or "").strip() or current
    scoped = _scoped_rows(all_rows, rid)
    if batch is not None:
        scoped = [r for r in scoped if int(r.get("batch") or 0) == int(batch)]
    # 三态只判一次：状态过滤、counts 与重复组三层原先各自再算一遍 `judged_state`。
    judged = [(r, judged_state(r)) for r in scoped]
    if status is not None:
        rows = [fold_legacy(r) for r, state in judged
                if str(r.get("status") or "") == status
                or state == status]
    else:
        rows = [fold_legacy(r) for r, _state in judged]
    rows.sort(key=lambda r: str(r.get("slot") or ""))
    # 计数按委托过滤后、状态过滤前那一份算：调用方问"这一批还有几篇 pending"时
    # 需要同时看到全部态，否则 status=admitted 那一次查询会把"总数 12"读成"总数 9"。
    # 键集合是 `schema.CANDIDATE_STATUSES` 那五个 + `qualified`（判收未注册）：
    # 两个历史档永远是 0（它们已经折进 `rejected`）。计数按盘上的 status数，
    # 不按 `judged_state` —— 后者把 `qualified` 读成"判过（判定入库）"，
    # 而这里要回答的是"这一批现在各是哪一档"（判收未注册与已注册是两档）。
    counts = {s: 0 for s in S.CANDIDATE_STATUSES}
    counts.setdefault(QUALIFIED, 0)
    # 同一委托内同一篇占多个槽的读数（G9 修法 ②：只报数，不动 counts 的分子分母）。
    groups: dict[str, list[str]] = {}
    for r, _state in judged:
        status = str(fold_legacy(r).get("status") or "")
        if status in counts:
            counts[status] += 1
        groups.setdefault(candidate_identity(r.get("title"), r.get("doi")), []).append(
            str(r.get("slot") or ""))
    slots = [str(r.get("slot") or "") for r in rows]
    gaps: list[str] = []
    if slots:
        have = {int(s) for s in slots}
        gaps = [S.format_id(n) for n in range(min(have), max(have) + 1) if n not in have]
    waiting = undecided(scoped)
    # 全表（跨委托）那一条读数：默认视图只返回当前委托的行，但"这一趟清完了没有"
    # 看的是全表 —— 不把这两句话同时写进 note，旧委托的 pending 就只在收工闸那里
    # 才第一次露面（VC1 P1-6 的现场）。作用域由 `pending_all_delegations` 写死。
    scope = pending_all_delegations(all_rows, current=current)
    scope_line = pending_scope_note(scope) or (
        f"全表（跨委托）没有待裁的行（{len(all_rows)} 行候选里 0 条 pending）。")
    dup_groups = sorted(
        ({"key": k, "slots": sorted(v)} for k, v in groups.items() if len(v) > 1),
        key=lambda g: g["slots"][0])
    # 可读性判定跟着行一起读出来（台账按槽位号查，槽位号全局唯一）：回读的那一眼于是
    # 同时看得见"这一条判过没有"与"这一条的可读性审过没有"—— 两件都是提交前要收的口径。
    tiers = LAV.tiers_by_slot(store.root)
    # 抽读回执只补"抽过但失败"这一档（机器判得出的事实）：A 还没报档位时，
    # 列表上就能看见"这一条有字节但抽不出可读文本"，而不是空白一个"未查"。
    # 成功那一侧不替 A 报 readable —— 抽出来可读 ≠ A 读过（读过要 fs.read）。
    for slot, receipt in LAV.receipts_by_slot(store.root).items():
        if slot not in tiers and _tier_of_receipt(receipt):
            tiers[slot] = _tier_of_receipt(receipt)
    for r in rows:
        r["availability"] = tiers.get(str(r.get("slot") or ""), "")
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
        "note": _stage_list_note(len(waiting)) + scope_line,
    }


def _stage_list_note(waiting_count: int) -> str:
    """`list_candidates` 返回的那一条 `note`（A 在真机上读到的教法）。

    单独成函数只为让「口径写反」这件事有一个可被负控替代的落点：判据把这一格
    打桩成旧口径 ⇒ 必须红（`tests/test_lit_stage_note_says_metadata_only_needs_an_attempt.py`）。

    2026-11-17（PA3）：`metadata_only` 那一句此前写反了 ——「盘上没有字节的才报」
    是旧口径（业主 2026-11-16 裁定 AR1 之前的"零读可入"）。真口径在
    `litavail` 与 `_read_evidence_gate`：仅题录也必须先试过一次抽取（留下
    `extract_failed` 回执），零回执的仅题录按 `no_read_evidence` 整批拒、逐槽点名。
    """
    return (
        "默认只返回当前委托的行（`request_id` = 最近一次暂存的那次委托）；"
        "查历史请显式给 request_id（`*` = 全部）。状态四档："
        "`pending` 待裁 / `qualified` 判收未注册（无号） / `admitted` 已注册"
        "（带 lit_id） / `rejected` 拒收；"
        "历史的 `cleared` 读成 rejected+over_cap、`withdrawn` 读成 "
        "rejected+withdrawn_by_reviewer（撤掉的槽位仍在，序号不复用）。"
        f"本委托还有 {waiting_count} 条没判：只要还大于 0，`lit.admit_all` "
        "就整批拒绝（`lit.admit` 逐条判收不受它拦）。"
        "判收（`lit.admit`）**不发号**：正式文献号由 `lit.admit_all` 在提交那一刻"
        "批量注册并回填，随后清表（`cleared_at` 打上、整份行归档在 "
        "data/lit_candidates/archive-<request_id>.jsonl）。"
        # 2026-11-19（FIXBATCH ②）：这一句原先只活在收工门
        # （`closing._check_literature_pending` 的 docstring）里 —— 那是收工那一刻才
        # 跑到、模型读不到的地方。真机 lp-ball-11：`search_requests` 七条全部
        # `done=true`，而 `lit_candidates` 还挂着 60 条 pending、`lit.stage_reject`
        # 事件 0 条；A 在 final 里把"待裁还剩多少"读成"这一档已经收过工"。
        # 落点选 `lit.stage_list` 的返回文案（A 每趟判收前都会读它），不动
        # `closing.py`、也不动禁改区的 `specs/a.py`：事实不变，只换落点。
        "A 的 `done=True` 只表示「这一条检索请求跑完了」，不等于「清表」；"
        "收工闸数的是**全表**，不是当前委托、也不是那一条检索请求。"
        "标 `readable` 之前先 `text.extract(path=<全文路径>, lit_id=\"cand:<槽位>\")` "
        "抽出正文、再用 `fs.read` 读那份 `.txt` —— 没有这两步的事实，"
        "`lit.admit` 会以 `no_read_evidence` 整批拒并逐槽点名；"
        "报 `metadata_only` 也一样：**必须先试一次抽取**（留下 `extract_failed` 回执）"
        "才允许按仅题录入库，零回执的仅题录会被同一道闸按零读取尝试整批拒掉"
        "（要指得出处）。"
    )


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
              slot_field: str, actor: str, tx_note: str,
              refresh_report: bool = True) -> dict:
    """把某一槽写成判过的那一档：`status="rejected"` + 受控理由码 + 一行散文。

    为什么不再有"写成 withdrawn"这条分支：状态只有三态
    （待裁 / 入库 / 拒收），"撤掉"与"拒收"的差别现在落在受控理由码上
    （`withdrawn_by_reviewer` 还是 `rejected_low_quality`），不再多占一个状态格。
    `slot_field` 保留原样：`lit.stage_withdraw` 仍然把那一句同时写进
    `withdrawn_reason`（老读者按那一列查"撤了什么"照旧查得到），
    `reject_reason` 两边都写满 —— 折完之后行仍然说得出理由。

    可改的条件是 `judged_state(row) == "pending"`，不是"status 字面是 pending"：
    历史链路整批入库、`relevance` 空着的那几条（存量行就是这个形状）也算
    "没判过"，于是它们还能被逐条判拒 —— 否则那种行会永远卡在"写不进 relevance、
    又不许判拒"里，提交闸对它所在的那次委托就成了永久关闭。

    2026-11-16（Q1）：`qualified` 的行可以改判拒/撤（判收之后、提交之前改主意是
    允许的：号还没发、库里还没有它，改判只是一次状态改写）。判过 `admitted` 的行
    不行 —— 那一行的号已经发出去，改它等于抹掉"这一篇进过库"。

    报告过期（Q1 第 ⑨ 条）：判完一条就把已经存在的那份报告重渲染一次
    （`reports/lit-<rid>.md` 存在才写）。不这么做，报告会静默停在"待裁 15 条"，
    而那些行早就判完了（真机 `lit-r-000008.md` 就是这个形态）。
    """
    with store.tx("lit_candidates", actor=actor, note=tx_note) as tx:
        row = next((r for r in tx.rows("lit_candidates") if str(r.get("slot")) == str(slot)), None)
        if row is None:
            raise LitStageError(f"待新增列表里没有槽位 {slot!r}", kind="unknown_slot",
                                detail={"slot": slot})
        state = judged_state(row)
        status_now = str(fold_legacy(row).get("status") or "")
        if state != "pending" and status_now != QUALIFIED:
            raise LitStageError(
                f"槽位 {slot!r} 已经判过了（{state}，盘上 status="
                f"{row.get('status')!r}）⇒ 只有还没判的那一槽能改成 rejected",
                kind="not_pending", detail={"slot": slot, "status": row.get("status")},
            )
        row = dict(row)
        row["status"] = "rejected"
        row["reason_code"] = code
        row[slot_field] = str(note or "").strip() or _code_label(code)
        row["reject_reason"] = row[slot_field]
        # 判拒之后它没有"有入库资格"这回事了：把判收那一格的残留清干净
        # （只清"这一行现在不是 admitted"时才安全，见上面的分支）。
        row["lit_id"] = None
        row["admitted_at"] = ""
        S.LitCandidate(**{k: row[k] for k in row
                          if k in S.LitCandidate.__dataclass_fields__}).validate()
        tx.upsert("lit_candidates", row, note=tx_note)
        rid = str(row.get("request_id") or "")
    out = {"slot": str(slot), "status": "rejected", "reason_code": code,
           "reason": row[slot_field], "title": row.get("title"),
           "request_id": row.get("request_id"), "batch": row.get("batch")}
    if refresh_report and rid:
        _refresh_report_if_present(store, rid)
    return out


def withdraw(store: Store | None, slot: str, reason_code: str, note: str = "",
             *, actor: str = "agent-A") -> dict:
    """撤掉某一槽：状态落 `rejected` + 受控理由码（`withdrawn_by_reviewer`），不物理删除。

    撤掉之后可以再 `stage_add` 补位 —— 但新条进的是新序号（旧号不复用），
    所以列表里会同时看到"第 3 号（撤掉，理由…）"与"第 13 号（补进来的那条）"。
    那一句同时写进 `withdrawn_reason` 与 `reject_reason`：前者是老读者查
    "撤了什么"的那一列，后者是三态里"拒收的理由"那一列。

    `reason_code` 必须是 `schema.CANDIDATE_REASON_CODES` 里的受控取值
    （报告里的理由只认受控取值，不许自由发挥）。
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


def _readback_gate(store: Store, rid: str, wanted: Sequence[str],
                   base: Mapping[str, Any]) -> dict | None:
    """回读闸（业主裁定 9 / 15）：要提交的每个槽位都得被这次委托的回执覆盖。

    抽成函数是为了让 `admission_plan` 留在 200 行线内（体量三格是软基线，只许降）。
    返回 `None` = 这一闸放行；否则是一整笔受控拒（逐条点名缺哪几个槽）。
    """
    receipt = readback_receipt(store, rid)
    covered = set(receipt.get("slots") or []) if receipt else set()
    uncovered = [s for s in wanted if s not in covered]
    if not uncovered:
        return None
    return {**base, "ok": False, "kind": "no_readback", "whole_call_refused": True,
            "reason": _readback_reason(rid, uncovered, has_receipt=bool(receipt)),
            "missing_readback": uncovered, "call_size": 0, "admitted": []}


def _read_evidence_gate(store: Store, rid: str, wanted: Sequence[str],
                        tiers: Mapping[str, str],
                        by_slot: Mapping[str, Mapping[str, Any]],
                        base: Mapping[str, Any]) -> dict | None:
    """读证据闸（业主裁定 3 / AR1）：有回执才准判准入，不是 A 的一句话。

    两档一起判（判据真身在 `litavail.check_read`）：

    - `readable`：这一条必须 `check_read == "ok"` —— 抽读回执在、回执绑的是这一条
      候选（身份三格 + `cand-<槽>.txt`）、抽读件还是那一版、A 用 `fs.read` 读过同一版。
      只抽不读 ⇒ `not_read`；抽过但失败 ⇒ `extract_failed`；没抽过 ⇒ `no_extract`。
      三种都逐槽点名，而不是一句"请先读"。
    - `metadata_only`：不是零读可入（AR1 / VC1 P0-1）。它必须有"试过、但拿不到
      可读文本"的那条 `extract_failed` 回执；没有回执（`no_extract`）⇒ 拒；有字节且
      抽出了正文（`ok` / `not_read` / `text_changed` …）⇒ 也拒（盘上有字节，仅题录是假话）。
      `metadata_only` 不核候选身份：它证明的是"试过一次"，不是"读过"。

    返回 `None` = 放行；否则整笔受控拒（`no_read_evidence`，逐条给 `read_problems`）。
    """
    receipts = LAV.receipts_by_slot(store.root)
    problems: list[dict] = []
    for slot in wanted:
        tier = str(tiers.get(slot) or "")
        if tier == LAV.EXTRACT_FAILED:
            # 这一档由 `_availability_gate` 拦（它先跑）：这里不重复报同一个原因。
            continue
        receipt = receipts.get(slot)
        # 只有 readable 要核"读的是这一条候选"（P1-4）；metadata_only 只核"试过没有"。
        expected = (LAV.candidate_digest(by_slot.get(slot) or {})
                    if tier == LAV.READABLE else None)
        state, why = LAV.check_read(store.root, slot, receipt, expected=expected)
        if tier == LAV.READABLE:
            if state != "ok":
                problems.append({"slot": slot, "state": state, "why": why})
        elif tier == LAV.METADATA_ONLY:
            if state == "extract_failed":
                continue
            if state == "no_extract":
                why = ("零读取尝试：`data/lit_reads.jsonl` 里没有这一条。仅题录也要先试一次"
                       "抽取 —— 拿不到可读文本（`extract_failed` 回执）才允许按仅题录入库")
                state = "no_attempt"
            elif state == "ok":
                why = (f"这一条抽出了可读正文（{int((receipt or {}).get('chars') or 0)} 字），"
                       "盘上有字节就不能报仅题录：读了报 readable，否则按受控理由码判拒")
            else:
                why = f"仅题录要求一条'试过、拿不到可读文本'的回执；这一条停在 {state}：{why}"
            problems.append({"slot": slot, "state": state, "why": why})
    if not problems:
        return None
    return {**base, "ok": False, "kind": "no_read_evidence", "whole_call_refused": True,
            "reason": _read_evidence_reason(rid, problems),
            "read_problems": problems, "call_size": 0, "admitted": []}


def _read_evidence_reason(rid: str, problems: Sequence[Mapping[str, Any]]) -> str:
    """读证据闸的拒信：逐槽点名"卡在哪一步"，再给两条正路。

    为什么不写成"请先读再判"：A 需要知道的是这一槽停在"没抽""抽了没读"还是
    "抽过失败"—— 三种的下一步不同（下载/抽、fs.read、判拒）。
    2026-11-16（AR1）起 `metadata_only` 也在这道闸里：它不是"没查"的写法，是
    "试过、拿不到可读文本"的写法 —— 连一次抽读回执都没有的仅题录，按同一档拒。
    """
    scope = f"本次委托（{rid}）" if rid else "本委托"
    parts = [f"{p.get('slot')}：{p.get('why')}" for p in problems]
    return (
        f"{scope}的「读过」证据过不了入库闸：{'；'.join(parts)} ⇒ **整批不许提交入库**。"
        "口径：`readable` 不是自报。判收成 readable 的每一条都要先抽读、再读：\n"
        "① `search.download` 拿到全文的 `rel_path`（或盘上那份文件的路径）；\n"
        "② `text.extract(path=<路径>, lit_id=\"cand:<槽位>\")` —— 抽出的 `.txt` 与一条"
        "抽读回执会一起落盘（回执记着这一条候选的身份与抽读件版本）；\n"
        "③ `fs.read` 那份 `.txt`（闸核的是你读的与抽读件是同一版）；\n"
        "④ 然后再 `lit.admit`（`items[].availability=\"readable\"` + 那条候选自己的 "
        "`relevance`）。\n"
        "只想录题录（`metadata_only`）的那一条：也要先走 ② 试一次抽读。抽不出来"
        "（`no_text_layer` / 乱码 / 抽取报错）会留下一条 `extract_failed` 回执，"
        "拿着它再报 `metadata_only` + DOI/URL 才能入库；**一次都没试过的仅题录会被"
        "这一道闸按零读取尝试拒掉**。抽过但正文可读却不想读的，按 `extract_failed` 判 "
        "`lit.stage_reject`（`reason_code=\"rejected_low_quality\"`）。"
    )


def _availability_gate(rid: str, wanted: Sequence[str],
                       by_slot: Mapping[str, Mapping[str, Any]],
                       tiers: Mapping[str, str],
                       scoped: Sequence[Mapping[str, Any]],
                       base: Mapping[str, Any]) -> dict | None:
    """可读性覆盖闸（业主裁定 ②③）：要提交的每个槽位都要有判定，且那一档能入库。

    `extract_failed` / `unknown` / 没有定位符的仅题录一律不许进 —— 整批拒、逐条点名。
    返回 `None` = 放行。判据只有 `litavail` 一处（四档词表与 `ADMITTABLE_TIERS`）。
    """
    unaudited = LAV.missing_tiers([by_slot[s] for s in wanted], tiers)
    bad_tiers: list[tuple[str, str]] = []
    for s in wanted:
        t = str(tiers.get(s) or "")
        if s not in tiers:
            continue
        # 仅题录：可以入，但必须指得出处（`litavail.locator_of` 非空）。
        if t == LAV.METADATA_ONLY and not LAV.locator_of(by_slot[s]):
            bad_tiers.append((s, t))
            continue
        if not LAV.is_admissible(t):
            bad_tiers.append((s, t))
    if not (unaudited or bad_tiers):
        return None
    return {**base, "ok": False,
            "kind": "availability_not_admissible" if bad_tiers else "missing_availability",
            "whole_call_refused": True,
            "reason": _availability_reason(rid, bad_tiers, missing=unaudited),
            "missing_availability": unaudited,
            "availability_bad": [{"slot": s, "tier": t} for s, t in bad_tiers],
            "counts": _decision_counts(scoped),
            "call_size": 0, "admitted": []}


def _judged_gate(wanted: Sequence[str], by_slot: Mapping[str, Mapping[str, Any]],
                 scoped: Sequence[Mapping[str, Any]], rid: str,
                 base: Mapping[str, Any]) -> dict | None:
    """提交闸（Q16 第 ③ 条 / FX3·甲）：这一批内每一条都必须判过，否则整批拒。

    作用域 = 这一次提交覆盖的槽（`wanted`），不是整委托：15 槽判完 5 槽 ⇒ 提交那 5 槽
    放行，其余 10 槽保持 pending 进下一批。点名点到未判的槽 ⇒ 逐条点名拒
    （`undecided_items`），"批内全判"仍是硬要求，一个字没放宽。

    点名是空表（`slots=[]`）⇒ 这一笔没有覆盖任何槽：有 pending 就按"还有 N 条没判"拒
    （旧调用点 `admission_plan(slots=[], require_judged=True)` 读的就是这一档），
    一条 pending 都没有才落 `nothing_to_submit`（不是成功 —— 空提交没有对象）。

    判据只有 `undecided` 那一处（打桩成恒空 ⇒ 本闸失效，见
    tests/test_pending_list_is_three_state.py 的反真空那一条）。

    作用域不扩到别的委托：让新委托被旧账卡住是另一个缺陷（VC1 P1-6 的
    「最小补法」逐字反对这条路）。跨委托那一半是读数：`base` 里的
    `pending_by_delegation` 与 `pending_scope_note` 会把"别的委托还剩几条、谁能清"
    写进拒信 —— 看得见，但不拦这一次提交；拦它的是收工闸（全表口径）。
    """
    if wanted:
        waiting = undecided([by_slot[s] for s in wanted])
    else:
        waiting = undecided(scoped)
        if not waiting:
            return {**base, "ok": False, "kind": "nothing_to_submit",
                    "whole_call_refused": True,
                    "reason": (f"本次提交没有覆盖任何槽位（委托 {rid} 已经没有可提交的"
                               "判定了）：要么先 `lit.stage_add` 进候选，要么点名 "
                               "`slots` 指定这一批要交哪几个槽"),
                    "counts": _decision_counts(scoped), "call_size": 0, "admitted": []}
    if not waiting:
        return None
    others = str(base.get("pending_scope_note") or "")
    return {**base, "ok": False, "kind": "undecided_items", "whole_call_refused": True,
            "reason": undecided_reason(waiting, rid) + (f" {others}" if others else ""),
            "undecided": waiting, "counts": _decision_counts(scoped),
            "call_size": 0, "admitted": []}


def _over_cap_gate(call_size: int, limit: int, already: int,
                   base: Mapping[str, Any]) -> dict | None:
    """`refuse_all` 那一档的调用形状：单次超限 / 委托累计超限 ⇒ 整笔拒。

    先判形状再判证据：一次要入 11 条是"这次调用根本不成立"，与证据齐不齐是两件事
    （先报后者会让 A 去补一堆证据、回来仍然超限）。
    """
    if call_size > limit:
        return {**base, "ok": False, "kind": "over_cap_call", "whole_call_refused": True,
                "reason": (
                    f"本次调用要入库 {call_size} 条，超过单次上限 {limit} 条 ⇒ 整笔拒绝"
                    f"（一条都没入：分批突破上限不算合法）。请精选到 ≤{limit} 条，"
                    f"或分成多次调用（同一委托累计入库仍受 {MAX_ADMIT_PER_DELEGATION} 条限制）"),
                "call_size": call_size, "admitted": []}
    if already + call_size > MAX_ADMIT_PER_DELEGATION:
        return {**base, "ok": False, "kind": "over_cap_delegation",
                "whole_call_refused": True,
                "reason": (
                    f"这次委托已经入库 {already} 条，这次还要入 {call_size} 条 ⇒ "
                    f"累计 {already + call_size} 条，超过该委托上限 "
                    f"{MAX_ADMIT_PER_DELEGATION} 条 ⇒ 整笔拒绝（一条都没入）。"
                    "一次文献检索正式入库至多 10 篇，必须精选"),
                "call_size": call_size, "admitted": []}
    return None


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
    require_readback: bool = False,
    from_qualified: bool = False,
    judged_scope: Sequence[str] | None = None,
) -> dict:
    """入库前的那一笔判断：提交闸 + 条数上限 + 重叠检查 + 逐条该不该进（一行都不写）。

    这是"入库这个动作"的唯一入口判据：`lit.admit` / `lit.admit_all` / A 的自动链路
    三条路都从这里过，谁也不许在调用点上各判一次（判据两份必然漂，而漂的形态是
    "工具说拒了、实现却写进去了"）。

    ## 提交闸

    `require_judged=True` 的那两条路（`lit.admit_all` 与 A 的自动链路）是"整批提交"：
    这一批（`judged_scope`；不给 ⇒ 要入库的 `slots`）里只要还有一条没判，整批一条
    都不许入库，拒信逐条点名（`undecided_reason`）。批外未判的槽不拦这一笔（FX3·甲：
    15 槽判完 5 槽可只交 5 槽，其余进下一批；收工闸仍看全表）。
    "判过"的定义只此一处：`judged_state`（`pending` 与"入库了却写不出 relevance"都算没判）。
    它管"决定过没有"；"读过没有"是紧接着的 `_read_evidence_gate`（`no_read_evidence`），
    两道闸管两件事，谁也不替谁作证。

    逐条入库（`lit.admit`，`require_judged=False`）不受这条闸拦 —— 它就是判决本身：
    它要过的是下面那条"每一条入库都必须带 relevance"的逐条判据。

    ## 两档超限处置（`on_over_cap`）

    - `"refuse_all"`（`lit.admit` 用）：本次要入的条数超过上限 ⇒ 整笔拒绝，
      一条都不入。为什么整笔：如果前 10 条进了、第 11 条被挡，调用方会读成
      "第 11 条被审掉了"，而真相是"这一次调用根本不成立"。
    - `"truncate"`（`lit.admit_all` / A 的自动链路用）：按槽位号顺序把前 N 条
      通过检查的收进来，其余落 `rejected` + `reason_code="over_cap"` ——
      一键迁移的语义是"把通过的都迁走"，不是"有一条超限就全不动"。
      落盘处不再是第四态 `cleared`（配额满必须折进
      rejected + over_cap），但 `plan["cleared"]` 这个键名沿用下来：
      它是"没进去的那几条"这一个读数格，不是状态名（`lit.admit` 的 `returns=`
      已经把它钉在冻结声明里，改名要人重冻快照）。

    ## 逐条拒收

    - 这一条已经判过（`judged_state != "pending"`）⇒ 拒（`already_terminal`）；
    - 这一条没有 relevance（行上没有、调用级也没给）⇒ 拒（`missing_relevance`），
      行保持原样：没写"为什么与本次检索相关"就等于没读过它。
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
    # 全表待裁（跨委托）的那一条读数：本闸按本委托判"能不能提交"，但"这一趟清完了
    # 没有"要看全表 —— 两个读数都放进 base，于是每一条返回（放行与受控拒）
    # 都带着"别的委托还剩几条、谁能清"。作用域由 `pending_all_delegations` 写死。
    # `current` 标志在闸这里不参与判定（`exclude=rid` 已经点名了本委托），所以不传 ——
    # 保持这个调用点在判据夹具里的形状（它们把 `pending_all_delegations` 换成单参 lambda）。
    scope = pending_all_delegations(rows)
    scope_note = pending_scope_note(scope, exclude=rid)
    scoped = [fold_legacy(r) for r in rows
              if str(r.get("request_id") or "") == rid]
    if slots is None:
        if batch is None:
            # FX3·甲：不点名 = 本委托「已判定的全部」（按批提交的默认作用域）。
            # 旧调用点（`lit.admit` 的 batch 档与 A 的自动链路）仍然显式给 slots/batch。
            wanted = submission_slots(scoped)
        else:
            wanted = [str(r.get("slot")) for r in sorted(scoped, key=lambda r: str(r.get("slot") or ""))
                      if int(r.get("batch") or 0) == int(batch) and judged_state(r) == "pending"]
    else:
        wanted = submission_slots(scoped, slots)
        if not wanted and not require_judged:
            raise LitStageError("slots 是空的：没有要入库的东西", kind="no_target")
    by_slot = {str(r.get("slot") or ""): r for r in scoped}
    if judged_scope is None:
        gate_slots = wanted
    else:
        gate_slots = submission_slots(scoped, judged_scope)
    unknown = [s for s in wanted if s not in by_slot]
    unknown += [s for s in gate_slots if s not in by_slot and s not in unknown]
    if unknown:
        outside = [s for s in unknown if s in {str(r.get("slot")) for r in rows}]
        raise LitStageError(
            f"这些槽位不在**本次委托**（{rid}）的待新增列表里：{unknown}"
            + (f"；其中 {outside} 属于别的委托（列表按委托重置，旧委托的行不参与本次筛选）"
               if outside else "（序号不复用，请用 lit.stage_list 查一遍）"),
            kind="unknown_slot", detail={"slots": unknown, "request_id": rid},
        )
    batches = {int(by_slot[s].get("batch") or 0) for s in wanted}
    # 配额读数的分母口径：逐条判收（`from_qualified=False`）时"已经入库的"包含
    # 已判收未注册的那几条（它们迟早会占配额，先占住才不会"判 10 条、提交时超限"）；
    # 提交那一刻（`from_qualified=True`）只数已经注册的那几条 —— 否则本次要注册的
    # 那 10 条会被自己算成"已经入库 10 条"，一条也注册不了。
    already = (sum(1 for r in scoped if str(r.get("status") or "") == "admitted")
               if from_qualified else
               sum(1 for r in scoped if judged_state(r) == "admitted"))

    items: list[dict] = []
    refused: list[dict] = []
    over_cap: list[dict] = []
    # 可读性判定（A 的逐条自审）按槽位读一次：台账是旁路文件（零 schema），
    # 槽位号全局唯一，所以这里不需要按委托再过滤一遍。
    tiers = LAV.tiers_by_slot(store.root)
    # 索引建一次、逐槽复用：`overlap_check` 自己也会建，但那是"每条候选一遍全表"。
    lit_index = literature_index(store)
    for slot in wanted:
        row = by_slot[slot]
        state = judged_state(row)
        if from_qualified and str(row.get("status") or "") == QUALIFIED:
            # 提交那一刻：这一条已经判收（`judged_state` 把它读成 admitted），
            # 现在要做的是"注册"，不是"再判一次" ⇒ 跳过逐条终态检查，只走下面
            # 的重叠/证据那几道闸（它们本来就该在注册前再核一遍）。
            state = "pending"
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
        "pending_total": scope["total"],
        "pending_by_delegation": scope["by_delegation"],
        "pending_scope_note": scope_note,
        "refused": refused,
        "cleared": over_cap,
    }
    if on_over_cap == "refuse_all":
        refused_gate = _over_cap_gate(call_size, limit, already, base)
        if refused_gate is not None:
            return refused_gate
    if require_judged:
        refused_gate = _judged_gate(gate_slots, by_slot, scoped, rid, base)
        if refused_gate is not None:
            return refused_gate
    if require_readback:
        refused_gate = _readback_gate(store, rid, wanted, base)
        if refused_gate is not None:
            return refused_gate
    refused_gate = _availability_gate(rid, wanted, by_slot, tiers, scoped, base)
    if refused_gate is not None:
        return refused_gate
    refused_gate = _read_evidence_gate(store, rid, wanted, tiers, by_slot, base)
    if refused_gate is not None:
        return refused_gate
    if on_over_cap == "refuse_all":
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
#: ## 为什么要有这一格
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
#: 修不修行为要等这条读数先跑出一批现场数据（口径：先要读数）。
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
    return {
        "checked": True,
        "count": len(bad),
        "rows": bad,
        "reason": "" if not bad else f"{len(bad)} 条结算决定与盘上的行对不上",
    }


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


def apply_qualification(tx: Any, decisions: Iterable[Mapping[str, Any]]) -> list[dict]:
    """把一批"判收"写成 `qualified`（有入库资格、不注册、不写 lit_id）。

    业主口径（Q1）：「审入库资格时每条待入库文献用临时文献号」——
    判收这一步只改状态与证据，一个 literature 行都不建、一个号都不发。
    号只在 `admit_all`（提交）那一刻由登记路径批量发出来，再回填到同一行
    （`apply_settlement` 的 `admitted` 分支）。两件事分开，于是"回填"有对象可指。

    `decisions` 的每一项：`{slot, status="qualified", relevance?, new_content?,
    overlap_score?, overlap_kind?, overlap_with?}`。写进去的只有证据；
    `lit_id` / `admitted_at` 保持空（`schema.LitCandidate.validate` 由 FC-27 补丁
    守这一条：`qualified` ⇒ relevance 非空且 lit_id 为空）。
    """
    rows = {str(r.get("slot") or ""): r for r in tx.rows("lit_candidates")}
    written: list[dict] = []
    for d in decisions:
        slot = str(d.get("slot") or "")
        if str(d.get("status") or QUALIFIED) != QUALIFIED:
            continue
        row = dict(rows.get(slot) or {})
        if not row:
            _note_settlement_mismatch(kind="dropped_slot", slot=slot,
                                      expected=QUALIFIED, got="",
                                      why="判收决定指向的槽位在表里读不到 ⇒ 这一笔被丢掉")
            continue
        row["status"] = QUALIFIED
        row["lit_id"] = None
        row["admitted_at"] = ""
        for k in ("overlap_score", "overlap_kind", "overlap_with"):
            if d.get(k) not in (None, ""):
                row[k] = d[k]
        for k in ("new_content", "relevance"):
            if str(d.get(k) or "").strip():
                row[k] = str(d[k]).strip()
        S.LitCandidate(**{k: row[k] for k in row
                          if k in S.LitCandidate.__dataclass_fields__}).validate()
        tx.upsert("lit_candidates", row, note="lit.admit.qualify")
        rows[slot] = row
        written.append(row)
    return written


#: 「不落终态」的拒因（`_decisions_from` 直接筛掉）：这几档都是"这一条还没判完"，
#: 把它写进终态等于替 A 做了决定，而且行上会缺受控理由码（`schema` 的 validate 会先炸）。
#:
#: - `already_terminal`：早就判过；
#: - `missing_relevance`：还没写"为什么相关"；
#: - `missing_availability`：还没给可读性判定；
#: - `availability_unknown`：给了判定，但那一档是"没查" —— 要 A 去查，不是判拒；
#: - `metadata_only_without_locator`：仅题录但指不出处 —— 补一个 DOI/URL 就能重交。
_NOT_TERMINAL_CODES: tuple[str, ...] = (
    "already_terminal",
    "missing_relevance",
    "missing_availability",
    "availability_unknown",
    "metadata_only_without_locator",
)


def _decisions_from(plan: Mapping[str, Any], lit_ids: Mapping[str, str],
                    failures: Mapping[str, str]) -> list[dict]:
    """把 `admission_plan` 的结论 + 登记结果翻成 `apply_settlement` 要的决定。

    两个"不落终态"的码必须在这里筛掉，否则会把一次可重试的拒绝写成终态：
    `already_terminal`（这一条早就判过）与 `missing_relevance`（这一条还没写
    "为什么相关" —— 它得留在 pending，等补上证据或判拒）；2026-11-16 起同一张表
    还收 `missing_availability` / `availability_unknown` / `metadata_only_without_locator`
    （理由见 :data:`_NOT_TERMINAL_CODES`）。
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
        if str(r.get("code")) in _NOT_TERMINAL_CODES:
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
    """判收（逐条）：过 `admission_plan` 那几道闸 ⇒ 落 `qualified`，不注册、不发号。

    2026-11-16（Q1，业主口径「判收不注册，提交时才注册」）：本函数不再调
    `registrar`、不建 `literature` 行、不写 `lit_id`。它把这一条写成
    `status="qualified"` —— "有入库资格、还没有正式文献号"。发给模型的读数里
    `admitted[].lit_id` 因此是空串、`created=false`、`registered=0`：
    那三格说的是"还没进库"，不是"入库失败了"。

    超限即整笔拒绝（`on_over_cap="refuse_all"`，见 `admission_plan`）。
    逐条被挡的槽位不在这里终态（保持 `pending`，理由在 `refused[]` 里）：
    `lit.admit` 是"补一句 `new_content` 再试"的入口；终态留给 `admit_all` 的结算
    或调用方的 `lit.stage_reject`。

    报告：本函数只渲染进度报告（`phase="draft"`，报告头逐字标"未定稿"）——
    交报告那一刻的原件由 `admit_all` 落 `.submitted.md`，注册之后重渲染定稿。
    """
    plan = admission_plan(store, request_id=request_id, slots=slots, batch=batch,
                          new_content=new_content, cap=cap, on_over_cap="refuse_all",
                          require_readback=True)
    if not plan.get("ok"):
        return {**plan, "admitted": [], "registered": 0, "report": None, "report_path": None}
    # 判收只写证据（relevance / new_content / 重叠读数），一个号都不发。
    # `registrar` 仍然留在签名里：`lit.admit_all` 与它共用一个工具装配面，
    # 删掉这一格会让"判收"与"提交"在调用点长得不一样（判据只有本模块一处）。
    del registrar
    decisions = [{"slot": str(item["slot"]), "status": QUALIFIED,
                  "overlap_score": (item.get("overlap") or {}).get("overlap_score"),
                  "overlap_kind": (item.get("overlap") or {}).get("overlap_kind"),
                  "overlap_with": (item.get("overlap") or {}).get("overlap_with"),
                  "relevance": str((item.get("row") or {}).get("relevance") or ""),
                  "new_content": item.get("new_content")}
                 for item in plan.get("admitted") or []]
    if decisions:
        with store.tx("lit_candidates", actor=actor, note="lit.admit") as tx:
            apply_qualification(tx, decisions)
    done = []
    for item in plan.get("admitted") or []:
        ov = item.get("overlap") or {}
        # 键集合与冻结声明逐字一致（八格）：`lit_id` 空串是"还没号"，
        # 不是"少了一格"（声明那边由 FC-27 补丁改的是文字，不是键集合）。
        done.append({"slot": str(item["slot"]), "title": item["title"], "lit_id": "",
                     "created": False,
                     "overlap_score": ov.get("overlap_score"),
                     "overlap_kind": ov.get("overlap_kind"),
                     "overlap_with": ov.get("overlap_with"),
                     "new_content": item.get("new_content")})
    rep = write_report(store, plan["request_id"], phase="draft") if write_report_file else None
    return {
        "ok": True,
        "kind": "",
        "whole_call_refused": False,
        "reason": "",
        "request_id": plan["request_id"],
        "batch": plan["batch"],
        "call_size": plan["call_size"],
        "call_limit": plan["call_limit"],
        "delegation_admitted": plan["delegation_admitted"],
        "delegation_limit": plan["delegation_limit"],
        "admitted": done,
        "refused": [r for r in plan.get("refused") or []],
        "cleared": [],
        "registered": 0,
        "report": rep,
        "report_path": (rep or {}).get("path"),
    }


def admit_all(
    store: Store | None,
    *,
    registrar: Callable[[Mapping[str, Any]], dict],
    request_id: str | None = None,
    slots: Sequence[str] | None = None,
    new_content: str = "",
    cap: int | None = None,
    actor: str = "agent-A",
    write_report_file: bool = True,
) -> dict:
    """提交一批：判完之后的一次批量注册 + 回填 + 双阶段报告 + 清这一批的行。

    业主口径（Q1，2026-11-16）：「提交时系统自动为有入库资格的文献注册文献号后自动
    回填报告中入库文献的正式文献号 …… 系统做批量注册入库并得到映射关系回填报告的
    文献号 → 清空待入库文献表及文献 → 真正收工。」

    ## 提交粒度 = 批次，不是整委托（2026-11-17 FX3·甲）

    `slots` 点名"这一次提交覆盖哪些槽"；不给 = 本委托已判定的全部。一个委托可以
    有多批：15 槽判完 5 槽 ⇒ 交这 5 槽（带号定稿只含这 5 条），其余 10 槽保持
    `pending` 进下一批。批外未判的槽不拦这一笔；收工闸仍看全表，所以最后一笔要么
    把剩下的判完交掉、要么如实红。

    ## 提交闸：这一批内全判（Q16 的逐条判据一格没放宽）

    `require_judged=True` 的那一笔判据在 `admission_plan` 里，作用域是 `judged_scope`
    （= 这一批覆盖的槽，含已判拒的槽）。批内只要还有一条没判 ⇒ 整批拒，拒信逐条点名
    （`槽位 + 题名前 40 字`）并给做法。判过 = `judged_state != "pending"`
    （判收的 `qualified` 也算判过）。要入库的每一条仍要过可读性 / 抽读回执闸。

    ## 闸过了之后的六步，顺序不能换

    1. 取这一批判收未注册的行（`status == "qualified"`），过
       `admission_plan(on_over_cap="truncate", from_qualified=True)`：
       DOI 重复 / 高重叠无 `new_content` / 不可读 的逐条拒收；
       超配额的落 `rejected(over_cap)`；
    2. 交报告：渲染这一批的无号快照 `reports/lit-<rid>.submitted.md`（入库组不带号）。
       已存在就不覆盖（重跑幂等：注册前崩掉时那份原件不该被"注册后的行"洗掉）；
    3. 过 `report_violations(snapshot, phase="submitted")` —— 报告判据是提交动作的
       一部分；
    4. 批量注册：`_register(plan, registrar)` 一次性把这一批送进现有登记路径，
       拿回 `{slot: lit_id}`；再在同一个事务里 `apply_settlement` 把
       `qualified → admitted` 与 `lit_id` 回填到同一行（映射就在行上，
       不需要单独映射表）；
    5. 重渲染带号定稿 `reports/lit-<rid>.md`：只收"已提交过的行"（这一批 + 更早已清的
       批次），未判的 pending 不进定稿 —— 定稿不允许有待裁块（那是交付物，不是进度）；
    6. 清这一批：归档 `data/lit_candidates/archive-<rid>.jsonl`（整份委托，含未判行）+
       只给这一批的行打 `cleared_at` / `clear_reason`（不物理删，审计要留）。
       没提交的 pending 行不落 `cleared_at` ⇒ 收工闸的 `delegation_not_cleared` 仍红。

    "不许物理删"是结构性的：本函数一次 `delete` 都没有，清表只打标记。

    幂等：整份委托都清过表（每一行都有 `cleared_at`）再受控拒 `already_settled`；
    崩溃在 4 与 6 之间重跑时，快照不重写、只注册还停在 `qualified` 的那些行。
    """
    if store is None:
        raise LitStageError("未配置 store：入不了库（不是「都重复了」）", kind="no_store")
    rid = _resolve_request(store, request_id)
    if is_settled(store, rid):
        raise LitStageError(
            f"委托 {rid} 已经定稿并清表（归档在 "
            f"data/lit_candidates/archive-{rid}.jsonl）⇒ 受控拒 `already_settled`："
            f"重看读 reports/lit-{rid}.md 与那份归档；要重新判请开一次新委托",
            kind="already_settled", detail={"request_id": rid})
    rows = [fold_legacy(r) for r in _rows(store)
            if str(r.get("request_id") or "") == rid]
    by_slot = {str(r.get("slot") or ""): r for r in rows}
    target = submission_slots(rows, slots)
    unknown = [s for s in target if s not in by_slot]
    if unknown:
        outside = [s for s in unknown if s in {str(r.get("slot")) for r in _rows(store)}]
        raise LitStageError(
            f"这些槽位不在**本次委托**（{rid}）的待新增列表里：{unknown}"
            + (f"；其中 {outside} 属于别的委托（列表按委托重置，旧委托的行不参与本次筛选）"
               if outside else "（序号不复用，请用 lit.stage_list 查一遍）"),
            kind="unknown_slot", detail={"slots": unknown, "request_id": rid},
        )
    qualified_slots = [s for s in target
                       if str(by_slot[s].get("status") or "") == QUALIFIED]
    # 提交闸跑在这两处之前：即使一条 pending 都没有也要跑 —— 否则"已经判完"
    # 与"还没判完但一行 pending 都不剩（判收了却没有 relevance）"在盘上同形，
    # 而后者正是存量那 33 条的形状。
    plan = admission_plan(store, request_id=rid, slots=qualified_slots,
                          judged_scope=target, new_content=new_content,
                          cap=cap, on_over_cap="truncate", require_judged=True,
                          require_readback=True, from_qualified=True)
    if not plan.get("ok"):
        return {**plan, "admitted": [], "registered": 0, "report": None, "report_path": None}
    batch_rows = [by_slot[s] for s in target]
    # ---- ② 交报告（无号原件）+ ③ 报告判据 --------------------------------
    snapshot = _write_report_snapshot(store, rid, batch_rows)
    bad = report_violations(snapshot["text"], phase="submitted")
    if bad:
        raise LitStageError(
            "交报告（无号原件）没通过报告判据 ⇒ 不注册、不发行号：" + "；".join(bad),
            kind="report_violations",
            detail={"violations": bad, "path": snapshot["path"]})
    # ---- ④ 批量注册 + 回填（同一事务） ------------------------------------
    lit_ids, failures, got_all = _register(plan, registrar)
    decisions = _decisions_from(plan, lit_ids, failures)
    with store.tx("lit_candidates", actor=actor, note="lit.admit_all") as tx:
        apply_settlement(tx, decisions)
        # FX3·甲：结算之后不再把批外的 pending 折成 rejected(not_screened) ——
        # 它们保持 pending 进下一批（收工闸按全表看，所以"没清完"仍会拦）。
        settled = [dict(r) for r in tx.rows("lit_candidates")
                   if str(r.get("request_id") or "") == rid]
    settlement_mismatch(store, decisions, request_id=rid)
    settled.sort(key=lambda r: str(r.get("slot") or ""))
    # ---- ⑤ 重渲染带号定稿 + 报告判据 --------------------------------------
    # 定稿只收"已提交过的行"：这一批 + 更早已清的批次；批外未判的 pending 不进定稿
    # （报告判据要求待裁 0 条），否则一份没判完的委托会写出"0 篇待裁"的假定稿。
    submitted = set(target)
    reported = [r for r in settled
                if str(r.get("slot") or "") in submitted
                or str(r.get("cleared_at") or "").strip()]
    rep = write_report(store, rid, rows=reported, phase="final") if write_report_file else None
    if write_report_file:
        final_text = report_path(store, rid).read_text(encoding="utf-8")
        # 拦门只拦"这一次提交注册的那些行"（按 `lit:<号>` 认）：更早已入库的行若
        # 缺可得性档位，那是 AR1 之前的历史读数 —— 拿它拦今天的提交会让任何老工作区
        # 永远提交不了；那些行只留在 `report_violations()` 的读数里（不拦门那一档）。
        registered = {str(x) for x in lit_ids.values() if str(x)}
        bad_final = [
            v for v in report_violations(final_text, phase="final", blocking=True)
            if not (re.search(r"`lit:([^`]+)`", v)
                    and re.search(r"`lit:([^`]+)`", v).group(1) not in registered)
        ]
        if bad_final:
            raise LitStageError(
                "定稿报告没通过报告判据 ⇒ 不往下收工（行已注册、未清表；可重跑）："
                + "；".join(bad_final),
                kind="report_violations",
                detail={"violations": bad_final, "path": (rep or {}).get("path")})
    # ---- ⑥ 归档 + 清这一批 ------------------------------------------------
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
    closed = clear_delegation(store, rid, actor=actor, mapping=done, only_slots=target)
    refused = list(plan.get("refused") or [])
    for slot, why in failures.items():
        refused.append(_refusal(slot, next((i["row"].get("title") for i in plan["admitted"]
                                           if str(i["slot"]) == slot), ""),
                                why, "registration_failed"))
    # 这一批之后的全表待裁读数（按委托分组）：没交的槽仍 pending，A 照它进下一批。
    left = pending_all_delegations(_rows(store), current=rid)
    return {
        "ok": True,
        "kind": "",
        "whole_call_refused": False,
        "reason": "",
        "request_id": rid,
        "submitted": list(target),
        "call_size": plan["call_size"],
        "call_limit": plan["call_limit"],
        "delegation_admitted": plan["delegation_admitted"] + len(done),
        "delegation_limit": plan["delegation_limit"],
        "pending_total": left["total"],
        "pending_by_delegation": left["by_delegation"],
        "pending_scope_note": pending_scope_note(left, exclude=rid),
        "admitted": done,
        "refused": refused,
        "cleared": list(plan.get("cleared") or []),
        "registered": len(done),
        "report": rep,
        "report_path": (rep or {}).get("path"),
        "snapshot_path": snapshot["path"],
        "snapshot_rel_path": snapshot["rel_path"],
        "archive_path": closed["archived"]["path"],
        "archive_rel_path": closed["archived"]["rel_path"],
        "cleared_rows": closed["cleared"],
    }


# --------------------------------------------------------------------------- 委托报告


def report_path(store: Store, request_id: str) -> Path:
    """报告落点：`<工作区>/reports/lit-<request_id>.md`（下一次委托的 D/H 直接 `fs.read`）。"""
    return Path(store.root) / REPORT_DIR / f"lit-{request_id}.md"


def report_snapshot_path(store: Store, request_id: str) -> Path:
    """「交报告」那一刻的无号原件：`<工作区>/reports/lit-<rid>.submitted.md`。"""
    return Path(store.root) / REPORT_DIR / f"lit-{request_id}{REPORT_SNAPSHOT_SUFFIX}"


def _report_context(store: Store) -> tuple[dict, dict]:
    """报告的两份旁路读数：可读性判定（`lit_availability`）与抽读回执（`lit_reads`）。"""
    tiers = LAV.tiers_by_slot(store.root)
    reads = LAV.receipts_by_slot(store.root)
    for slot, receipt in reads.items():
        # 只补 A 没报过的那一格：A 报 `metadata_only` 时允许带一条 `extract_failed`
        # 尝试回执（AR1），覆盖会让报告写出一档与准入判定相反的可得性。
        if slot not in tiers and _tier_of_receipt(receipt):
            tiers[slot] = _tier_of_receipt(receipt)
    return tiers, reads


def _write_report_text(store: Store, path: Path, text: str) -> None:
    """报告落盘（先 `.tmp` 再 `os.replace`：不留半截报告）。"""
    _atomic_write(path, text)


def _write_report_snapshot(store: Store, request_id: str,
                           rows: Sequence[Mapping[str, Any]]) -> dict:
    """落「交报告」那一刻的无号原件（已存在就不覆盖 —— 重跑幂等）。

    为什么"已存在就不覆盖"：注册之后重跑 `admit_all` 时，行已经变成 `admitted`，
    再按"合格入库组"渲染会得到一份空的入库组 —— 那份原件必须留的是
    "交报告那一刻"的行，不是"注册之后"的行。
    """
    rid = str(request_id or "").strip()
    path = report_snapshot_path(store, rid)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
    else:
        tiers, reads = _report_context(store)
        _instance, writer = _readback_actor()
        text = report_markdown(rid, rows, availability=tiers, reads=reads,
                               phase="submitted", writer=writer,
                               writer_instance=_instance)
        _write_report_text(store, path, text)
    return {"path": path.as_posix(), "rel_path": f"{REPORT_DIR}/{path.name}",
            "chars": len(text), "text": text, "request_id": rid}


def _refresh_report_if_present(store: Store, request_id: str) -> dict | None:
    """报告过期（Q1 第 ⑨ 条）：判完一条之后，若那份报告已经在盘上就重渲染一次。

    "已经在盘上"是判据：A 没交过报告时不要凭空造一份（报告是交付物，
    不是每一次判定的副产品）；而交过之后不重渲染，它就会静默停在
    "待裁 15 条"（真机 `projects/lp-ball-2/reports/lit-r-000008.md` 就是那个形态：
    盘上的行 07:45 已经判拒，报告还写着 15 条待裁）。

    已清表的委托不重渲染（`is_settled` ⇒ 那份是定稿，改它等于改交付物）。
    异常一律吞掉：报告刷新失败不许把一次成功的判定带坏（与 run_once 同一条纪律）。
    """
    rid = str(request_id or "").strip()
    if not rid or is_settled(store, rid):
        return None
    if not report_path(store, rid).is_file():
        return None
    try:
        return write_report(store, rid, phase="draft")
    except Exception:  # noqa: BLE001 - 旁路：报告刷新失败不改判定结果
        return None


def _tier_of_receipt(receipt: Mapping[str, Any] | None) -> str:
    """抽读回执能替 A 报的那一档（只有 `extract_failed` 一档）。

    为什么只补这一档：抽读失败是机器判得出的事实（抽出来的不是可读文本），
    不需要等 A 的一句话；而"抽出来可读"不等于" A 读过" —— 那一档要抽读 + `fs.read`
    两道证据（`check_read`），不能由回执替 A 声明。

    调用点只把它当缺省填写：A 已经报过的档位不覆盖（2026-11-16 AR1 之后
    `metadata_only` 允许带一条 `extract_failed` 尝试回执，覆盖会让报告写出一档
    与准入判定相反的读数）。
    """
    if receipt and str(receipt.get("tier") or "") == LR.FULLTEXT_EXTRACT_FAILED:
        return LAV.EXTRACT_FAILED
    return ""


def _receipt_summary(receipt: Mapping[str, Any] | None) -> str:
    """报告那一行「回执」：`data/lit_reads.jsonl` 里这一条那一行的摘要。

    为什么必须以回执为源、而不是报告自己另拼一句：业主 2026-11-16 裁定（AR1）
    "抽读回执落进 A 稿，作为批准入库或拒绝入库的理由栏" —— 报告里的字数 / 指纹 /
    抽读件路径 / 时间必须与台账逐字对得上，读者（D/H/人）不必回头猜报告是不是
    另写了一份。所以 `write_report` 现读 `litavail.receipts_by_slot`，这里只做排版。

    没有回执 ⇒ 写"无 + 零读取尝试"：缺省不是"读过"，也不是空白。
    """
    if not receipt:
        return "无（`data/lit_reads.jsonl` 里没有这一条 —— 零读取尝试）"
    tier = str(receipt.get("tier") or "")
    at = str(receipt.get("at") or "")
    source = str(receipt.get("source") or "")
    if tier == LR.FULLTEXT_OK:
        parts = [f"抽读档位 {tier}", f"读过 {int(receipt.get('chars') or 0)} 字"]
        sha = str(receipt.get("sha256") or "")
        if sha:
            parts.append(f"指纹 sha256:{sha[:12]}")
        text = str(receipt.get("text") or receipt.get("text_abs") or "")
        if text:
            parts.append(f"抽读件 {text}")
        if source:
            parts.append(f"来源 {source}")
        if at:
            parts.append(f"时间 {at}")
        return "；".join(parts)
    if tier == LR.FULLTEXT_EXTRACT_FAILED:
        parts = ["抽读档位 extract_failed（没拿到可读字节）",
                 f"尝试过 {source or '（未记来源）'}（{receipt.get('note') or 'text.extract 失败'}）"]
        if at:
            parts.append(f"时间 {at}")
        return "；".join(parts)
    return f"抽读档位 {tier or '（空）'}（不是 ok / extract_failed 的受控取值）"


def _doi_or_provider(row: Mapping[str, Any]) -> str:
    """报告条目那一行末尾的出处：DOI 优先，没有就写 provider。"""
    return str(row.get("doi") or f"provider={row.get('provider') or '?'}")


def _year_text(row: Mapping[str, Any]) -> str:
    """报告条目里的年份：没有就写「年份不详」（不写 None）。"""
    return str(row.get("year") if row.get("year") is not None else "年份不详")


def _numbered_entry(row: Mapping[str, Any], *, tiers: Mapping[str, str],
                    reads: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """已入库的一条（带正式文献号）：``- `lit:000010` 《题名》（年）doi`` + 三栏。"""
    slot = str(row.get("slot") or "")
    lit_id = str(row.get("lit_id") or "?")
    out = [f"- `lit:{row.get('lit_id')}` 《{row.get('title')}》（{_year_text(row)}）"
           f" {_doi_or_provider(row)}",
           "  判定：批准入库",
           f"  回执：{_receipt_summary(reads.get(slot))}"]
    why = str(row.get("relevance") or row.get("new_content") or "").strip()
    if why:
        out.append(f"  理由（相关性）：{why}")
    else:
        out.append("  理由（相关性）：未写（缺的是 `lit:" + lit_id + "` 这一条的 "
                   "relevance / new_content）")
    out.append(f"  可得性：{LAV.describe_tier(tiers.get(slot, ''))}")
    return out


def _unnumbered_entry(row: Mapping[str, Any], *, tiers: Mapping[str, str],
                      reads: Mapping[str, Mapping[str, Any]], verdict: str) -> list[str]:
    """不带号的一条（判收未注册 / 交报告原件）：条目行只有文献信息，一个号都没有。"""
    slot = str(row.get("slot") or "")
    out = [f"- 《{row.get('title')}》（{_year_text(row)}） {_doi_or_provider(row)}",
           f"  判定：{verdict}",
           f"  回执：{_receipt_summary(reads.get(slot))}"]
    why = str(row.get("relevance") or row.get("new_content") or "").strip()
    if why:
        out.append(f"  理由（相关性）：{why}")
    else:
        out.append("  理由（相关性）：未写（缺的是这一条的 relevance / new_content）")
    out.append(f"  可得性：{LAV.describe_tier(tiers.get(slot, ''))}")
    return out


def _rejected_entry(row: Mapping[str, Any], *, tier_label: str,
                    receipt_text: str, twin_lit: str) -> list[str]:
    """未入库的一条：只留文献信息与理由（业主口径：被拒的没有号）。

    临时号（`cand:<槽位>`）与槽位号都不出现 —— 报告不是台账，读者要的是
    "这一篇为什么没进来"，"它是第几号槽"只对 `lit.stage_list` 有用。
    """
    code = str(row.get("reason_code") or "(未登记理由码)")
    detail = (str(row.get("reject_reason") or "").strip()
              or str(row.get("withdrawn_reason") or "").strip()
              or str(row.get("clear_reason") or "").strip())
    code_text = S.CANDIDATE_REASON_LABELS.get(code, code)
    tail = (f"（同一篇已在 `lit:{twin_lit}` —— 这是它的另一个槽位，属重复登记；条数不因此改）"
            if twin_lit else "")
    return [f"- 《{row.get('title')}》（{_year_text(row)}） {_doi_or_provider(row)} — 理由：{code}"
            f"（{code_text}）" + (f"；{detail}" if detail else "") + tail
            + f"；可得性：{tier_label}",
            "  判定：拒绝入库",
            f"  回执：{receipt_text}"]


def _pending_entry(item: Mapping[str, Any], *, tier_label: str,
                   receipt_text: str) -> list[str]:
    """待裁的一条：题名 + 为什么还停着 + 回执 + 可得性。同样不带槽位号。"""
    return [f"- 《{T.clip(str(item.get('title') or ''), UNDECIDED_TITLE_CHARS)}》"
            f" — {item.get('why')}；可得性：{tier_label}",
            "  判定：待裁（还没判）",
            f"  回执：{receipt_text}"]


def report_markdown(request_id: str, rows: Sequence[Mapping[str, Any]],
                    *, generated_at: str = "",
                    availability: Mapping[str, str] | None = None,
                    reads: Mapping[str, Mapping[str, Any]] | None = None,
                    phase: str = "draft", writer: str = "",
                    writer_instance: str = "") -> str:
    """委托报告正文（四个块；`phase` 决定"入库组"是带号还是无号）。

    `writer`（K16 / AL-07 / AL-08）是这一版报告的写者（`agent-A-<实例>`；没有身份
    的那一档是空串 —— 报告头如实写"未记"，不编一个人）。报告是交付物，读者要能回答
    "这一版是谁渲染的、是不是我这一版"：改前报告头只有委托号 / 状态 / 时间，于是
    "该不该刷新"落成"谁最后判谁说了算"（AL-08）。

    ## 两个渲染时刻（业主 Q1 口径）

    - `phase="submitted"`：交报告那一刻的原件（`reports/lit-<rid>.submitted.md`）。
      `## 已入库` 一块列的是"有入库资格"的那些条，一个号都没有（`lit_id` 是
      提交之后才由系统批量发出来的）。这一份是"回填"的对照物：注册之后重渲染的
      定稿与它应当同事实、只差号；
    - `phase="final"`：定稿（`reports/lit-<rid>.md`）。`## 已入库` 每条带
      `` `lit:NNNNNN` ``（回填后的正式号），`## 未入库` 每条只留文献信息与理由；
    - `phase="draft"`：进度（`lit.admit` / `reject` 之后的中间态）。`## 已入库`
      列已注册的行（通常 0 条），`## 待注册` 列判收未注册的那些（无号）。

    ## 四个块都必须有（空块写 `（无）`）

    `已入库` / `待注册` / `未入库` / `待裁` —— 少一块，"这一块是空的"与"这一块被忘了写"
    在报告上就同形。`待裁` 是要害：没有它，"A 还没读的那几条"与"根本没检索到"同形，
    而它们下一步的动作完全不同。

    ## 报告里没有临时号（业主逐字：「写报告时不用临时文献号」）

    四个块一处都不印槽位号，也不印 `cand:<槽位>`：正式号是 `lit:NNNNNN`，
    临时号只活在 `lit.stage_list` 与 `text.extract` 的入参里（`cand_ref` 是它唯一的构造点）。
    """
    if phase not in ("draft", "submitted", "final"):
        raise LitStageError(f"phase 只能是 draft / submitted / final，收到 {phase!r}",
                            kind="bad_phase")
    stamp = generated_at or S.now_iso()
    tiers = dict(availability or {})
    read_by_slot = dict(reads or {})
    folded = [fold_legacy(r) for r in rows]
    admitted = [r for r in folded if str(r.get("status")) == "admitted"]
    qualified = [r for r in folded if str(r.get("status")) == QUALIFIED]
    other = [r for r in folded if str(r.get("status")) == "rejected"]
    # 待裁块自己按 `judged_state` 数（不走 `undecided`）：那一格是提交闸的读数，
    # 反真空会打桩它；报告是交付物，不能跟着被打桩的那一份一起少说一条。
    waiting = [{"slot": str(r.get("slot") or ""), "title": str(r.get("title") or ""),
                "status": _pending_why(r)[0], "why": _pending_why(r)[1]}
               for r in rows if judged_state(r) == "pending"]
    # 已入库的篇数按去重后的 lit_id 计数，不是按行数：两条候选行都可能判重命中
    # 同一个 literature 行（`source_request_ids` 累积到同一行），按行数报
    # "已入库 2 篇"而库里只多了一篇，那是假读数。lit_id 才是"库里多了几篇"的单位。
    admitted_ids = sorted({str(r.get("lit_id") or "") for r in admitted} - {""})
    record_counts = {s: 0 for s in CANDIDATE_RECORDS}
    for r in folded:
        state = str(r.get("status") or "")
        if state in record_counts:
            record_counts[state] += 1
    lines: list[str] = [
        f"# 文献检索委托 {request_id} 的入库报告",
        "",
        f"- 委托：`{request_id}`",
        f"- 报告状态：{_PHASE_LABELS[phase]}",
        f"- 生成时间：{stamp}",
        # 这一版的写者（K16 / AL-08）：报告是交付物，"谁渲染的"必须留在报告上 ——
        # 否则两个 A 实例共读一份报告时，"过期不过期"落成"谁最后判谁说了算"。
        # 没有身份的那一档（直调 / 夹具）如实写"未记"，不编一个 actor 出来。
        f"- 写者：{writer or '（未记：这次渲染没有调用方身份）'}",
        # 实例轴单独一行：角色级 actor（`agent-A`）回答不了"是哪一个实例渲染的"，
        # 而 AL-08 要的正是这一格（`writer` 里带了实例，这里再单列一格供机器读）。
        f"- 写者实例：{writer_instance or '（未记）'}",
        # 盘点数四档（盘上的行状态）：历史的 cleared / withdrawn 已经折进 rejected。
        "- 盘点：" + "、".join(f"{s}={record_counts[s]}" for s in CANDIDATE_RECORDS)
        + "（按行上的 status 数；历史的 cleared 折进 rejected+over_cap、withdrawn 折进 "
          "rejected+withdrawn_by_reviewer）",
        # 可得性（可读性判定）四档的图例：每一条都会带这一栏，读者不必回头猜档名。
        "- 可得性（可读性判定四档）：" + " / ".join(
            f"{tier} {LAV.TIER_LABELS[tier]}" for tier in LAV.AVAILABILITY_TIERS),
        "",
    ]
    # ---- 块 ①：已入库（定稿带号 / 交报告原件无号）
    if phase == "submitted":
        lines += [f"## 已入库（{len(qualified)} 篇）", ""]
        if not qualified:
            lines.append("（无）")
        for r in qualified:
            lines += _unnumbered_entry(r, tiers=tiers, reads=read_by_slot,
                                       verdict="有入库资格（本份是交报告那一刻的原件："
                                               "正式文献号由系统在提交后批量注册并回填）")
    else:
        lines += [f"## 已入库（{len(admitted_ids)} 篇）", ""]
        if not admitted:
            lines.append("（无）")
        missing_relevance: list[str] = []
        for r in admitted:
            lines += _numbered_entry(r, tiers=tiers, reads=read_by_slot)
            if not str(r.get("relevance") or r.get("new_content") or "").strip():
                missing_relevance.append(str(r.get("lit_id") or ""))
        if missing_relevance:
            lines.append("- 缺相关性说明的条目（" + str(len(missing_relevance)) + " 篇）："
                         + "、".join(f"`lit:{lit_id}`" for lit_id in missing_relevance)
                         + " —— 这几条在 `## 待裁` 块里，判完（补 relevance 或判拒）才放行")
    # ---- 块 ②：待注册（只有进度报告会非空）
    lines += ["", f"## 待注册（{len(qualified) if phase == 'draft' else 0} 篇）", ""]
    if phase == "draft" and qualified:
        for r in qualified:
            lines += _unnumbered_entry(r, tiers=tiers, reads=read_by_slot,
                                       verdict="有入库资格（待提交注册，暂无号）")
    else:
        lines.append("（无）")
    # ---- 块 ③：未入库（只留文献信息与理由，没有号）
    lines += ["", f"## 未入库（{len(other)} 篇）", ""]
    if not other:
        lines.append("（无）")
    admitted_ident: dict[str, str] = {}
    for r in admitted:
        admitted_ident.setdefault(candidate_identity(r.get("title"), r.get("doi")),
                                  str(r.get("lit_id") or ""))
    for r in other:
        slot = str(r.get("slot") or "")
        twin = admitted_ident.get(candidate_identity(r.get("title"), r.get("doi")), "")
        lines += _rejected_entry(r, tier_label=LAV.describe_tier(tiers.get(slot, "")),
                                 receipt_text=_receipt_summary(read_by_slot.get(slot)),
                                 twin_lit=twin)
    # ---- 块 ④：待裁（同样不带槽位号）
    lines += ["", f"## 待裁（{len(waiting)} 条）", ""]
    if not waiting:
        lines.append("（无）")
    for item in waiting:
        slot = str(item.get("slot") or "")
        lines += _pending_entry(item, tier_label=LAV.describe_tier(tiers.get(slot, "")),
                                receipt_text=_receipt_summary(read_by_slot.get(slot)))
    lines.append("")
    return "\n".join(lines)


#: 报告头那一行「报告状态」的三种写法（两个渲染时刻 + 进度）。
_PHASE_LABELS: dict[str, str] = {
    "draft": "进度（**未定稿**）—— 判完之后由 `lit.admit_all` 提交：先落无号原件、"
             "批量注册后重渲染定稿；本份里的「待注册」组提交之后才有正式号",
    "submitted": "**交报告**（原件）—— 入库组按「有入库资格」列出、**不带号**；"
                 "系统在提交后批量注册并把正式文献号回填到 reports/lit-<委托>.md",
    "final": "**定稿**（已回填正式文献号）—— 入库组每条带 `lit:NNNNNN`，"
             "未入库组只留文献信息与理由（无号）",
}

#: 报告头那一行「写者」的读法（写者名的唯一解析点：`_report_writer_of` 用它）。
_REPORT_WRITER_LINE = re.compile(r"^-\s*写者：(.+)$", re.M)


def _report_writer_of(store: Store, request_id: str) -> str:
    """盘上那一版报告头写的写者（没有报告 / 读不出来 ⇒ 空串，不编一个）。

    只读不写：它是 `write_report` 返回的 `previous_writer` 的来源，让"这一版覆盖了
    谁那一版"在回执里看得见（K16 / AL-08）。读不出来不抛 —— 覆盖报告这件事不该因为
    *旧*那一份读不动而失败。
    """
    for path in (report_path(store, request_id), report_snapshot_path(store, request_id)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hit = _REPORT_WRITER_LINE.search(text)
        if hit:
            return str(hit.group(1)).strip()
    return ""


def write_report(store: Store, request_id: str, *, rows: Sequence[Mapping[str, Any]] | None = None,
                 generated_at: str = "", phase: str = "draft") -> dict:
    """把委托报告写到 `reports/lit-<request_id>.md`（`phase="submitted"` 写无号原件）。

    两个渲染时刻（业主 Q1）：`submitted` 落 `lit-<rid>.submitted.md`（交报告的原件），
    `final` 落 `lit-<rid>.md`（注册回填之后的定稿），`draft` 也落正式路径但报告头逐字
    标"未定稿"（进度）。"回填"就是再调一次本函数：`report_markdown` 是纯函数，
    所以不需要占位符、字符串替换或转义。

    两条受控拒（第 ⑨ 条）：
    - 已清表的委托（归档在盘上）再要求写报告 ⇒ `already_settled`：定稿是交付物，
      清表之后重渲染只会得到一份"0 篇"的空报告（`body_rows` 现读）；
    - `phase="final"` 时还有 `qualified` 行 ⇒ `not_registered`：定稿的入库组必须每条
      带号，而判收未注册的行没有号 —— 让它进定稿就是把"有资格"冒充成"已入库"。
    """
    rid = str(request_id or "").strip()
    if not rid:
        raise LitStageError("写报告必须知道是哪一次委托（request_id 为空）",
                            kind="no_delegation")
    if phase not in ("draft", "submitted", "final"):
        raise LitStageError(f"phase 只能是 draft / submitted / final，收到 {phase!r}",
                            kind="bad_phase")
    if is_settled(store, rid):
        raise LitStageError(
            f"委托 {rid} 已经定稿并清表（归档在 data/lit_candidates/archive-{rid}.jsonl）"
            "⇒ 受控拒 `already_settled`：定稿报告不再重渲染（重渲染会得到一份 0 篇的空报告；"
            "进度版更不许覆盖定稿）。要看就读 reports/lit-<委托>.md 与那份归档",
            kind="already_settled", detail={"request_id": rid})
    body_rows = list(rows) if rows is not None else [
        r for r in _rows(store) if str(r.get("request_id") or "") == rid]
    body_rows.sort(key=lambda r: str(r.get("slot") or ""))
    if phase == "final" and any(str(r.get("status") or "") == QUALIFIED
                                for r in (fold_legacy(x) for x in body_rows)):
        raise LitStageError(
            f"委托 {rid} 里还有判收未注册（qualified）的行 ⇒ 现在写不了定稿："
            "定稿的入库组必须每条带正式文献号（先 `lit.admit_all` 批量注册）",
            kind="not_registered", detail={"request_id": rid})
    # 可读性那一栏从旁路台账现读（报告是交付物：它必须与闸审的是同一份判定）。
    tiers, reads = _report_context(store)
    # 这一版的写者（K16 / AL-07 / AL-08）：谁渲染谁负责。实例从工具调用的身份挂点读，
    # 与回执、候选行、签同一根轴；没有身份的那一档是空串（报告头写"未记"）。
    instance, writer = _readback_actor()
    previous = _report_writer_of(store, rid)
    text = report_markdown(rid, body_rows, generated_at=generated_at,
                           availability=tiers, reads=reads, phase=phase,
                           writer=writer, writer_instance=instance)
    path = report_snapshot_path(store, rid) if phase == "submitted" else report_path(store, rid)
    _write_report_text(store, path, text)
    # 与报告标题同一口径：去重后的 lit_id（两条候选命中同一行时只算一篇）。
    admitted = len({str(r.get("lit_id") or "") for r in body_rows
                    if judged_state(r) == "admitted"} - {""})
    record = {s: 0 for s in CANDIDATE_RECORDS}
    for r in (fold_legacy(x) for x in body_rows):
        state = str(r.get("status") or "")
        if state in record:
            record[state] += 1
    return {
        "path": path.as_posix(),
        "rel_path": f"{REPORT_DIR}/{path.name}",
        "chars": len(text),
        "admitted": admitted,
        "not_admitted": record["rejected"],
        "undecided": record["pending"],
        "request_id": rid,
        #: 这一版是谁渲染的（K16 / AL-07 / AL-08）：`writer` 是 actor 名
        #: （`agent-A-<实例>`；没有身份 ⇒ 空串）、`instance` 是那一根实例轴、
        #: `previous_writer` 是覆盖之前盘上那一版报告头的写者（没有旧报告 ⇒ 空串）。
        "writer": writer,
        "writer_instance": instance,
        "previous_writer": previous if previous != writer else "",
    }


def report_violations(text: str, *, phase: str = "final",
                      blocking: bool = False) -> list[str]:
    """委托报告的判据：四块都在、都非空、没有临时号、理由/号/可得性逐条在场。

    2026-11-16（Q1）加三条（业主口径）：

    - 报告正文不出现临时号：一处 `槽位 NNNNNN` / `cand:<槽位>` 都不许有
      （"写报告时不用临时文献号"）。这也是"去号"那条改动的反真空落点：
      把未入库行改回带槽位 ⇒ 这里必红；
    - 两个渲染时刻各自的号规则：`phase="final"` 的已入库组每条必须有
      `` `lit:``（回填真的发生了）；`phase="submitted"` 的已入库组每条必须
      没有 `` `lit:``、且逐字带"有入库资格"（交报告那一刻还没号）；
    - `## 待注册` 块必须在（进度报告里它承的是"判收未注册"那一组，空时写（无））。

    返回违规描述列表（空 = 通过）。由测试的正控与负控直接打它 ——
    负控若不走同一条判据，就证明不了"去掉一块会红"。

    `blocking=True` 是拦门的那一档（`admit_all` 的提交动作就是这么调的）：
    它去掉只记读数、不拦门的那一条（`_relevance_violations`："已入库的 relevance
    全空"是读数 —— 存量 33 条现场就是这个形状，拿它拦提交会让历史工作区永远提交不了）。
    两档共用同一份检查实现，差别只在"哪一条算拦门"。
    """
    bad: list[str] = []
    body = str(text or "")
    if not body.strip():
        return ["报告是空的"]
    if phase not in ("draft", "submitted", "final"):
        return [f"phase 只能是 draft / submitted / final，收到 {phase!r}"]
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
    for name in ("已入库", "待注册", "未入库", "待裁"):
        hit = next((k for k in sections if k.startswith(name)), None)
        if hit is None:
            bad.append(f"缺 `## {name}` 块（这一块是交付物的一部分，不是可选）")
            continue
        if not sections[hit].strip():
            bad.append(f"`## {hit}` 块是空的（没有条目时也要写（无））")
    # ---- 临时号：报告正文一处都不许有（业主逐字：写报告时不用临时文献号）
    if _REPORT_SLOT_NUMBER.search(body):
        line = next((ln for ln in body.splitlines()
                     if _REPORT_SLOT_NUMBER.search(ln)), "")
        bad.append(f"报告正文里出现了槽位号（临时号不许进报告）：{line.strip()[:60]}")
    if "cand:" in body:
        line = next((ln for ln in body.splitlines() if "cand:" in ln), "")
        bad.append(f"报告正文里出现了 `cand:` 临时号：{line.strip()[:60]}")
    # ---- 未入库：理由必须是受控取值
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
    # ---- 已入库：两个渲染时刻各自的号规则
    admitted_text = next((v for k, v in sections.items() if k.startswith("已入库")), "")
    if phase == "submitted":
        entries = _report_blocks(admitted_text, numbered=False)
        # 原件里"入库组"的条数必须等于报告头「盘点」那一行的 qualified 数 ——
        # 这样"把有资格的那些漏掉"不会因为块里恰好没条目而静默通过。
        declared = _record_count(body, QUALIFIED)
        if declared is not None and declared != len(entries):
            bad.append(f"交报告原件的「已入库」块有 {len(entries)} 条，而盘点行写着 "
                       f"qualified={declared} ⇒ 这一组没把有入库资格的那些都写进去")
        for key, body_text in entries:
            if "`lit:" in body_text:
                bad.append(f"交报告原件里出现了正式文献号（这一刻还没有号）：《{key}》")
            if "有入库资格" not in body_text:
                bad.append(f"交报告原件的这一条没有「有入库资格」：《{key}》")
        bad.extend(_availability_violations(admitted_text, numbered=False))
    else:
        for line in admitted_text.splitlines():
            if line.strip().startswith("- ") and "`lit:" not in line:
                bad.append(f"已入库的这一条没有 lit_id：{line.strip()[:60]}")
        if not blocking:
            bad.extend(_relevance_violations(admitted_text))
        bad.extend(_availability_violations(admitted_text))
    # ---- 待注册 / 待裁：只要求"不带号"（它们本来就没有正式号）
    for name in ("待注册", "待裁"):
        block = next((v for k, v in sections.items() if k.startswith(name)), "")
        for line in block.splitlines():
            entry = line.strip()
            if entry.startswith("- ") and "`lit:" in entry:
                bad.append(f"`## {name}` 的那一条带着正式文献号（这一组此刻没有号）：{entry[:60]}")
    # ---- 两个渲染时刻都不许带"还没判的"：交报告/定稿是"判完之后"的产物
    if phase in ("submitted", "final"):
        waiting = next((k for k in sections if k.startswith("待裁")), "待裁")
        pending = _block_count(waiting)          # 条数在块标题里（`## 待裁（0 条）`）
        if pending is None:
            bad.append("`## 待裁` 的块标题读不出条数（判据不许因为读不到就通过）")
        elif pending > 0:
            bad.append(f"`## 待裁` 还有 {pending} 条：交报告/定稿是判完之后才写的"
                       "（提交闸要求 0 条待裁）")
    return bad


def _block_count(text: str) -> int | None:
    """块标题里的条数：`（2 条）` / `（3 篇）`（读不到 ⇒ `None`，不是 0）。"""
    hit = re.search(r"（\s*(\d+)\s*[条篇]\s*）", str(text or ""))
    return int(hit.group(1)) if hit else None


#: 报告头「盘点」那一行里某一档的行数：`qualified=2`。读不到 ⇒ `None`（不是 0）。
_REPORT_RECORD_COUNT = re.compile(r"\b([a-z]+)=(\d+)")


def _record_count(text: str, name: str) -> int | None:
    """从报告头「盘点：…」那一行读某一档的行数（读不到 ⇒ `None`，不是 0）。"""
    for line in str(text or "").splitlines():
        if not line.strip().startswith("- 盘点："):
            continue
        got = dict((k, int(v)) for k, v in _REPORT_RECORD_COUNT.findall(line))
        return got.get(str(name))
    return None


#: 报告里一行「可得性」的档位记号：`可得性：仅题录（metadata_only）`。
_REPORT_AVAILABILITY = re.compile(r"可得性：[^（\n]*（(" + "|".join(LAV.AVAILABILITY_TIERS)
                                  + r")）")

#: 报告正文里"槽位号"的形态（`槽位 000029`）：临时号不许进报告，这一条是它的判据。
#:
#: 只咬"槽位 + 四/六位数"这一种形态，不咬散文里的「另一个槽位」——
#: 那不是号，是"同一篇占了两个位置"这句话（重复登记的尾注要用它）。
_REPORT_SLOT_NUMBER = re.compile(r"槽位\s*(?:" + S.ID_OR_LEGACY_PATTERN + r")")


def _availability_violations(admitted_text: str, *, numbered: bool = True) -> list[str]:
    """「已入库」这一块逐条要有可得性栏，且那一档必须允许入库（业主裁定 ⑥ / ③）。

    为什么这条要进 `report_violations` 而不是只写在正文里：`## 已入库` 一块是
    "文献库里多了哪几篇"的唯一交付物。这一栏缺了，或者写着 `extract_failed` /
    `unknown`，"入库的文献质量有保证"这句话就没有可核对的读数了 —— 而那正是
    业主裁定 9 / 15 要的那一层。

    `numbered=False` 那一档是"交报告原件"：条目行没有 `lit:`，按题名认条目
    （同一套判据，两种条目形态）。
    """
    bad: list[str] = []
    entries = _report_blocks(admitted_text, numbered=numbered)
    for key, body in entries:
        where = f"`lit:{key}`" if numbered else f"《{key}》"
        hit = _REPORT_AVAILABILITY.search(body)
        if hit is None:
            bad.append(f"已入库的 {where} 没有「可得性」一栏（四块都要逐条列，业主裁定 ⑥）")
            continue
        tier = hit.group(1)
        if not LAV.is_admissible(tier):
            bad.append(f"已入库的 {where} 可读性是 `{tier}` —— 这一档不许入库"
                       "（业主裁定 ③：extract_failed / unknown 不许进文献库）")
    return bad


def _report_blocks(text: str, *, numbered: bool = True) -> list[tuple[str, str]]:
    """把「已入库」一块切成 `(条目键, 这一条的正文含后续缩进行)`。

    报告的一条规定是：条目行以 ``- `lit:…` 《题名》`` 开头（定稿）或以
    ``- 《题名》`` 开头（交报告原件 / 判收未注册），紧跟的行（`理由（相关性）：` /
    `可得性：`）以两个空格缩进。这一函数只认这两种形状，不猜别的写法。
    """
    out: list[tuple[str, str]] = []
    current = ""
    buf: list[str] = []
    row_re = _REPORT_ADMITTED_ROW if numbered else _REPORT_QUALIFIED_ROW
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        hit = row_re.match(line.strip())
        if hit:
            if current:
                out.append((current, "\n".join(buf)))
            current = hit.group(1)
            buf = [line]
            continue
        if current and (line.startswith("  ") or not line.strip()):
            buf.append(line)
        elif current:
            out.append((current, "\n".join(buf)))
            current = ""
            buf = []
    if current:
        out.append((current, "\n".join(buf)))
    return out


#: 报告「已入库」一块里一条条目的开头形态：`- `lit:000000` 《题名》…`。
#:
#: 判据要按条目读回紧跟其后的那行 `相关性：`，就必须能认出"新条目从这里开始"。
#: 不用"所有以 `- ` 开头的行"：缺相关性时报告里还有一行汇总条目
#: （`- 缺相关性说明的条目（N 篇）：…`），它也以 `- ` 开头。
_REPORT_ADMITTED_ROW = re.compile(r"^-\s*`lit:([^`]+)`\s*《")

#: 「交报告原件 / 判收未注册」那一条目的开头形态：`- 《题名》…`（没有号）。
#:
#: 与上面那一条分开是因为它们回答的号规则相反：定稿必须带号、原件必须不带号。
_REPORT_QUALIFIED_ROW = re.compile(r"^-\s*《([^》]+)》")


def _relevance_violations(admitted_text: str) -> list[str]:
    """已入库的条目 relevance 全空 ⇒ 一条违规读数（只记读数，不拦门）。

    为什么要这一档：`relevance` 是"它为什么与本次检索相关"的那一句，报告「已入库」
    一块要用它（AR1 之后它的行名是 `理由（相关性）：` —— 判定之后紧跟的那一句就是
    A 自己写的理由）；而 A 的自动链路暂存候选时一次
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
        if current and line.startswith("理由（相关性）：") and "未写" in line:
            missing.append(current)
    if entries and len(missing) == len(entries):
        return [
            f"已入库 {len(entries)} 篇的 relevance 全空（A 没写「为什么与本次检索相关」）；"
            "这一条只记读数，不拦门"
        ]
    return []
